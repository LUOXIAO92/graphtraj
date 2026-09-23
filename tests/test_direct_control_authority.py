"""Authorization of the public control entries by recorded direct ownership."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from graphtraj.execution import runner_status
from graphtraj.execution.runner_models import RunnerError
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket


PROBE_FILE = Path(__file__).with_name("direct_control_probes.py")
PROBE_INSTRUCTION = "Run the direct control probes now."


def _controlled_codex(fake_codex: FakeCodex) -> None:
    """Hold one role on request and run the control probes on probe input.

    The hold is selected by the Session's own role, so a test can keep one
    descendant running without stopping the rest of its Team. A replaced
    Engineer delivers a distinct commit so a later Session can repeat it. A
    probe set for a member is forwarded by the member's own direct parent: no
    other caller may reach it, so the parent is the only path that exists.
    """
    script = fake_codex.executable.read_text(encoding="utf-8")
    marker = "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')"
    assert marker in script
    delivered = (
        "delivered.write_text('complete team round' + ('' if ordinal == '1' "
        "else ' ' + ordinal) + '\\n')"
    )
    assert delivered in script
    script = script.replace(
        delivered,
        "delivered.write_text('complete team round ' + "
        "os.environ.get('GRAPHTRAJ_PARENT_ALIAS', '') + '\\n')",
        1,
    )
    injection = (
        "role_hold = os.environ.get('HOLD_FILE_' + os.environ.get('GRAPHTRAJ_ROLE', '').replace('-', '_').upper())\n"
        "if role_hold is not None:\n"
        "    while not Path(role_hold).exists():\n"
        "        time.sleep(0.01)\n"
        "if (os.environ.get('DIRECT_CONTROL_FORWARD_TO') and runtime_prompt"
        " and 'Run the direct control probes' in runtime_prompt):\n"
        "    child = {key: value for key, value in os.environ.items()"
        " if key != 'DIRECT_CONTROL_FORWARD_TO'}\n"
        "    forwarded = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'send',"
        " os.environ['DIRECT_CONTROL_FORWARD_TO'], '--instruction', 'Run the direct control probes now.',"
        " '--caused-by-event-id', os.environ['DIRECT_CONTROL_CAUSE']],"
        " cwd=os.environ['GRAPHTRAJ_HARNESS_ROOT'], env=child, capture_output=True, text=True)\n"
        "    with open(os.environ['DIRECT_CONTROL_PROBE_LOG'], 'a', encoding='utf-8') as stream:\n"
        "        stream.write(json.dumps({'probe': 'forward-send', 'returncode': forwarded.returncode,\n"
        "            'stdout': forwarded.stdout,\n"
        "            'stderr': forwarded.stderr}) + '\\n')\n"
        "    raise SystemExit(0)\n"
        "if os.environ.get('DIRECT_CONTROL_PROBE_FILE') and runtime_prompt and 'Run the direct control probes' in runtime_prompt:\n"
        "    import runpy\n"
        "    runpy.run_path(os.environ['DIRECT_CONTROL_PROBE_FILE'], run_name='direct_control_probes')\n"
        "    raise SystemExit(0)\n"
    )
    fake_codex.executable.write_text(script.replace(marker, injection + marker, 1))


def _mapping(root: Path, alias: str) -> dict:
    """Read the Runner's own record for one Session alias."""
    return yaml.safe_load(
        (
            root / ".graphtraj" / "runner" / "sessions" / alias / "mapping.yml"
        ).read_text(encoding="utf-8")
    )


def _role_alias(root: Path, role: str, timeout: float = 60.0) -> str:
    """Wait for one launched Session of the supplied role."""
    sessions = root / ".graphtraj" / "runner" / "sessions"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in sorted(sessions.glob("*/mapping.yml")):
            mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
            if mapping.get("role") == role:
                return mapping["alias"]
        time.sleep(0.02)
    raise AssertionError("No {0} Session was launched".format(role))


def _cause(root: Path) -> str:
    """Read the latest retained Project Worldline event identifier."""
    events = [
        json.loads(line)
        for shard in sorted((root / ".graphtraj" / "state" / "worldline").glob("*.jsonl"))
        for line in shard.read_text(encoding="utf-8").splitlines()
    ]
    return events[-1]["event_id"]


