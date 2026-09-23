"""One execution owns a Session until its retained terminal record confirms the end."""

import os
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from test_managed_sessions import launch_document, managed_project, observe


def _mapping(root: Path, alias: str) -> dict:
    """Read the Runner's own record for one Agent Alias."""
    return yaml.safe_load(
        (
            root / ".graphtraj" / "runner" / "sessions" / alias / "mapping.yml"
        ).read_text(encoding="utf-8")
    )


def _owner_locks(root: Path, alias: str) -> list[str]:
    """List the ownership locks left in one Session directory."""
    directory = root / ".graphtraj" / "runner" / "sessions" / alias
    return sorted(path.name for path in directory.glob("owner-*.lock"))


def test_steering_and_refusal_keep_one_execution_for_the_session(
    managed_project,
) -> None:
    """A live owner receives input, refuses a second execution, and continues after its end."""
    root, cause, call, _ = managed_project
    launched = call("launch", launch_document())["tasks"][0]
    alias = launched["alias"]
    # The create reports the execution it started, so a successor can locate it.
    assert launched["execution_id"]
    before = observe(call, alias, "running")
    assert before["session"] == launched["session"]
    assert before["execution_id"] == launched["execution_id"]

    # Input reaches the live execution rather than starting a second one. The
    # requested native decision leaves that execution normally waiting.
    assert call("send", [alias, "unhandled request", [cause]]) == {
        "alias": alias,
        "session": before["session"],
        "execution_id": before["execution_id"],
        "send_status": "sent",
    }
    waiting = observe(call, alias, "running", waiting_for="runtime-request")
    assert waiting["execution_id"] == before["execution_id"]
    owner = _mapping(root, alias)
    assert (owner["session"], owner["execution_id"]) == (
        before["session"],
        before["execution_id"],
    )
    assert _owner_locks(root, alias) == [
        "owner-{0}.lock".format(owner["worker_pid"])
    ]

    # An owner that still holds the Session without answering cannot be treated
    # as ended: the continuation is refused and the recorded execution stays.
    os.kill(owner["worker_pid"], signal.SIGSTOP)
    try:
        denied = call(
            "send", [alias, "start another execution", [cause]],
            timeout=30, returncode=1,
        )
    finally:
        os.kill(owner["worker_pid"], signal.SIGCONT)
    assert denied["error"]["code"] == "operation-failed"
    recorded = _mapping(root, alias)
    assert recorded["worker_pid"] == owner["worker_pid"]
    assert recorded["execution_id"] == owner["execution_id"]
    assert _owner_locks(root, alias) == [
        "owner-{0}.lock".format(owner["worker_pid"])
    ]
    running = observe(call, alias, "running", waiting_for="runtime-request")
    assert running["execution_id"] == owner["execution_id"]

    assert call("interrupt", [alias]) == {
        "alias": alias, "interrupt_status": "interrupted",
    }
    ended = observe(call, alias, "idle", "interrupted")
    assert ended["execution_id"] == owner["execution_id"]

    # The retained terminal record confirms the end, so a continuation is legal
    # and keeps the Agent Entity: same alias, native Session and recorded parent.
    continued = call("send", [alias, "finish the continuation", [cause]])
    resumed = observe(call, alias, "running")
    assert resumed["session"] == launched["session"] == continued["session"]
    assert resumed["execution_id"] == continued["execution_id"]
    assert resumed["execution_id"] != ended["execution_id"]
    after = _mapping(root, alias)
    assert after["alias"] == alias
    assert after["session"] == launched["session"]
    assert after["parent"] == owner["parent"]
    # The continuation keeps the Agent Entity's immutable binding unchanged.
    assert (after["role"], after["ticket_id"], after["team_generation"]) == (
        owner["role"],
        owner["ticket_id"],
        owner["team_generation"],
    )
    assert after["worker_pid"] != owner["worker_pid"]
    assert sorted(_owner_locks(root, alias)) == sorted([
        "owner-{0}.lock".format(owner["worker_pid"]),
        "owner-{0}.lock".format(after["worker_pid"]),
    ])
    assert call("interrupt", [alias]) == {
        "alias": alias, "interrupt_status": "interrupted",
    }
    observe(call, alias, "idle", "interrupted")


