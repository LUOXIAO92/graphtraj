"""Behavior of the one-time ``graphtraj migrate-tickets`` conversion."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process

REVISION = "definitions/20261015T070000.000000+0900.md"


def _definition(task_id: str, name: str, parent: str | None, body: str) -> str:
    """Render one retained Ticket-format v2 definition."""
    metadata = {"task": {
        "ticket_id": task_id, "ticket_name": name, "source": f"local:task/{task_id}",
        "title": f"Sample {name}", "dependencies": [], "schema_version": 2, "parent_id": parent,
        "disposition": "active", "replaced_by": [], "retirement_reason": None,
    }}
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + body


def _ticket_project(root: Path) -> dict[str, Path]:
    """Write a retained Ticket-format project with Team, Worktree and Runner records."""
    graphtraj = root / ".graphtraj"
    graphtraj.mkdir()
    (graphtraj / "config.yml").write_text(yaml.safe_dump({
        "version": 1,
        "paths": {"project_root": ".", "docs": "docs", "agent_worktrees": ".graphtraj/worktrees",
                  "state": ".graphtraj/state"},
        "agent_runner": {"dispatch_depth": 1, "max_concurrency": 2},
    }, sort_keys=False))
    tickets = graphtraj / "state/tickets"
    for task_id, name, parent, current in (("1", "summary", None, "ticket.md"),
                                           ("2", "child", "1", REVISION)):
        directory = tickets / f"{task_id}-{name}"
        (directory / "definitions").mkdir(parents=True)
        (directory / "ticket.md").write_text(_definition(task_id, name, parent, f"Body of ticket {task_id}.\n"))
        if current != "ticket.md":
            (directory / current).write_text(_definition(task_id, name, parent, "Revised ticket body.\n"))
        (directory / "ticket.yml").write_text(yaml.safe_dump({
            "ticket_id": task_id, "ticket_name": name, "current_definition": current,
            "status": "implementing" if task_id == "2" else "pending",
            "active_team_ordinal": 1 if task_id == "2" else None,
            "worktree": None, "branch": None, "current_candidate": None, "schema_version": 2,
        }, sort_keys=False))
    report = tickets / "2-child/teams/1/rounds/1/engineer.md"
    report.parent.mkdir(parents=True)
    report.write_text("Report mentions ticket-completed and state/tickets literally.\n")
    worktree = graphtraj / "worktrees/2-child"
    worktree.mkdir(parents=True)
    (worktree / ".state").symlink_to(os.path.relpath(tickets / "2-child", worktree), target_is_directory=True)
    session = graphtraj / "runner/sample"
    session.mkdir(parents=True)
    (session / "mapping.yml").write_text(yaml.safe_dump({
        "alias": "2-child@engineer", "ticket_id": "2", "ticket_name": "child", "session": "native-1",
        "report_file": ".graphtraj/state/tickets/2-child/teams/1/rounds/1/engineer.md",
        "instruction": "Fix ticket 2 under state/tickets.", "launch_status": "ticket-already-live",
    }))
    (session / "session.jsonl").write_text('{"arguments": {"ticket_id": "2"}}\n')
    return {"report": report, "worktree": worktree, "session": session}


def _snapshot(root: Path) -> dict[str, object]:
    """Capture every retained file and link below ``.graphtraj``."""
    return {str(path.relative_to(root)): os.readlink(path) if path.is_symlink() else path.read_bytes()
            for path in sorted((root / ".graphtraj").rglob("*"))
            if path.is_symlink() or path.is_file()}


def _migrate(commands: InstalledCommands, root: Path):
    return run_process([str(commands.product), "migrate-tickets"], cwd=root)


def test_migration_converts_structure_and_keeps_text_and_identity(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    paths  = _ticket_project(tmp_path)
    before = _snapshot(tmp_path)

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["backup"].startswith(".graphtraj/backups/")
    assert _migrate(installed_commands, tmp_path).returncode != 0

    graph = run_process([str(installed_commands.product), "task", "graph"], cwd=tmp_path)
    assert graph.returncode == 0, graph.stderr
    tasks = {task["task_id"]: task for task in yaml.safe_load(graph.stdout)["tasks"]}
    assert tasks["1"]["children"] == ["2"] and tasks["2"]["parent_id"] == "1"
    assert tasks["2"]["current_definition"] == REVISION and tasks["2"]["status"] == "implementing"
    assert tasks["2"]["body"] == "Revised ticket body.\n" and tasks["1"]["current_definition"] == "task.md"

    state = tmp_path / ".graphtraj/state/tasks/2-child"
    assert (state / "teams/1/rounds/1/engineer.md").read_bytes() == before[
        ".graphtraj/state/tickets/2-child/teams/1/rounds/1/engineer.md"]
    assert (paths["worktree"] / ".state").resolve() == state.resolve()
    mapping = yaml.safe_load((paths["session"] / "mapping.yml").read_text())
    assert mapping == {
        "alias": "2-child@engineer", "task_id": "2", "task_name": "child", "session": "native-1",
        "report_file": ".graphtraj/state/tasks/2-child/teams/1/rounds/1/engineer.md",
        "instruction": "Fix ticket 2 under state/tickets.", "launch_status": "task-already-live",
    }
    assert (paths["session"] / "session.jsonl").read_bytes() == before[".graphtraj/runner/sample/session.jsonl"]


def test_failed_migration_restores_retained_state(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    _ticket_project(tmp_path)
    (tmp_path / ".graphtraj/state/tickets/1-summary/broken.yml").write_text("key: [unclosed\n")
    before = _snapshot(tmp_path)

    assert _migrate(installed_commands, tmp_path).returncode != 0
    after = {key: value for key, value in _snapshot(tmp_path).items() if "/backups/" not in key}
    assert after == before


def test_legacy_definition_without_parent_facts_is_refused_without_changes(
    installed_commands: InstalledCommands, tmp_path: Path,
) -> None:
    _ticket_project(tmp_path)
    legacy = tmp_path / ".graphtraj/state/tickets/7-legacy"
    legacy.mkdir()
    (legacy / "ticket.md").write_text("# Ticket 7: Legacy\n\nTicket name: legacy\n\nSource: x\n\n"
                                      "Active: true\n\nReplaced by: none\n\nDependencies: none\n\nBody.\n")
    (legacy / "ticket.yml").write_text(yaml.safe_dump({
        "ticket_id": "7", "ticket_name": "legacy", "current_definition": "ticket.md", "active": True,
        "replaced_by": [], "dependencies": [], "status": "pending", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
    }))
    before = _snapshot(tmp_path)

    result = _migrate(installed_commands, tmp_path)
    assert result.returncode != 0
    assert "7: schema_version, parent_id, disposition, retirement_reason" in result.stderr
    assert _snapshot(tmp_path) == before