def _status(commands: InstalledCommands, root: Path, environment: dict, alias: str) -> dict:
    """Read one alias status document through the installed command."""
    completed = run_process(
        [str(commands.runner), "status", alias], cwd=root, env=environment, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return yaml.safe_load(completed.stdout)["aliases"][0]


def _wait_running(
    commands: InstalledCommands, root: Path, environment: dict, aliases: tuple[str, ...]
) -> None:
    """Wait until each supplied Session reports a running execution."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if all(
            _status(commands, root, environment, alias)["activity"] == "running"
            for alias in aliases
        ):
            return
        time.sleep(0.05)
    raise AssertionError("A probe target never reached a running execution")


def _temporary_specialist(
    commands: InstalledCommands, root: Path, environment: dict
) -> str:
    """Dispatch one Main-owned temporary Session outside the Team's branch."""
    batch = root / "authority-specialist.yml"
    batch.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "ticket_id": "76",
                        "ticket_name": "session-alias-control",
                        "role": {
                            "investigation-specialist": {
                                "runtime": "codex",
                                "model": "gpt-5.6-luna",
                            }
                        },
                        "instruction": "Investigate before delivery.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    completed = run_process(
        [str(commands.runner), "--batch-input", str(batch)],
        cwd=root, env=environment, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return yaml.safe_load(completed.stdout)["tasks"][0]["alias"]


def _probe(
    commands: InstalledCommands,
    root: Path,
    environment: dict,
    alias: str,
    *,
    log: Path,
    name: str,
    targets: dict,
    batch: Path,
    forward_to: str | None = None,
) -> dict:
    """Run one probe set and return its recorded results.

    The instruction reaches ``alias`` directly. When ``forward_to`` names a
    member, the addressed Session is that member's recorded direct parent and
    forwards the same instruction, so the member's own process tree runs the
    probes.
    """
    log.unlink(missing_ok=True)
    completed = run_process(
        [
            str(commands.runner), "send", alias,
            "--instruction", PROBE_INSTRUCTION,
            "--caused-by-event-id", _cause(root),
        ],
        cwd=root,
        env={
            **environment,
            "DIRECT_CONTROL_PROBE_SET": name,
            "DIRECT_CONTROL_PROBE_LOG": str(log),
            "DIRECT_CONTROL_TARGETS": json.dumps(targets),
            "DIRECT_CONTROL_CAUSE": _cause(root),
            "DIRECT_CONTROL_BATCH": str(batch),
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_APPEND_LOG": "1",
            **(
                {"DIRECT_CONTROL_FORWARD_TO": forward_to}
                if forward_to is not None else {}
            ),
        },
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    deadline = time.monotonic() + 90
    entries: list[dict] = []
    while time.monotonic() < deadline:
        entries = _records(log)
        if any(entry["probe"] == "probes-complete" for entry in entries):
            break
        time.sleep(0.02)
    else:
        raise AssertionError("The Session did not finish its control probes")
    return {entry["probe"]: entry for entry in entries if entry["probe"] != "probes-complete"}


def _records(log: Path) -> list[dict]:
    """Read the complete probe records; a partial final line is ignored."""
    if not log.is_file():
        return []
    records = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _assert_denied(entry: dict) -> None:
    """One refused probe names the established authority error."""
    assert entry["returncode"] == 1, entry
    expected = {"authority-denied", "native-approval-unavailable"} if entry["probe"].startswith("replace-") else {"authority-denied"}
    assert entry["document"]["error"]["code"] in expected, entry


def _assert_denied_after_authority(entry: dict) -> None:
    """A probe the authority layer admitted is refused by the request itself."""
    assert entry["returncode"] == 1, entry
    assert entry["document"]["error"]["code"] != "authority-denied", entry


def _assert_summary(entry: dict, alias: str, activity: str) -> None:
    """A cross-level observation returns only the coarse activity."""
    document = entry["document"]["aliases"][0]
    assert document["alias"] == alias, entry
    assert document["activity"] == activity, entry
    assert set(document) <= {"alias", "activity", "last_outcome"}, entry


def _assert_full(entry: dict, alias: str) -> None:
    """The caller's own or direct-child Session keeps its full status."""
    document = entry["document"]["aliases"][0]
    assert document["alias"] == alias, entry
    assert document["session"] and document["execution_id"], entry


def _assert_status_document(document: dict, alias: str, *, full: bool) -> None:
    """One status document read from Main keeps or drops the private identity."""
    assert document["alias"] == alias, document
    if full:
        assert document["session"] and document["execution_id"], document
    else:
        assert set(document) <= {"alias", "activity", "last_outcome"}, document


def _record_direct_session(
    runner_directory: Path, alias: str, role: str, parent: str | None
) -> None:
    """Record one Session and its direct parent as the Runner would."""
    directory = runner_directory / "sessions" / alias
    directory.mkdir(parents=True)
    (directory / "mapping.yml").write_text(
        yaml.safe_dump(
            {
                "alias": alias, "runtime": "codex", "session": "native",
                "execution_id": "turn", "ticket_id": "132", "team_generation": 1,
                "role": role, "parent": parent, "retained_batch_file": "batch.yml",
                "worktree_path": str(directory / "worktree"),
                "trace_file": str(directory / "events.jsonl"),
                "worker_pid": 4242, "runtime_pid": 4243,
            }
        ),
        encoding="utf-8",
    )


def _ask_to_replace(
    runner_directory: Path, caller: str | None, target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ask one replacement entry to authorize the target for the caller."""
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: caller)
    mapping, _ = runner_status.read_alias_mapping(runner_directory, target)
    runner_status.require_replacement_authority(runner_directory, target, mapping)


def _replacement_command(target: str) -> list:
    """One exact replace command line, as the Runtime would have approved it."""
    return [
        "agent-runner", "replace", target,
        "--actor", "user", "--caused-by-event-id", "evt",
    ]


def test_control_entries_follow_recorded_direct_ownership(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Each public control entry allows the direct owner and refuses the rest."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _controlled_codex(fake_codex)
    _register_ready_ticket(installed_commands, root)
    release  = tmp_path / "release-reviews"
    hold     = tmp_path / "hold-specialist"
    batch    = root / "authority-batch.yml"
    batch.write_text(
        yaml.safe_dump(
            {"tasks": [{"ticket_id": "76", "ticket_name": "session-alias-control",
                        "role": "team-leader"}]}
        ),
        encoding="utf-8",
    )
    launch_environment = {
        **environment,
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "FAKE_CODEX_REVIEW_RELEASE_FILE": str(release),
        "HOLD_FILE_INVESTIGATION_SPECIALIST": str(hold),
        "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        "DIRECT_CONTROL_PROBE_FILE": str(PROBE_FILE),
    }
    with (tmp_path / "authority-team.log").open("w", encoding="utf-8") as output:
        launched = subprocess.Popen(
            [str(installed_commands.runner), "--batch-input", str(batch)],
            cwd=root, env=launch_environment, text=True,
            stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            leader    = _role_alias(root, "team-leader")
            engineer  = _role_alias(root, "engineer")
            standards = _role_alias(root, "standards-reviewer")
            spec      = _role_alias(root, "spec-reviewer")
            other     = _temporary_specialist(installed_commands, root, launch_environment)
            _wait_running(installed_commands, root, environment, (standards, spec, other))

            peers = _probe(
                installed_commands, root, launch_environment, leader,
                log=tmp_path / "engineer-probes.jsonl", name="peers", batch=batch,
                forward_to=engineer,
                targets={
                    "leader": leader, "reviewer": standards, "other": other,
                    "leader_registration": str(
                        root / ".graphtraj" / "runner" / "sessions" / leader
                        / "child-registration.yml"
                    ),
                },
            )
            assert peers.pop("forward-send")["returncode"] == 0, peers
            children = _probe(
                installed_commands, root, launch_environment, leader,
                log=tmp_path / "leader-probes.jsonl", name="children", batch=batch,
                targets={
                    "engineer": engineer, "reviewer": standards, "other": other,
                    "foreign_registration": str(
                        root / ".graphtraj" / "runner" / "sessions" / spec
                        / "child-registration.yml"
                    ),
                },
            )
        finally:
            release.touch()
            hold.touch()
            try:
                launched.wait(timeout=60)
            except subprocess.TimeoutExpired:
                launched.kill()
                launched.wait(timeout=10)

    # An Engineer controls neither its sibling, its parent, nor another branch,
    # whether it carries the projected values, carries none of them, or carries
    # a consistent forgery of its Leader's identity.
    _assert_full(peers["status-self"], engineer)
    assert peers["status-self"]["document"]["aliases"][0]["execution_id"] == _mapping(root, engineer)["execution_id"]
    _assert_summary(peers["status-parent-leader"], leader, "idle")
    _assert_summary(peers["status-sibling-reviewer"], standards, "running")
    _assert_summary(peers["status-other-branch"], other, "running")
    _assert_summary(peers["status-other-branch-cleared-env"], other, "running")
    for name in (
        "send-sibling-reviewer", "interrupt-sibling-reviewer",
        "requests-sibling-reviewer", "replace-sibling-reviewer",
        "replace-parent-leader", "replace-parent-leader-user-actor", "register-child-batch",
        "reply-sibling-reviewer", "reply-parent-leader",
        "requests-parent-leader-cleared-env", "send-parent-leader-cleared-env",
        "replace-parent-leader-cleared-env", "interrupt-parent-leader-cleared-env",
        "register-child-batch-cleared-env", "send-sibling-reviewer-forged-env",
        "replace-sibling-reviewer-forged-env",
    ):
        _assert_denied(peers[name])

    # A Team Leader controls its direct children only, and its own subtree for
    # interruption, while approval and replacement stay with the direct owner.
    _assert_full(children["status-self"], leader)
    assert children["status-self"]["document"]["aliases"][0]["execution_id"] == _mapping(root, leader)["execution_id"]
    _assert_full(children["status-child-engineer"], engineer)
    _assert_full(children["status-child-reviewer"], standards)
    _assert_summary(children["status-other-branch"], other, "running")
    assert children["requests-child-reviewer"]["document"]["alias"] == standards
    assert children["requests-child-reviewer"]["document"]["requests"] == []
    # The approval entry admits the direct parent and then refuses the
    # fabricated request it was given, so the caller never reaches the reply.
    _assert_denied_after_authority(children["reply-child-reviewer"])
    # The Leader's own child-registration entry is admitted, so only the Batch
    # rules refuse the Leader-shaped Batch it was handed.
    _assert_denied_after_authority(children["register-own-registration"])
    assert children["send-child-reviewer"]["document"] == {
        "alias": standards, "send_status": "sent",
    }
    for name in (
        "send-other-branch", "requests-other-branch", "interrupt-other-branch",
        "replace-other-branch", "register-foreign-session", "reply-other-branch",
        "send-other-branch-cleared-env",
    ):
        _assert_denied(children[name])
    _assert_summary(children["status-other-branch-cleared-env"], other, "running")
    replacement = children["replace-child-engineer"]["document"]
    assert children["replace-child-engineer"]["returncode"] == 0, replacement
    assert replacement["alias"] == engineer
    assert replacement["replacement_alias"] != engineer
    assert replacement["team_ordinal"] == 1
    assert children["interrupt-child-reviewer"]["document"] == {
        "alias": standards, "interrupt_status": "interrupted",
        "members": [{"alias": standards, "interrupt_status": "interrupted"}],
    }

    # Main observes the Team Leader it dispatched itself in full, and a Session
    # beyond that direct relation as a summary only.
    ticket_directory = root / ".graphtraj" / "state" / "tickets" / "76-session-alias-control"
    team_file = ticket_directory / "teams" / "1" / "team.yml"
    seat = yaml.safe_load(team_file.read_text(encoding="utf-8"))["members"]["engineer"]["session_ref"]
    _assert_status_document(
        _status(installed_commands, root, environment, leader), leader, full=True,
    )
    _assert_status_document(
        _status(installed_commands, root, environment, standards), standards, full=False,
    )
    _assert_status_document(
        _status(installed_commands, root, environment, seat), seat, full=False,
    )

    # An ordinary control and a replacement of a member both lie outside Main's
    # direct relation, and the --actor self-report changes neither verdict.
    request_file = tmp_path / "main-reply.yml"
    request_file.write_text(
        yaml.safe_dump(
            {"alias": standards, "session": "none", "execution_id": "none", "request_token": "none"}
        ),
        encoding="utf-8",
    )
    control_environment = {**environment, "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round"}
    for arguments in (
        ["send", standards, "--instruction", "Report your current activity.",
         "--caused-by-event-id", _cause(root)],
        ["requests", standards],
        ["reply", standards, "--request-file", str(request_file),
         "--response", '{"decision": "accept"}'],
        ["replace", seat, "--actor", "main", "--caused-by-event-id", _cause(root)],
        ["replace", seat, "--actor", "user", "--caused-by-event-id", _cause(root)],
    ):
        refused = run_process(
            [str(installed_commands.runner), *arguments],
            cwd=root, env=control_environment, timeout=30,
        )
        assert refused.returncode == 1, refused.stdout + refused.stderr
        expected = {"authority-denied", "native-approval-unavailable"} if arguments[0] == "replace" else {"authority-denied"}
        assert yaml.safe_load(refused.stdout)["error"]["code"] in expected, refused.stdout
    assert yaml.safe_load(team_file.read_text(encoding="utf-8"))["members"]["engineer"]["session_ref"] == seat


def _native_rollout(
    tmp_path: Path, thread: str, *, records: list[dict]
) -> Path:
    """Write one native Codex session rollout and point the environment at it."""
    home = tmp_path / "codex-home"
    session = home / "sessions" / "2026" / "09" / "22"
    session.mkdir(parents=True, exist_ok=True)
    rollout = session / "rollout-2026-09-22T00-00-00-{0}.jsonl".format(thread)
    rollout.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    return home


def _escalated_call_records(command: str, cwd: str) -> list[dict]:
    """One escalated tool call that the native Runtime then produced a result for."""
    call_id = "call_escalated"
    return [
        {"type": "session_meta", "payload": {"session_id": "thread"}},
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": call_id,
                "input": (
                    'text(await tools.exec_command({cmd:"' + command
                    + '",workdir:"' + cwd
                    + '",sandbox_permissions:"require_escalated",yield_time_ms:1000}));'
                ),
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "custom_tool_call_output", "call_id": call_id},
        },
    ]


@pytest.mark.parametrize("output", [None, "Command completed", "Permission denied", "Cancelled"])
def test_caller_selected_history_cannot_authorize_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str | None
) -> None:
    """History, including a denied or replayed result, grants no replacement authority."""
    runner_directory = tmp_path / "harness" / ".graphtraj" / "runner"
    leader = "132-ticket-handover0-team_leader@team_leader"
    member = "132-ticket-handover0-engineer@engineer_2"
    _record_direct_session(runner_directory, leader, "team_leader", None)
    _record_direct_session(runner_directory, member, "engineer", leader)
    thread = "01a0c781-608b-7a90-b640-1422636d029f"
    command = _replacement_command(member)
    monkeypatch.setattr(sys, "argv", list(command))
    records = _escalated_call_records(" ".join(command), os.getcwd())
    if output is None:
        records.pop()
    else:
        records[-1]["payload"]["output"] = output
    home = _native_rollout(tmp_path, thread, records=records)
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("CODEX_THREAD_ID", thread)

    # Neither the first use nor a replay can promote Main or a Session caller.
    for caller in (None, member):
        monkeypatch.setattr(runner_status, "session_operation", lambda *args: {"approval": None})
        for _ in range(2):
            with pytest.raises(RunnerError) as refused:
                _ask_to_replace(runner_directory, caller, member, monkeypatch)
            assert refused.value.code == "authority-denied"

    # Direct ownership still authorizes without consulting the fabricated history.
    _ask_to_replace(runner_directory, None, leader, monkeypatch)
    _ask_to_replace(runner_directory, leader, member, monkeypatch)
