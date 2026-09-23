"""One judged-abnormal Agent: its parent is notified and its descendants stop.

A parent, a child and a grandchild Session each run a real managed Worker with
a controlled native peer. Killing the child's Worker leaves the judgement the
Runner already makes - the recorded owner is gone without a terminal record -
and the public control entry must then deliver the abnormal facts into the
parent's own execution and stop the grandchild, while a normal wait or an
unconfirmed owner stops nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import time
from pathlib import Path

import yaml

from graphtraj.execution.runner_heartbeat import read_heartbeat
from test_managed_sessions import (
    ManagedProject,
    launch_document,
    managed_project,
    observe,
)


def _mapping(root: Path, alias: str) -> dict:
    """Read the identity one managed Worker retained in this isolated project."""
    return yaml.safe_load(
        (root / ".graphtraj/runner/sessions" / alias / "mapping.yml").read_text(
            encoding="utf-8"
        )
    )


def _sessions(root: Path) -> list[str]:
    """List the Session aliases this Runner records for the project."""
    return sorted(
        path.name for path in (root / ".graphtraj/runner/sessions").iterdir()
    )


def _notices(root: Path, alias: str) -> str:
    """Return one Session's retained parent notices, or an empty text."""
    path = root / ".graphtraj/runner/sessions" / alias / "parent-notices.jsonl"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _kill_worker(root: Path, alias: str) -> dict:
    """Kill one Session's Worker and drop the control path it left behind.

    The abnormality judgement never reads that path: the ownership lock the
    killed process released, the retained heartbeat and the absent terminal
    record decide it. Removing the leftover directory only keeps a dead
    control path from waiting out its timeout in every later probe.
    """
    mapping = _mapping(root, alias)
    os.kill(mapping["worker_pid"], signal.SIGKILL)
    control = mapping.get("control_directory")
    if isinstance(control, str):
        shutil.rmtree(control, ignore_errors=True)
    return mapping


def _await_parent_receipt(
    root: Path, session: str, text: str, timeout: float = 15.0
) -> str:
    """Wait until the parent's own native record holds the delivered notice."""
    rollout = root / "native" / ("rollout-" + session + ".jsonl")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = []
        if rollout.is_file():
            for line in rollout.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if any(
            isinstance(record.get("payload"), dict)
            and record["payload"].get("last_agent_message") == text
            for record in records
        ):
            return text
        time.sleep(0.05)
    raise AssertionError("The parent execution never received the notice.")


