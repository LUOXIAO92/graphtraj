"""The swarm launch entry activates Agents from the caller's Task context."""

from __future__ import annotations

from pathlib import Path

import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_task_graph import _task


TASK_ID   = "139"
TASK_NAME = "swarm-task-activation"


def _swarm_input(root: Path, tasks: list[dict]) -> Path:
    """Write one launch input naming role aliases and launch instructions."""

    path = root / "swarm.yml"
    path.write_text(
        yaml.safe_dump({"tasks": tasks}, sort_keys=False), encoding="utf-8"
    )
    return path


def _inline_task(name: str, instruction: str, task_id: str | None = None) -> dict:
    """Select an inline role and, for Main, its DAG selection."""

    task = {
        "role": {name: {"runtime": "codex", "model": "gpt-5.6-luna"}},
        "instruction": instruction,
    }
    return task if task_id is None else {"task_id": task_id, **task}


def _task_directory(root: Path) -> Path:
    return root / ".graphtraj/state/tasks" / (TASK_ID + "-" + TASK_NAME)


def _cause(root: Path) -> str:
    """Record one Main decision and return its event identity."""

    from graphtraj.graph.delivery_worldline import append_project_worldline_event

    instruction = root / "instruction.md"
    instruction.write_text("Use the activated Agent.\n", encoding="utf-8")
    return append_project_worldline_event(
        root / ".graphtraj/state",
        root,
        {
            "event":                "main-decision",
            "decision":            "Use the activated Agent.",
            "caused_by_event_ids": [],
            "evidence_refs":       ["instruction.md"],
        },
    )["event_id"]


def test_swarm_input_starts_each_selected_agent_from_the_registered_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """One input starts two Agents; each returns the alias it is reached by."""

    from graphtraj.execution.runner_batch import read_batch
    from graphtraj.graph.task_graph import register_task

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    register_task(root / ".graphtraj/state", root, _task(TASK_ID, TASK_NAME))
    from test_task_graph import _change_status
    _change_status(installed_commands, root, TASK_ID, 'ready')
    role_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(role_file.read_text())
    roles['role_tree'] = {'probe-one': {}, 'probe-two': {}}
    role_file.write_text(yaml.safe_dump(roles))

    swarm = _swarm_input(
        root,
        [
            _inline_task("probe-one", "Inspect the accepted Task.", TASK_ID),
            _inline_task("probe-two", "Inspect the Task guards.", TASK_ID),
        ],
    )
    assert "task_name" not in swarm.read_text(encoding="utf-8")
    completed = run_process(
        [str(installed_commands.runner), "--swarm-input", str(swarm)],
        cwd=root, env=environment, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = yaml.safe_load(completed.stdout)
    launched = document["tasks"]
    assert [task["launch_status"] for task in launched] == ["launched", "launched"]
    for task, role in zip(launched, ("probe-one", "probe-two")):
        # The current Task and the alias the Agent is reached by afterwards.
        assert (task["task_id"], task["task_name"], task["role"]) == (
            TASK_ID, TASK_NAME, role,
        )
        entity = role.replace("-", "_")
        assert task["alias"] == (
            "{0}-swarm_task_activation-handover0-{1}@{1}".format(TASK_ID, entity)
        )

    # The retained record carries the Task the input left out, so a later
    # read of the Team's record still locates each task without that input.
    retained = read_batch(Path(document["retained_batch_file"]), root)
    assert [(task.task_id, task.task_name, task.role) for task in retained.tasks] == [
        (TASK_ID, TASK_NAME, "probe-one"),
        (TASK_ID, TASK_NAME, "probe-two"),
    ]
    assert "task_name" in Path(document["retained_batch_file"]).read_text(
        encoding="utf-8"
    )

    team = yaml.safe_load((_task_directory(root) / 'teams/1/team.yml').read_text())
    assert {member['role'] for member in team['members'].values()} == {'probe-one', 'probe-two'}
    assert len(team['members']) == 2
    task_state = (_task_directory(root) / 'task.yml').read_bytes()

    # Later interaction addresses the alias alone, and the ordinary message
    # does not rewrite the current Task definition.
    alias = launched[0]["alias"]
    status = run_process(
        [str(installed_commands.runner), "status", alias],
        cwd=root, env=environment, timeout=30,
    )
    assert status.returncode == 0, status.stderr
    observed, = yaml.safe_load(status.stdout)["aliases"]
    assert observed["alias"] == alias
    assert observed["session"] == launched[0]["session"]
    message = run_process(
        [
            str(installed_commands.runner), "send", alias,
            "--instruction", "Report your current activity.",
            "--caused-by-event-id", _cause(root),
        ],
        cwd=root, env=environment, timeout=60,
    )
    assert message.returncode == 0, message.stdout + message.stderr
    assert (_task_directory(root) / "task.yml").read_bytes() == task_state
    assert (root / ".graphtraj/state/batches").is_dir()


def test_swarm_input_refuses_task_identity_it_cannot_project(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A selection outside the registered Tasks, or a second DAG, is refused."""

    from graphtraj.graph.task_graph import register_task

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    register_task(root / ".graphtraj/state", root, _task(TASK_ID, TASK_NAME))

    unregistered = _swarm_input(
        root, [{"task_id": "999", **_inline_task("probe", "Inspect the Task.")}],
    )
    refused = run_process(
        [str(installed_commands.runner), "--swarm-input", str(unregistered)],
        cwd=root, env=environment, timeout=60,
    )
    assert refused.returncode == 1, refused.stdout
    assert yaml.safe_load(refused.stdout)["error"]["code"] == "invalid-task"

    dependencies = _swarm_input(
        root,
        [
            _inline_task("probe", "Inspect the Task.")
            | {"task_id": TASK_ID, "dependencies": ["135"]}
        ],
    )
    refused = run_process(
        [str(installed_commands.runner), "--swarm-input", str(dependencies)],
        cwd=root, env=environment, timeout=60,
    )
    assert refused.returncode == 1, refused.stdout
    assert yaml.safe_load(refused.stdout)["error"]["code"] == "invalid-input"
    assert not list((root / ".graphtraj/state/batches").glob("*.yml"))
    assert not list((root / ".graphtraj/runner/sessions").glob("*/mapping.yml"))
