"""Installation from the built distribution wheel and upgrade of a live project.

Every command here comes from a wheel built from this working tree, which is
the artifact an operator installs. The upgrade check runs a second, freshly
installed environment against a project the earlier installation created.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process
from test_existing_repository_setup import run_setup
from test_mcp_host_tools import TOOL_NAMES, _started_mcp
from test_ticket_graph import _ticket, _write


RESOURCE_DIRECTORIES = (
    "graphtraj/resources/roles/",
    "graphtraj/resources/codex/agents/",
    "graphtraj/resources/skills/",
)


def installed_provenance(installed_commands: InstalledCommands) -> dict:
    """Return the install source pip recorded inside the installed environment."""

    site_packages = installed_commands.product.parent.parent / "lib"
    recorded = next(
        site_packages.glob(
            "python*/site-packages/graphtraj-*.dist-info/direct_url.json"
        )
    )
    return json.loads(recorded.read_text(encoding="utf-8"))


def test_built_wheel_carries_the_commands_and_their_packaged_resources(
    built_wheel: Path,
) -> None:
    """The artifact an operator installs contains every command and resource."""

    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
        entry_points = next(
            archive.read(name).decode("utf-8")
            for name in names
            if name.endswith(".dist-info/entry_points.txt")
        )

    assert "graphtraj/interfaces/cli/graphtraj.py" in names
    assert "graphtraj/interfaces/mcp.py" in names
    for directory in RESOURCE_DIRECTORIES:
        assert any(name.startswith(directory) for name in names), directory
    assert sum(name.endswith("/SKILL.md") for name in names) == 18
    assert any(name.endswith("/references/coding.md") for name in names)
    assert {
        line.split(" = ")[0]
        for line in entry_points.splitlines()
        if " = " in line
    } == {"graphtraj", "agent-runner", "graphtraj-mcp"}


def test_installed_commands_come_from_the_built_wheel(
    built_wheel: Path,
    installed_commands: InstalledCommands,
) -> None:
    """The environment under test installed that wheel, not a source directory."""

    provenance = installed_provenance(installed_commands)

    assert provenance["url"] == built_wheel.as_uri()
    assert provenance["archive_info"]["hash"] == "sha256={0}".format(
        hashlib.sha256(built_wheel.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("same_root", (True, False))
def test_installed_wheel_initializes_both_layouts_and_serves_host_tools(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    same_root: bool,
) -> None:
    """A wheel installation sets up, repeats setup and answers host calls."""

    harness_root = (
        temporary_git_repository if same_root else temporary_git_repository.parent
    )
    configuration = harness_root / ".graphtraj" / "config.yml"

    first = run_setup(installed_commands, harness_root)
    assert first.returncode == 0, first.stdout + first.stderr
    configured = configuration.read_bytes()
    help_result = run_process(
        [str(installed_commands.product), "--help"], cwd=harness_root
    )
    assert help_result.returncode == 0, help_result.stderr

    second = run_setup(installed_commands, harness_root, answers="")
    assert second.returncode == 0, second.stdout + second.stderr
    assert configuration.read_bytes() == configured
    assert (harness_root / ".graphtraj" / ".agent-worktrees" / "dev").is_dir()

    # Doctor resolves every core Skill and role from the installed wheel.
    doctor = run_process(
        [str(installed_commands.product), "doctor"], cwd=harness_root
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr

    mcp_executable = installed_commands.product.with_name("graphtraj-mcp")
    with _started_mcp(mcp_executable, harness_root) as server:
        discovered = server.request("tools/list")["result"]["tools"]
        call = server.call("ticket_graph", {})

    assert {tool["name"] for tool in discovered} == TOOL_NAMES
    assert call["result"]["isError"] is False
    assert call["result"]["structuredContent"] == {"tickets": []}


def test_upgrading_the_installation_preserves_existing_project_records(
    installed_commands: InstalledCommands,
    mutable_installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    """A newer installation keeps the existing project's configuration and history."""

    repository = temporary_git_repository
    assert run_setup(installed_commands, repository).returncode == 0

    # Operator-owned configuration and selections made before the upgrade.
    user_config = repository / ".codex" / "config.toml"
    user_config.parent.mkdir(exist_ok=True)
    user_config.write_text('model = "operator-model"\n', encoding="utf-8")
    roles = repository / ".graphtraj" / "roles.yml"
    roles.write_bytes(
        roles.read_bytes().replace(
            b"model: gpt-5.6-luna", b"model: operator-selected-model", 1
        )
    )
    operator_skill = repository / ".agents" / "skills" / "implement" / "SKILL.md"
    operator_skill.write_text(
        "---\nname: implement\ndescription: Operator copy.\n---\n",
        encoding="utf-8",
    )
    selections = {
        "roles": roles.read_bytes(),
        "skill": operator_skill.read_bytes(),
        "user_config": user_config.read_bytes(),
    }

    # Delivery history recorded through the installed commands.
    registered = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "register",
            "--ticket-file",
            str(_write(repository / "issue.yml", _ticket("119", "runtime-core-install"))),
        ],
        cwd=repository,
    )
    assert registered.returncode == 0, registered.stderr
    (repository / "evidence.md").write_text(
        "Main approved this Ticket.\n", encoding="utf-8"
    )
    changed = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "update",
            "--state-file",
            str(
                _write(
                    repository / "state-change.yml",
                    {
                        "ticket_id":            "119",
                        "status":               "ready",
                        "active_team_ordinal":  None,
                        "worktree":             None,
                        "branch":               None,
                        "current_candidate":    None,
                        "caused_by_event_ids":  [],
                        "evidence_refs":        ["evidence.md"],
                    },
                )
            ),
        ],
        cwd=repository,
    )
    assert changed.returncode == 0, changed.stderr
    history_before = {
        command: run_process(
            [str(installed_commands.product), *command], cwd=repository
        ).stdout
        for command in (("ticket", "graph"), ("worldline", "read"))
    }
    assert yaml.safe_load(history_before[("ticket", "graph")])["tickets"][0][
        "status"
    ] == "ready"

    # The upgraded installation continues on the same existing project.
    upgraded = mutable_installed_commands
    repeated = run_setup(upgraded, repository, answers="")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr

    history_after = {
        command: run_process(
            [str(upgraded.product), *command], cwd=repository
        ).stdout
        for command in (("ticket", "graph"), ("worldline", "read"))
    }
    assert history_after == history_before
    assert roles.read_bytes() == selections["roles"]
    assert operator_skill.read_bytes() == selections["skill"]
    assert user_config.read_bytes() == selections["user_config"]
    doctor = run_process([str(upgraded.product), "doctor"], cwd=repository)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