def test_the_shared_boundary_answers_for_each_ownership_state(
    managed_project,
) -> None:
    """A create claims only a free directory, and a continue only an ended one."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import (
        owning_execution,
        read_alias_mapping,
        session_occupied,
    )

    root, cause, call, _ = managed_project
    runner = root / ".graphtraj" / "runner"
    launched = call("launch", launch_document())["tasks"][0]
    alias = launched["alias"]
    observe(call, alias, "running")
    session_directory = runner / "sessions" / alias
    mapping, _ = read_alias_mapping(runner, alias)

    # A create may not claim a directory that already records a Session, and the
    # refusal names that record instead of leaving a raw directory error.
    recorded = owning_execution(alias, session_directory, None)
    assert recorded == {"activity": "recorded"}
    assert session_occupied(alias, recorded).as_document()["code"] == "operation-failed"

    # A running execution owns the directory.
    running = owning_execution(alias, session_directory, mapping)
    assert running["activity"] == "running"
    assert running["execution_id"] == mapping["execution_id"]

    # So does an owner that holds its ownership lock without answering.
    os.kill(mapping["worker_pid"], signal.SIGSTOP)
    try:
        unreachable = owning_execution(alias, session_directory, mapping)
    finally:
        os.kill(mapping["worker_pid"], signal.SIGCONT)
    assert unreachable["activity"] == "unreachable"

    # The retained terminal record confirms the end and frees the directory.
    call("interrupt", [alias])
    observe(call, alias, "idle", "interrupted")
    assert owning_execution(
        alias, session_directory, read_alias_mapping(runner, alias)[0]
    ) is None
    assert session_occupied(alias, None).as_document()["code"] == "operation-failed"


def _live_owners(directory: Path) -> list[int]:
    """Return the recorded owners that still hold one Session directory's lock."""
    from graphtraj.execution.runner_heartbeat import ownership_is_held

    held = []
    for lock in sorted(directory.glob("owner-*.lock")):
        pid = int(lock.name[len("owner-"):-len(".lock")])
        if ownership_is_held(directory, pid):
            held.append(pid)
    return held


def test_concurrent_create_and_continue_keep_one_owner_per_directory(
    managed_project,
) -> None:
    """A create and a continue at once cannot leave two live owners in one directory."""
    root, cause, call, _ = managed_project
    launched = call("launch", launch_document())["tasks"][0]
    alias = launched["alias"]
    before = observe(call, alias, "running")

    with ThreadPoolExecutor(2) as callers:
        created = callers.submit(call, "launch", launch_document("second"))
        continued = callers.submit(call, "send", [alias, "unhandled request", [cause]])
        create_document = created.result()
        continue_document = continued.result()

    # The continue reached the execution the Session already owned.
    assert continue_document == {
        "alias": alias,
        "session": before["session"],
        "execution_id": before["execution_id"],
        "send_status": "sent",
    }
    assert _mapping(root, alias)["execution_id"] == before["execution_id"]
    assert _live_owners(root / ".graphtraj" / "runner" / "sessions" / alias) == [
        _mapping(root, alias)["worker_pid"]
    ]

    # A concurrent create owns its own directory, or is refused while another
    # execution already owns the directory it would claim.
    second = create_document["tasks"][0]
    if "error" in second:
        assert second["error"]["code"] == "operation-failed"
    else:
        assert second["launch_status"] == "launched"
        assert second["alias"] != alias
        assert second["execution_id"]
        observe(call, second["alias"], "running")

    session_root = root / ".graphtraj" / "runner" / "sessions"
    for directory in sorted(path for path in session_root.iterdir() if path.is_dir()):
        assert len(_live_owners(directory)) <= 1, directory.name
    running = observe(call, alias, "running", waiting_for="runtime-request")
    assert running["execution_id"] == before["execution_id"]
    for name in (alias, second.get("alias")):
        if not name:
            continue
        call("interrupt", [name])
        observe(call, name, "idle", "interrupted")
