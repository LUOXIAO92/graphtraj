"""Light Task index freshness and the layered current/full graph views."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from test_task_graph import _configure, _task


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """Return a configured project root and its state directory."""
    _configure(tmp_path)
    (tmp_path / "evidence.md").write_text("Main checked the result.\n", encoding="utf-8")
    return tmp_path, tmp_path / ".graphtraj/state"


def _graph(root: Path, **arguments: object) -> dict:
    """Read the graph through the public tool handler."""
    from graphtraj.interfaces.tools import read_current_graph

    return read_current_graph(arguments, cwd=root).document


def _status(state: Path, root: Path, task_id: str, status: str) -> None:
    from graphtraj.graph.task_graph import update_task_state

    update_task_state(state, root, {
        "task_id": task_id, "status": status, "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
    })


def _complete(state: Path, root: Path, task_id: str, cancelled: dict | None = None) -> None:
    from graphtraj.graph.task_graph import complete_task

    complete_task(state, root, {
        "task_id": task_id, "current_definition": "task.md", "reason": "Accepted.",
        "cancelled_scope": cancelled or {}, "caused_by_event_ids": [],
        "evidence_refs": ["evidence.md"],
    })


def _child(task_id: str, parent: str | None, dependencies: list[str] | None = None) -> dict:
    return {**_task(task_id, "task-" + task_id, dependencies=dependencies), "parent_id": parent}


def _opened(action) -> list[str]:
    """Run action and return the project files it opened."""
    opened: list[str] = []
    active = [True]
    sys.addaudithook(lambda event, args: opened.append(str(args[0]))
                     if active[0] and event == "open" and isinstance(args[0], (str, Path)) else None)
    try:
        action()
    finally:
        active[0] = False
    return opened


def test_hot_read_uses_the_index_and_native_writes_advance_it(tmp_path: Path) -> None:
    """Reads after the first build open neither definitions nor old Worldline shards."""
    from graphtraj.graph.task_graph import register_task, revise_tasks

    root, state = _project(tmp_path)
    register_task(state, root, _child("1", None))
    register_task(state, root, _child("2", "1"))
    first = _graph(root, view="full")
    assert [task["task_id"] for task in first["tasks"]] == ["1", "2"]
    assert "body" not in first["tasks"][0] and "worktree" not in first["tasks"][0]

    opened = _opened(lambda: _graph(root, view="full"))
    assert not [path for path in opened if path.endswith((".md", "task.yml"))]

    _status(state, root, "2", "blocked")
    revised = {**_child("2", "1"), "title": "Renamed", "current_definition": "task.md"}
    revise_tasks(state, root, {"tasks": [revised], "caused_by_event_ids": [],
                               "evidence_refs": ["evidence.md"], "product_preserving": True})
    graphs: list[dict] = []
    after = _opened(lambda: graphs.append(_graph(root, view="full")))
    node = graphs[0]["tasks"][1]
    assert (node["status"], node["title"], node["outcome"]) == ("blocked", "Renamed", "blocked")
    assert graphs[0]["revision"] == first["revision"] + 2
    assert not [path for path in after if path.endswith((".md", "task.yml"))]

    details = _graph(root, view="full", details=["2"])["details"]["2"]
    assert details["body"] == _child("2", "1")["body"]


def test_stale_damaged_or_missing_index_is_rebuilt_not_reported(tmp_path: Path) -> None:
    from graphtraj.graph.task_graph import register_task

    root, state = _project(tmp_path)
    register_task(state, root, _child("1", None))
    _graph(root, view="full")
    index = state / "task-index.json"
    behind = index.read_bytes()

    # An interrupted writer committed its event but not the index.
    _status(state, root, "1", "blocked")
    index.write_bytes(behind)
    assert _graph(root, view="full")["tasks"][0]["status"] == "blocked"

    for damaged in (b"{not json", b"[]", b""):
        index.write_bytes(damaged)
        assert _graph(root, view="full")["tasks"][0]["status"] == "blocked"
    index.unlink()
    assert _graph(root, view="full")["tasks"][0]["status"] == "blocked"


def test_concurrent_writes_and_reads_match_a_rebuild(tmp_path: Path) -> None:
    from graphtraj.graph.task_graph import register_task

    root, state = _project(tmp_path)
    for task_id in map(str, range(1, 9)):
        register_task(state, root, _child(task_id, None))
    _graph(root, view="full")
    errors: list[BaseException] = []

    def work(task_id: str) -> None:
        try:
            _status(state, root, task_id, "ready")
            _graph(root, view="full")
            _status(state, root, task_id, "blocked")
        except BaseException as error:  # surfaced below
            errors.append(error)

    threads = [threading.Thread(target=work, args=(str(key),)) for key in range(1, 9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    incremental = _graph(root, view="full")
    (state / "task-index.json").unlink()
    assert _graph(root, view="full") == incremental
    assert {task["status"] for task in incremental["tasks"]} == {"blocked"}


def test_current_view_expands_scope_and_folds_history(tmp_path: Path) -> None:
    """History folds into summaries while inputs, replacements and roots stay visible."""
    from graphtraj.graph.task_graph import register_task, revise_tasks

    root, state = _project(tmp_path)
    for definition in (
        _child("1", None), _child("2", "1"), _child("3", "1"),      # completed summary
        _child("4", None), _child("5", "4"), _child("6", "4", ["2"]),  # open summary
        _child("7", "4"), _child("8", "4"), _child("9", "4"),
        _child("10", None),                                           # unrelated open root
    ):
        register_task(state, root, definition)
    for task_id in ("2", "3", "1", "5"):
        _complete(state, root, task_id)
    _status(state, root, "7", "blocked")
    cancelled = {**_child("8", "4"), "disposition": "cancelled",
                 "retirement_reason": "Withdrawn.", "current_definition": "task.md"}
    replacement = {**_child("11", "4"), "current_definition": None}
    superseded = {**_child("9", "4"), "disposition": "superseded", "replaced_by": ["11"],
                  "retirement_reason": "Merged.", "current_definition": "task.md"}
    revise_tasks(state, root, {"tasks": [cancelled, superseded, replacement],
                               "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
                               "product_preserving": True})

    scoped = _graph(root, task_id="4")
    nodes = {task["task_id"]: task for task in scoped["tasks"]}
    # Open work, its cross-summary input and every top-level Task remain.
    assert set(nodes) == {"1", "2", "4", "6", "7", "10", "11"}
    assert nodes["7"]["outcome"] == "blocked" and nodes["4"]["outcome"] == "pending"
    assert nodes["4"]["folded"] == {"completed": 1, "cancelled": 1, "superseded": 1}
    assert nodes["1"]["folded"] == {"completed": 1}
    edges = {(edge["source"], edge["target"], edge["kind"]) for edge in scoped["edges"]}
    assert ("2", "6", "dependency") in edges and ("4", "11", "replacement") in edges
    assert ("2", "1", "acceptance") in edges and ("3", "1", "acceptance") not in edges

    project = {task["task_id"] for task in _graph(root)["tasks"]}
    assert {"6", "7", "10", "11"} <= project and "3" not in project
    full = _graph(root, view="full")
    assert {task["task_id"] for task in full["tasks"]} == set(map(str, range(1, 12)))
    outcomes = {task["task_id"]: task["outcome"] for task in full["tasks"]}
    assert (outcomes["8"], outcomes["9"], outcomes["3"]) == ("cancelled", "superseded", "completed")
    with pytest.raises(ValueError):
        _graph(root, task_id="99")
