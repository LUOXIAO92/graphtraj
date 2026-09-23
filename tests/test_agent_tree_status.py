"""One query returns the Agent status tree the caller may see."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from graphtraj.execution import runner_status
from runner_fixtures import configure_harness, engineer_probe
from test_managed_sessions import (
    ManagedProject,
    launch_document,
    managed_project,
    observe,
)


def _records(root: Path) -> set[str]:
    """List the records the Runner retained, ignoring live control directories."""
    sessions = root / ".graphtraj" / "runner" / "sessions"
    return {
        path.relative_to(sessions).as_posix()
        for path in sessions.rglob("*")
        if path.is_file() and "control-" not in path.relative_to(sessions).parts
    }


def _budget(root: Path) -> bytes | None:
    """Read the Ticket budget record, if this project has one."""
    budget = next(root.glob(".graphtraj/state/tickets/*/execution-budget.yml"), None)
    return budget.read_bytes() if budget is not None else None


def _last_command(root: Path) -> dict:
    """Read the raw result the fixture recorded for the last public command."""
    lines = (root / "public-operations.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def _aliases(document: dict) -> dict:
    """Index one tree document by alias."""
    return {node["alias"]: node for node in document["agents"]}


def _reparent(root: Path, alias: str, parent: str) -> None:
    """Record one direct parent for an existing Session, as a dispatch would."""
    mapping_file = root / ".graphtraj" / "runner" / "sessions" / alias / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    mapping["parent"] = parent
    mapping_file.write_text(yaml.safe_dump(mapping), encoding="utf-8")


def test_one_query_reports_every_member_and_a_lost_one_blocks_nothing(
    managed_project: ManagedProject,
) -> None:
    """A single alias-free query reports running, waiting, completed and lost."""
    from graphtraj.execution.runner_heartbeat import read_heartbeat
    from graphtraj.execution.runner_status import read_alias_mapping

    root, _, call, _ = managed_project
    waiting = call("launch", launch_document("request:approval", "waiting-probe"))["tasks"][0]
    waiting_status = observe(
        call, waiting["alias"], "running", waiting_for="runtime-request"
    )
    finished = call("launch", launch_document("request:approval", "finished-probe"))["tasks"][0]
    request, = call("requests", [finished["alias"]])["requests"]
    call("reply", [finished["alias"], request, {"decision": "decline"}])
    observe(call, finished["alias"], "idle", "completed")
    # The owner publishes its terminal record on its own loop, so wait for it
    # before this query is the only thing that could still add a record.
    wait_for_file(
        root / ".graphtraj" / "runner" / "sessions" / finished["alias"] / "execution.yml"
    )
    lost = call("launch", launch_document("hold", "lost-probe"))["tasks"][0]
    observe(call, lost["alias"], "running")
    lost_mapping, lost_directory = read_alias_mapping(
        root / ".graphtraj/runner", lost["alias"]
    )

    os.kill(lost_mapping["worker_pid"], signal.SIGSTOP)
    try:
        before = _records(root)
        budget = _budget(root)
        heartbeat = read_heartbeat(lost_directory)["updated_at"]
        completed = call("cli", ["status"], timeout=30)
        print(_last_command(root)["stdout"])
        after = _records(root)
        frozen = read_heartbeat(lost_directory)["updated_at"]
    finally:
        os.kill(lost_mapping["worker_pid"], signal.SIGCONT)

    tree = _aliases(completed)
    assert set(tree) == {waiting["alias"], finished["alias"], lost["alias"]}, tree
    assert all(node["parent"] is None for node in tree.values()), tree
    assert (tree[waiting["alias"]]["activity"], tree[waiting["alias"]]["waiting_for"]) == (
        "running", "runtime-request",
    ), tree
    assert tree[waiting["alias"]]["session"] == waiting_status["session"], tree
    assert (tree[finished["alias"]]["activity"], tree[finished["alias"]]["last_outcome"]) == (
        "idle", "completed",
    ), tree
    assert tree[lost["alias"]]["activity"] == "unreachable", tree
    assert not any("error" in node for node in tree.values()), tree

    # One query created no Session or execution, wrote no budget record and did
    # not wake the member it could not reach: its heartbeat stayed frozen while
    # the query ran, and it answered again on the same execution afterwards.
    assert after == before, before ^ after
    assert _budget(root) == budget
    assert frozen == heartbeat, heartbeat
    recovered = observe(call, lost["alias"], "running", timeout=15)
    assert recovered["session"] == tree[lost["alias"]]["session"], recovered


def test_the_visible_tree_and_its_detail_follow_the_recorded_relation(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded parent decides visibility and how much detail a node keeps."""
    root, _, call, _ = managed_project
    outer = call("launch", launch_document("hold", "outer-probe"))["tasks"][0]
    middle = call("launch", launch_document("request:approval", "middle-probe"))["tasks"][0]
    inner = call("launch", launch_document("request:approval", "inner-probe"))["tasks"][0]
    branch = call("launch", launch_document("request:approval", "branch-probe"))["tasks"][0]
    for launched in (outer, middle, inner, branch):
        observe(call, launched["alias"], "running")
    request, = call("requests", [inner["alias"]])["requests"]
    call("reply", [inner["alias"], request, {"decision": "decline"}])
    observe(call, inner["alias"], "idle", "completed")

    # The recorded relation is the whole tree: outer owns middle, middle owns
    # inner, and branch stays a separate top-level Session.
    _reparent(root, middle["alias"], outer["alias"])
    _reparent(root, inner["alias"], middle["alias"])
    broken = root / ".graphtraj" / "runner" / "sessions" / "t134-broken@e1"
    broken.mkdir()
    (broken / "mapping.yml").write_text("{}\n", encoding="utf-8")

    completed = call("cli", ["status"], timeout=30, returncode=1)
    print(_last_command(root)["stdout"])
    tree = _aliases(completed)
    assert tree[outer["alias"]]["children"] == [middle["alias"]], tree
    assert tree[middle["alias"]]["parent"] == outer["alias"], tree
    assert tree[middle["alias"]]["children"] == [inner["alias"]], tree
    assert tree[branch["alias"]]["parent"] is None, tree
    # The unreadable record keeps its own entry and every other node returns.
    assert tree["t134-broken@e1"]["error"]["code"] == "operation-failed", tree
    assert tree["t134-broken@e1"]["parent"] is None, tree
    assert tree[outer["alias"]]["session"] and tree[branch["alias"]]["session"], tree
    assert set(tree[middle["alias"]]) <= {
        "alias", "parent", "children", "activity", "last_outcome"
    }, tree
    assert tree[middle["alias"]]["activity"] == "running", tree
    assert (tree[inner["alias"]]["activity"], tree[inner["alias"]]["last_outcome"]) == (
        "idle", "completed",
    ), tree

    # The same query from inside the owning Session sees only that subtree,
    # with full detail for itself and its recorded direct child.
    monkeypatch.setattr(
        runner_status, "caller_alias", lambda directory: outer["alias"]
    )
    owned = _aliases(runner_status.status_tree(root).document)
    assert set(owned) == {outer["alias"], middle["alias"], inner["alias"]}, owned
    assert owned[outer["alias"]]["session"] and owned[middle["alias"]]["session"], owned
    assert set(owned[inner["alias"]]) <= {
        "alias", "parent", "children", "activity", "last_outcome"
    }, owned
    assert "t134-broken@e1" not in owned, owned


def test_a_real_team_tree_is_reachable_in_one_query(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A Team the Runner recorded itself is read from one alias-free query."""
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    with engineer_probe(
        installed_commands, harness, fake_codex, environment
    ) as (engineer, _, probe_environment):
        completed = run_process(
            [str(installed_commands.runner), "status"],
            cwd=harness,
            env=probe_environment,
            timeout=60,
        )
        print(completed.stdout)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        tree = _aliases(yaml.safe_load(completed.stdout))
        leaders = [node for node in tree.values() if node["parent"] is None]
        assert len(leaders) == 1, tree
        leader = leaders[0]
        assert leader["session"] and leader["execution_id"], tree
        assert tree[engineer]["parent"] == leader["alias"], tree
        assert engineer in leader["children"], tree
        # A recorded descendant keeps the coarse activity for Main.
        assert set(tree[engineer]) <= {
            "alias", "parent", "children", "activity", "last_outcome"
        }, tree
        assert tree[engineer]["activity"] in {"running", "idle"}, tree
