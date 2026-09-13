"""Coding Team delivery through the installed public Runner operations."""

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_managed_sessions import CALL


def ready_team(root: Path, body: str) -> Path:
    """Register an isolated, ready Ticket using the public graph operations."""
    from graphtraj.graph.ticket_graph import register_ticket, update_ticket_state

    state = root / ".graphtraj/state"
    directory = register_ticket(state, root, {
        "ticket_id": "114", "ticket_name": "small-team",
        "source": "https://github.com/example/project/issues/114",
        "title": "Deliver a greeting", "body": body, "dependencies": [],
    })
    (root / "readiness.md").write_text("This isolated Ticket is ready.\n")
    update_ticket_state(state, root, {
        "ticket_id": "114", "status": "ready", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["readiness.md"],
    })
    return directory


def test_dispatch_depth_one_stops_before_registering_team_children(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A depth-one Leader cannot register or execute a depth-two Engineer."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    ready_team(root, "Deliver one complete Team Round.")
    configuration_file = root / ".graphtraj/config.yml"
    configuration = yaml.safe_load(configuration_file.read_text())
    configuration["agent_runner"]["dispatch_depth"] = 1
    configuration_file.write_text(yaml.safe_dump(configuration))
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    environment.pop("PYTHONPATH", None)
    result = run_process([
        str(installed_commands.runner.with_name("python")), "-c", CALL, str(root),
        json.dumps(["launch", {"tasks": [{
            "ticket_id": "114", "ticket_name": "small-team", "role": "team-leader",
        }]}]),
    ], cwd=root, env=environment, timeout=30)
    task = json.loads(result.stdout)["tasks"][0]
    assert task["launch_status"] == "failed", task
    assert "dispatch_depth" in task["error"]["message"]
    assert len(list((root / ".graphtraj/state/batches").glob("*.yml"))) == 1
    mappings = [yaml.safe_load(path.read_text()) for path in
                (root / ".graphtraj/runner/sessions").glob("*/mapping.yml")]
    assert [mapping["role"] for mapping in mappings] == ["team-leader"]


def test_engineer_cannot_launch_as_main(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A delegated leaf's Runner context cannot reset its depth by using Main's entry."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    ready_team(root, "Deliver one complete Team Round.")
    environment.update(
        GRAPHTRAJ_ROLE="engineer-junior",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
    )
    environment.pop("PYTHONPATH", None)
    result = run_process([
        str(installed_commands.runner.with_name("python")), "-c", CALL, str(root),
        json.dumps(["launch", {"tasks": [{
            "ticket_id": "114", "ticket_name": "small-team", "role": "team-leader",
        }]}]),
    ], cwd=root, env=environment, timeout=30)
    assert json.loads(result.stdout).get("error", {}).get("code") == "authority-denied", result.stdout
    assert not list((root / ".graphtraj/state/batches").glob("*.yml"))
    assert not list((root / ".graphtraj/runner/sessions").glob("*/mapping.yml"))


@pytest.mark.parametrize("capacity", [2, 1])
def test_public_team_phases_and_parent_capacity_transfer(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    capacity: int,
) -> None:
    """Observe implementation, fixed Review and acceptance while roles use shared capacity."""
    from graphtraj.execution.runner_status import read_alias_mapping, status_aliases
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.ticket_graph import read_graph
    from test_project_concurrency import observe_runtime, starts

    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    ticket = ready_team(root, "Deliver one complete Team Round.")
    state = root / ".graphtraj/state"
    assert read_graph(state)["tickets"][0]["status"] == "ready"
    configuration_file = root / ".graphtraj/config.yml"
    configuration = yaml.safe_load(configuration_file.read_text())
    configuration["agent_runner"]["max_concurrency"] = capacity
    configuration_file.write_text(yaml.safe_dump(configuration))
    engineer_release = root / "engineer-release"
    review_release = root / "review-release"
    environment.update(
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        FAKE_CODEX_ENGINEER_RELEASE_FILE=str(engineer_release),
        FAKE_CODEX_REVIEW_RELEASE_FILE=str(review_release),
    )
    if capacity == 1:
        environment["FAKE_CODEX_SERIAL_TEAM"] = "1"
    environment.pop("PYTHONPATH", None)
    observe_runtime(fake_codex, root, environment)
    (root / "release").touch()
    process = subprocess.Popen([
        str(installed_commands.runner.with_name("python")), "-c", CALL, str(root),
        json.dumps(["launch", {"tasks": [{
            "ticket_id": "114", "ticket_name": "small-team", "role": "team-leader",
        }]}]),
    ], cwd=root, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    runner = root / ".graphtraj/runner"
    leader = "114-small-team@l1"

    def running_child(alias: str) -> dict:
        """Read a child's public identity and status while its model work is held."""
        wait_for_file(runner / "sessions" / alias / "mapping.yml", timeout=20)
        mapping, _ = read_alias_mapping(runner, alias)
        assert mapping["parent"] == leader
        assert mapping["worktree_path"] == str(worktrees / "114-small-team")
        assert mapping["ticket_id"] == "114" and mapping["team_generation"] == 1
        observed = status_aliases([alias, leader], root)
        assert observed.succeeded, observed.document
        child, parent = observed.document["aliases"]
        assert child["activity"] == "running"
        assert child["session"] == mapping["session"] and child["execution_id"] == mapping["execution_id"]
        assert parent["activity"] == "idle" and parent["last_outcome"] == "completed"
        return mapping

    try:
        engineer = running_child("114-small-team@j1")
        assert engineer["role"] == "engineer-junior"
        assert read_graph(state)["tickets"][0]["status"] == "implementing"
        engineer_release.touch()
        assert running_child("114-small-team@r1")["role"] == "standards-reviewer"
        if capacity == 2:
            assert running_child("114-small-team@r2")["role"] == "spec-reviewer"
        reviewing = read_graph(state)["tickets"][0]
        assert reviewing["status"] == "reviewing"
        candidate = next(event["candidate"] for event in read_worldline(state, root)
                         if event["kind"] == "candidate-ready-for-review")
        assert len(candidate) == 40
    finally:
        engineer_release.touch()
        review_release.touch()
        stdout, stderr = process.communicate(timeout=45)
    assert process.returncode == 0, stdout + stderr
    assert json.loads(stdout)["tasks"][0]["launch_status"] == "accepted"
    accepted = read_graph(state)["tickets"][0]
    assert accepted["status"] == "awaiting-integration"
    assert read_worldline(state, root)[-1]["candidate"] == candidate
    reports = ticket / "teams/1/rounds/1"
    assert {path.name for path in reports.iterdir()} == {
        "engineer.md", "validation.md", "standards.md", "spec.md", "leader.md",
    }
    assert all(candidate in path.read_text() for path in reports.iterdir())
    aliases = [path.parent.name for path in (runner / "sessions").glob("*/mapping.yml")]
    assert len(aliases) == 5
    assert all(item["activity"] == "idle" and item["last_outcome"] == "completed"
               for item in status_aliases(aliases, root).document["aliases"])
    active = set()
    peak = 0
    for event in starts(root, 1):
        if event["kind"] == "start":
            active.add(event["pid"])
            peak = max(peak, len(active))
        else:
            active.remove(event["pid"])
        assert len(active) <= capacity
    assert not active and peak == capacity


@pytest.mark.skipif(
    os.environ.get("CODEX_TEAM_REAL") != "1",
    reason="explicit real Codex small-Team acceptance probe",
)
def test_real_small_team(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Require actual implementation, fixed-candidate reports and Leader acceptance."""
    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    real = shutil.which("codex")
    assert real
    fake_codex.executable.unlink()
    fake_codex.executable.symlink_to(real)
    native_home = root / "native-home"
    native_home.mkdir()
    operator = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    originals = {}
    for name in ("config.toml", "auth.json"):
        path = operator / name
        if path.is_file():
            originals[path] = path.read_bytes()
            shutil.copy2(path, native_home / name)
    config_file = native_home / "config.toml"
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
    model = os.environ.get("CODEX_TEAM_MODEL", config.get("model", "gpt-5.6"))
    roles_file = root / ".graphtraj/roles.yml"
    roles = yaml.safe_load(roles_file.read_text())
    for preset in [*roles["roles"]["coding-team"].values(), roles["roles"]["delivery-state"]]:
        preset.update(model=model, reasoning_effort="low")
    roles["roles"]["coding-team"]["team-leader"]["allow_runtime_swarm"] = False
    roles_file.write_text(yaml.safe_dump(roles))
    limits = root / ".graphtraj/config.yml"
    configuration = yaml.safe_load(limits.read_text())
    configuration["agent_runner"]["max_concurrency"] = int(os.environ.get("CODEX_TEAM_CAPACITY", "1"))
    limits.write_text(yaml.safe_dump(configuration))
    ticket = ready_team(root, (
        "Implement greeting.py with greet(name: str) -> str returning 'Hello, ' + name + '!'. "
        "Add test_greeting.py with a standard-library unittest proving greet('Ada') == 'Hello, Ada!'. "
        "No dependencies. Commit the implementation and record actual validation and self-review. "
        "The Leader must run the normal Engineer, fixed candidate, Standards/Spec Review "
        "and final decision flow. This is an isolated validation Ticket."
    ))
    python = installed_commands.runner.with_name("python")
    environment.update(CODEX_HOME=str(native_home))
    environment.pop("PYTHONPATH", None)
    environment["PATH"] = str(python.parent) + os.pathsep + environment["PATH"]
    instruction = (
        "For the team-leader only: select coding-team.engineer-junior for this bounded probe. "
        "Use the installed public Python Runner operations for child registration: "
        f"{python} -c 'from pathlib import Path; from graphtraj.execution.runner_batch import parse_batch; "
        "from graphtraj.execution.runner_launch import launch_batch; "
        "print(launch_batch(parse_batch(...), Path.cwd()).document)'. "
        "Supply the actual task mapping in place of ...; then end this turn. "
        "At insufficient-capacity, register each Reviewer separately. "
        "Do not invoke native helpers."
    )
    document = {"tasks": [{
        "ticket_id": "114", "ticket_name": "small-team", "role": "team-leader",
        "instruction": instruction,
    }]}
    (root / "real-team-input.json").write_text(json.dumps(document, indent=2))
    try:
        result = run_process(
            [str(python), "-c", CALL, str(root), json.dumps(["launch", document])],
            cwd=root, env=environment,
            timeout=float(os.environ.get("CODEX_TEAM_WAIT", "900")),
        )
        (root / "real-team-result.json").write_text(json.dumps({
            "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "model": model, "max_concurrency": configuration["agent_runner"]["max_concurrency"],
        }, indent=2))
        assert result.returncode == 0, result.stdout + result.stderr
        task = json.loads(result.stdout)["tasks"][0]
        assert task["launch_status"] == "accepted", task
        worktree = worktrees / "114-small-team"
        verified = run_process([str(python), "-m", "unittest", "discover"], cwd=worktree)
        assert verified.returncode == 0, verified.stdout + verified.stderr
        checked = run_process([
            str(python), "-c", "from greeting import greet; assert greet('Ada') == 'Hello, Ada!'",
        ], cwd=worktree)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert (worktree / "test_greeting.py").is_file()
        candidate = run_process(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
        reports = ticket / "teams/1/rounds/1"
        assert {path.name for path in reports.iterdir()} == {
            "engineer.md", "validation.md", "standards.md", "spec.md", "leader.md",
        }
        assert all(candidate in path.read_text() for path in reports.iterdir())
        assert "Decision: ACCEPT" in (reports / "leader.md").read_text()
        mappings = [yaml.safe_load(path.read_text()) for path in
                    (root / ".graphtraj/runner/sessions").glob("*/mapping.yml")]
        assert {mapping["role"] for mapping in mappings} == {
            "team-leader", "engineer-junior", "standards-reviewer", "spec-reviewer", "delivery-state",
        }
        assert len({mapping["session"] for mapping in mappings}) == 5
        assert all(mapping["worktree_path"] == str(worktree) for mapping in mappings)
        assert all(mapping["parent"] == task["alias"] for mapping in mappings
                   if mapping["role"] != "team-leader")
    except subprocess.TimeoutExpired as error:
        (root / "real-team-result.json").write_text(json.dumps({
            "timeout": error.timeout, "model": model,
            "max_concurrency": configuration["agent_runner"]["max_concurrency"],
        }, indent=2))
        raise
    finally:
        from graphtraj.execution.runner_control import interrupt_session
        from graphtraj.execution.runner_models import RunnerError
        from graphtraj.execution.runner_status import status_aliases

        cleanup = []
        for path in (root / ".graphtraj/runner/sessions").glob("*/mapping.yml"):
            alias = path.parent.name
            observed = status_aliases([alias], root).document["aliases"][0]
            cleanup.append(observed)
            if observed.get("activity") == "running":
                try:
                    cleanup.append(interrupt_session(alias, root))
                except RunnerError as error:
                    cleanup.append({"alias": alias, "error": error.as_document()})
        (root / "real-team-cleanup.json").write_text(json.dumps(cleanup, indent=2))
        assert all(path.read_bytes() == content for path, content in originals.items())
