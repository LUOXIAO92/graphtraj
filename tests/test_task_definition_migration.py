"""Behavior of ``graphtraj migrate-task-definitions`` on state with an unversioned task.md."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, current_definition, initial_definition, run_process
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.graph.task_graph import register_task, revise_tasks
from test_task_graph import _configure, _task
from test_task_migration import _snapshot


def _retired_layout(tmp_path: Path) -> Path:
    """Return state written before versioned names: Task 1 with one version, Task 2 with two.

    Tasks are registered and revised through the product, then each initial
    definition is put back at the retired name ``task.md`` (read-only), and
    ``current_definition`` names it where the Task was never revised.
    """
    state = _configure(tmp_path)
    register_task(state, tmp_path, _task("1", "single"))
    register_task(state, tmp_path, _task("2", "revised"))
    (tmp_path / "evidence.md").write_text("Revise Task 2.\n", encoding="utf-8")
    revise_tasks(state, tmp_path, {
        "product_preserving": True, "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
        "tasks": [{**_task("2", "revised"), "body": "Deliver the revised text.",
                   "current_definition": current_definition(state, "2")}],
    })
    for directory in sorted((state / "tasks").glob("[0-9]*")):
        initial = initial_definition(directory)
        os.rename(initial, directory / "task.md")
        record = yaml.safe_load((directory / "task.yml").read_text(encoding="utf-8"))
        if record["current_definition"] == initial.relative_to(directory).as_posix():
            record["current_definition"] = "task.md"
            (directory / "task.yml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    (state / "task-index.json").unlink(missing_ok=True)
    return state


def _migrate(commands: InstalledCommands, root: Path, *options: str):
    return run_process([str(commands.product), "migrate-task-definitions", *options], cwd=root)


def test_migration_renames_initial_text_and_keeps_every_version(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    """Preview writes nothing; the migration renames, records, backs up and runs only once."""
    state  = _retired_layout(tmp_path)
    tasks  = state / "tasks"
    events = {event["task_id"]: event["event_id"] for event in read_worldline(state)
              if event["event"] == "task-registered"}
    texts  = {task_id: (tasks / name / "task.md").read_bytes() for task_id, name in (("1", "1-single"), ("2", "2-revised"))}
    revision = current_definition(state, "2")

    refused = run_process([str(installed_commands.product), "task", "graph"], cwd=tmp_path)
    assert refused.returncode != 0 and "migrate-task-definitions" in refused.stderr

    before  = _snapshot(tmp_path)
    preview = _migrate(installed_commands, tmp_path, "--preview")
    assert preview.returncode == 0, preview.stderr
    assert _snapshot(tmp_path) == before
    planned = yaml.safe_load(preview.stdout)
    assert [(item["task_id"], item["to"], item["current_definition_updated"]) for item in planned["renamed"]] == [
        ("1", f".graphtraj/state/tasks/1-single/definitions/{events['1']}.md", True),
        ("2", f".graphtraj/state/tasks/2-revised/definitions/{events['2']}.md", False),
    ]

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    report = yaml.safe_load(result.stdout)
    for task_id, name in (("1", "1-single"), ("2", "2-revised")):
        initial = tasks / name / f"definitions/{events[task_id]}.md"
        assert not (tasks / name / "task.md").exists()
        assert initial.read_bytes() == texts[task_id]
        assert initial.stat().st_mode & 0o777 == 0o444
        assert (tmp_path / report["backup"] / f".graphtraj/state/tasks/{name}/task.md").read_bytes() == texts[task_id]
    assert current_definition(state, "1") == f"definitions/{events['1']}.md"
    # Task 2 keeps its later revision current; its initial text sorts first.
    assert current_definition(state, "2") == revision
    assert [path.name for path in sorted((tasks / "2-revised/definitions").iterdir())] == [
        f"{events['2']}.md", revision.split("/")[-1]]

    recorded = read_worldline(state)[-1]
    assert recorded["event"] == "task-definitions-renamed" and recorded["event_id"] == report["event_id"]
    assert recorded["renamed_definitions"] == {
        ".graphtraj/state/tasks/1-single/task.md": f".graphtraj/state/tasks/1-single/definitions/{events['1']}.md",
        ".graphtraj/state/tasks/2-revised/task.md": f".graphtraj/state/tasks/2-revised/definitions/{events['2']}.md",
    }
    graph = run_process([str(installed_commands.product), "task", "graph", "--view", "full",
                         "--details", "1", "--details", "2"], cwd=tmp_path)
    assert graph.returncode == 0, graph.stderr
    details = yaml.safe_load(graph.stdout)["details"]
    assert details["1"]["body"] == "Deliver single." and details["2"]["body"] == "Deliver the revised text."

    after = _snapshot(tmp_path)
    again = _migrate(installed_commands, tmp_path)
    assert again.returncode == 0, again.stderr
    assert yaml.safe_load(again.stdout)["renamed"] == []
    assert _snapshot(tmp_path) == after


@pytest.mark.parametrize("layout", ["linked-task-md", "irregular-definition", "no-creation-event"])
def test_unsupported_layout_stops_before_any_change(
    installed_commands: InstalledCommands, tmp_path: Path, layout: str,
) -> None:
    """One unsupported Task stops the migration for every Task, naming that Task."""
    state = _retired_layout(tmp_path)
    task  = state / "tasks/2-revised"
    if layout == "linked-task-md":
        text = (task / "task.md").read_bytes()
        (task / "task.md").unlink()
        (tmp_path / "elsewhere.md").write_bytes(text)
        (task / "task.md").symlink_to(tmp_path / "elsewhere.md")
    elif layout == "irregular-definition":
        (task / "definitions/notes.md").write_text("Not a definition version.\n", encoding="utf-8")
    else:
        # A Task directory that no Worldline event created.
        (state / "tasks/3-unrecorded").mkdir()
        (state / "tasks/3-unrecorded/task.md").write_bytes((task / "task.md").read_bytes())
        (state / "tasks/3-unrecorded/task.yml").write_text(yaml.safe_dump({
            "task_id": "3", "task_name": "unrecorded", "current_definition": "task.md"}), encoding="utf-8")
    before = _snapshot(tmp_path)

    result = _migrate(installed_commands, tmp_path)

    assert result.returncode != 0
    assert "Task 2" in result.stderr or "Task 3" in result.stderr or "2-revised" in result.stderr
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / ".graphtraj/backups").exists()