def test_abnormal_child_notifies_its_parent_and_stops_descendants(
    managed_project: ManagedProject,
) -> None:
    """The judged abnormality reaches the parent and stops the live grandchild."""
    root, _, call, _ = managed_project
    parent = call("launch", launch_document())["tasks"][0]["alias"]
    observe(call, parent, "running")
    child = call("child", [parent, "descendant@e1"])["alias"]
    observe(call, child, "running")
    grandchild = call("child", [child, "descendant@e2"])["alias"]
    observe(call, grandchild, "running")
    sessions = _sessions(root)
    before = {alias: _mapping(root, alias) for alias in (parent, child, grandchild)}
    directory = root / ".graphtraj/runner/sessions" / child

    # The existing judgement reads the killed owner as abnormal, while the
    # read-only query alone stops nothing and notifies nobody.
    killed = _kill_worker(root, child)
    observed = call("status", [child], timeout=60)["aliases"][0]
    assert observed["activity"] == "abnormal", observed
    assert "last_outcome" not in observed
    heartbeat = read_heartbeat(directory)
    assert heartbeat is not None
    assert heartbeat["worker_pid"] == killed["worker_pid"]
    assert not (directory / "stop.yml").exists()
    assert _notices(root, child) == ""

    document = call("cli", ["handle-abnormal", child], timeout=120)
    assert document["handled"] is True
    assert document["activity"] == "abnormal"
    assert document["session"] == killed["session"]
    assert document["execution_id"] == killed["execution_id"]
    assert document["heartbeat_at"] == heartbeat["updated_at"]
    # The abnormal owner left no terminal record, so its own stop stays
    # unconfirmed while the live grandchild is interrupted: no full stop is
    # claimed and no member is reissued or replaced.
    assert document["interrupt_status"] == "incomplete"
    assert {item["alias"]: item["interrupt_status"] for item in document["members"]} == {
        child: "unconfirmed",
        grandchild: "interrupted",
    }

    # The notice travelled into the parent's own live execution, and the
    # record retains the abnormal facts with each member's stop result.
    record = json.loads(_notices(root, child).splitlines()[-1])
    assert record["delivery"] == "received"
    assert record["parent"] == parent
    assert record["parent_session"] == before[parent]["session"]
    assert record["parent_execution_id"] == before[parent]["execution_id"]
    assert _await_parent_receipt(
        root, before[parent]["session"], record["notice"]
    ) == record["notice"]
    assert record["identity"] == {
        "alias":            child,
        "activity":         "abnormal",
        "session":          killed["session"],
        "execution_id":     killed["execution_id"],
        "heartbeat_at":     heartbeat["updated_at"],
        "interrupt_status": "incomplete",
        "members":          document["members"],
    }
    assert child in record["notice"] and grandchild in record["notice"]

    # The stopped subtree keeps its identity and can start nothing: the
    # prohibition the target published covers every recorded descendant.
    observe(call, grandchild, "idle", "interrupted")
    assert (directory / "stop.yml").exists()
    assert _mapping(root, child) == before[child]
    assert _mapping(root, grandchild) == before[grandchild]
    assert _mapping(root, parent)["execution_id"] == before[parent]["execution_id"]
    assert _sessions(root) == sessions
    denied = call("child", [grandchild, "descendant@e3"], returncode=1)
    assert denied["error"]["code"] == "subtree-stopped"
    assert not (
        root / ".graphtraj/runner/sessions/descendant@e3/session.yml"
    ).exists()
    denied = call("resume-worker", [grandchild, grandchild], returncode=1)
    assert denied["error"]["code"] == "subtree-stopped"


def test_normal_wait_and_unconfirmed_owner_are_not_handled(
    managed_project: ManagedProject,
) -> None:
    """A normal wait, a completed Session and lost contact stop nothing."""
    root, cause, call, _ = managed_project
    waiting = call("launch", launch_document("request:approval"))["tasks"][0]["alias"]
    active = observe(call, waiting, "running", waiting_for="runtime-request")
    directory = root / ".graphtraj/runner/sessions" / waiting
    notices = _notices(root, waiting)

    # A pending native request is a normal wait: the entry reports it, and
    # neither stops the execution nor sends another notice.
    document = call("cli", ["handle-abnormal", waiting], timeout=60)
    assert document["handled"] is False
    assert document["activity"] == "running"
    assert document["waiting_for"] == "runtime-request"
    assert document["execution_id"] == active["execution_id"]
    still = observe(call, waiting, "running", waiting_for="runtime-request")
    assert still["execution_id"] == active["execution_id"]
    assert not (directory / "stop.yml").exists()
    assert _notices(root, waiting) == notices

    # Lost contact cannot confirm death, so the entry reports what it read.
    owner = _mapping(root, waiting)
    os.kill(owner["worker_pid"], signal.SIGSTOP)
    try:
        lost = call("status", [waiting], timeout=60)["aliases"][0]
        assert lost["activity"] == "unreachable"
        document = call("cli", ["handle-abnormal", waiting], timeout=60)
        assert document["handled"] is False
        assert document["activity"] == "unreachable"
        assert document["heartbeat_at"] == lost["heartbeat_at"]
        assert not (directory / "stop.yml").exists()
        assert _notices(root, waiting) == notices
    finally:
        os.kill(owner["worker_pid"], signal.SIGCONT)
    observe(call, waiting, "running", waiting_for="runtime-request", timeout=15)

    # A normal completion is not an abnormality either.
    finished = call("launch", launch_document())["tasks"][0]["alias"]
    observe(call, finished, "running")
    call("send", [finished, "finish normally", [cause]])
    observe(call, finished, "idle", "completed")
    finished_directory = root / ".graphtraj/runner/sessions" / finished
    document = call("cli", ["handle-abnormal", finished], timeout=60)
    assert document["handled"] is False
    assert document["activity"] == "idle"
    assert document["last_outcome"] == "completed"
    assert not (finished_directory / "stop.yml").exists()
    assert _notices(root, finished) == ""
