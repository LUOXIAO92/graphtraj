from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_ticket_graph import _change_status, _register, _ticket
from test_task_recovery import installed_commands


@dataclass(frozen=True)
class DeliveredTicket:
    root: Path
    repository: Path
    state: Path
    worktree: Path
    branch: str
    ticket_id: str
    ticket_name: str
    ticket_directory: Path
    environment: dict[str, str]
    commands: InstalledCommands
    failed_start_aliases: tuple[str, ...]


def _deliver_ticket(
    commands: InstalledCommands,
    repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    *,
    integrate: bool,
    failed_start: bool = False,
    terminal_failed_start: bool = False,
) -> DeliveredTicket:
    root, worktrees, _, environment = configure_harness(
        commands, repository, fake_codex, tmp_path
    )
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['failed_start'] = dict(roles['roles']['coding_team']['engineer'])
    roles['role_tree'] = {'coding-team.engineer': {}, 'failed_start': {}}
    roles_file.write_text(yaml.safe_dump(roles))
    ticket_id = "85"
    ticket_name = "cleanup-integrated-ticket"
    _register(commands, root, _ticket(ticket_id, ticket_name))
    _change_status(commands, root, ticket_id, "ready")
    batch = root / "team-batch.yml"
    batch.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "ticket_id": ticket_id,
                        "ticket_name": ticket_name,
                        "role": "coding-team.engineer",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    failed_start_aliases: tuple[str, ...] = ()
    if failed_start or terminal_failed_start:
        if failed_start:
            environment["FAKE_CODEX_UNSUPPORTED"] = "1"
        else:
            environment.update(FAKE_CODEX_EVENTS="[]", FAKE_CODEX_EXIT_CODE="1")
        if terminal_failed_start:
            failed_batch = yaml.safe_load(batch.read_text())
            failed_batch['tasks'][0]['role'] = 'failed_start'
            batch.write_text(yaml.safe_dump(failed_batch))
        failed = run_process(
            [str(commands.runner), "--swarm-input", str(batch)],
            cwd=root,
            env=environment,
            timeout=15,
        )
        assert failed.returncode == 1
        if terminal_failed_start:
            failed_batch['tasks'][0]['role'] = 'coding-team.engineer'
            batch.write_text(yaml.safe_dump(failed_batch))
        sessions = root / ".graphtraj" / "runner" / "sessions"
        if failed_start:
            assert not sessions.exists() or not list(sessions.iterdir())
            # Preserve coverage for historical allocations from before preflight
            # moved ahead of reservation; new unsupported Runtimes leave none.
            historical = sessions / "85-cleanup_integrated_ticket-handover0-team_leader@unstarted"
            historical.mkdir(parents=True)
            (historical / "events.jsonl").touch()
            traces = (root / ".graphtraj/state/tickets/85-cleanup-integrated-ticket"
                      / "teams/1/traces" / historical.name)
            traces.mkdir(parents=True)
            (traces / "events.jsonl").touch()
        failed_start_aliases = tuple(
            directory.name for directory in sessions.iterdir() if directory.is_dir()
        )
        assert failed_start_aliases
        if failed_start:
            environment.pop("FAKE_CODEX_UNSUPPORTED")
        else:
            environment.pop("FAKE_CODEX_EVENTS")
            environment.pop("FAKE_CODEX_EXIT_CODE")
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(commands.runner),
    )
    launched = run_process(
        [str(commands.runner), "--swarm-input", str(batch)],
        cwd=root,
        env=environment,
        timeout=15,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    wait_for_file(root / '.graphtraj/runner/sessions' / alias / 'execution.yml')
    reported = run_process([str(commands.runner), 'reports', alias], cwd=root, env=environment)
    submission = yaml.safe_load(reported.stdout)['submissions'][-1]
    accepted = run_process([
        str(commands.runner), 'decide-result', '--submission-id', submission['event_id'],
        '--commit', submission['candidate'], '--decision', 'accepted', '--reason', 'Fixture task completed',
        '--evidence-ref', submission['evidence_refs'][0],
    ], cwd=root, env=environment)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    state = root / ".graphtraj" / "state"
    ticket_directory = state / "tickets" / (ticket_id + "-" + ticket_name)
    worktree = worktrees / (ticket_id + "-" + ticket_name)
    branch = "agent/" + ticket_id + "-" + ticket_name
    status = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
    assert status["status"] == "awaiting-integration"
    assert run_process(["git", "status", "--porcelain"], cwd=worktree).stdout == ""

    if integrate:
        integrated = run_process(
            [
                str(commands.product),
                "ticket",
                "integrate",
                "--ticket-id",
                ticket_id,
                "--",
                sys.executable,
                "-c",
                "pass",
            ],
            cwd=root,
            env=environment,
            timeout=15,
        )
        assert integrated.returncode == 0, integrated.stderr
        status = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
        assert status["status"] == "integrated"

    return DeliveredTicket(
        root=root,
        repository=repository,
        state=state,
        worktree=worktree,
        branch=branch,
        ticket_id=ticket_id,
        ticket_name=ticket_name,
        ticket_directory=ticket_directory,
        environment=environment,
        commands=commands,
        failed_start_aliases=failed_start_aliases,
    )


@pytest.fixture
def integrated_ticket(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> DeliveredTicket:
    return _deliver_ticket(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
    )


def _cleanup(ticket: DeliveredTicket):
    """Exercise cleanup through the installed CLI in this isolated fixture."""
    return run_process(
        [str(ticket.commands.runner), "cleanup", "--ticket-id", ticket.ticket_id],
        cwd=ticket.root, env=ticket.environment, timeout=15,
    )


def _ticket_mappings(ticket: DeliveredTicket) -> list[Path]:
    sessions = ticket.root / ".graphtraj" / "runner" / "sessions"
    mappings = []
    for directory in sessions.iterdir():
        mapping_file = directory / "mapping.yml"
        if mapping_file.is_file():
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
            if mapping.get("ticket_id") == ticket.ticket_id and "run_id" not in mapping:
                mappings.append(directory)
    return mappings


def _durable_contents(ticket: DeliveredTicket) -> dict[str, bytes]:
    roots = (
        ticket.ticket_directory,
        ticket.state / "batches",
        ticket.state / "worldline",
    )
    return {
        path.relative_to(ticket.root).as_posix(): path.read_bytes()
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _assert_durable_contents(ticket: DeliveredTicket, before: dict[str, bytes]) -> None:
    """Keep all evidence; only current member references and appended events change."""
    after = _durable_contents(ticket)
    for name, content in before.items():
        if name.endswith('/team.yml'):
            original = yaml.safe_load(content)
            current = yaml.safe_load(after[name])
            assert {**original, 'members': current['members']} == current
            assert {name: member['role'] for name, member in original['members'].items()} == {
                name: member['role'] for name, member in current['members'].items()
            }
        elif '/worldline/' in name:
            assert after[name].startswith(content)
        else:
            assert after[name] == content


def _append_worldline_reference(ticket: DeliveredTicket, evidence: Path) -> dict:
    event = ticket.root / "cleanup-evidence.yml"
    event.write_text(
        yaml.safe_dump(
            {
                "event": "cleanup-evidence-recorded",
                "caused_by_event_ids": [],
                "evidence_refs": [evidence.relative_to(ticket.root).as_posix()],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    appended = run_process(
        [str(ticket.commands.product), "worldline", "append", "--event-file", str(event)],
        cwd=ticket.root,
        env=ticket.environment,
    )
    assert appended.returncode == 0, appended.stderr
    return yaml.safe_load(appended.stdout)


def test_installed_cleanup_uses_only_ticket_identity_and_preserves_trajectory(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    help_result = run_process(
        [str(ticket.commands.runner), "cleanup", "--help"], cwd=ticket.root
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--ticket-id" in help_result.stdout
    assert "--run-id" not in help_result.stdout

    historical_run = ticket.state / "20260101-historical-delivery-run"
    historical_run.mkdir()
    historical_marker = historical_run / "evidence.md"
    historical_marker.write_text("historical evidence\n", encoding="utf-8")
    durable_before = _durable_contents(ticket)
    mappings = _ticket_mappings(ticket)
    assert mappings

    cleaned = _cleanup(ticket)

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["ticket_id"] == ticket.ticket_id
    assert document["cleanup_status"] == "cleaned"
    assert "run_id" not in document
    assert not ticket.worktree.exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 1
    assert all(not (path / "mapping.yml").exists() for path in mappings)
    _assert_durable_contents(ticket, durable_before)
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"

    repeated = _cleanup(ticket)

    assert repeated.returncode == 0, repeated.stderr
    repeated_document = yaml.safe_load(repeated.stdout)
    assert repeated_document["cleanup_status"] == "already-cleaned"
    assert "run_id" not in repeated_document
    _assert_durable_contents(ticket, durable_before)
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"


def test_installed_cleanup_allows_missing_worldline_evidence(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    mappings = _ticket_mappings(ticket)
    event = _append_worldline_reference(ticket, mappings[0] / "mapping.yml")

    result = _cleanup(ticket)

    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert not ticket.worktree.exists()
    assert all(not (path / "mapping.yml").exists() for path in mappings)
    read_after_cleanup = run_process(
        [str(ticket.commands.product), "worldline", "read"],
        cwd=ticket.root,
        env=ticket.environment,
    )
    assert read_after_cleanup.returncode == 0, read_after_cleanup.stderr
    assert event in [json.loads(line) for line in read_after_cleanup.stdout.splitlines()]
    new_evidence = ticket.root / "new-evidence.md"
    new_evidence.write_text("new evidence\n", encoding="utf-8")
    appended = _append_worldline_reference(ticket, new_evidence)
    assert appended in [
        json.loads(line)
        for line in run_process(
            [str(ticket.commands.product), "worldline", "read"],
            cwd=ticket.root,
            env=ticket.environment,
        ).stdout.splitlines()
    ]


def test_installed_cleanup_removes_historical_preflight_allocation_after_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    ticket = _deliver_ticket(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
        failed_start=True,
    )
    sessions = ticket.root / ".graphtraj" / "runner" / "sessions"
    failed_sessions = [sessions / alias for alias in ticket.failed_start_aliases]
    assert len(failed_sessions) == 1
    failed_session = failed_sessions[0]
    events = failed_session / "events.jsonl"
    trace = (
        ticket.ticket_directory
        / "teams"
        / "1"
        / "traces"
        / failed_session.name
        / "events.jsonl"
    )
    assert not (failed_session / "mapping.yml").exists()
    # Historical preflight residue has empty Session and Trace entries.
    assert events.is_file() and events.read_bytes() == b""
    assert trace.is_file() and not trace.is_symlink()
    assert trace.read_bytes() == b""
    durable_before = _durable_contents(ticket)
    mappings = _ticket_mappings(ticket)

    cleaned = _cleanup(ticket)

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert set(ticket.failed_start_aliases) <= set(document["aliases_removed"])
    assert not ticket.worktree.exists()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 1
    assert all(not session.exists() for session in failed_sessions)
    assert all(not (mapping / "mapping.yml").exists() for mapping in mappings)
    assert trace.read_bytes() == b""
    _assert_durable_contents(ticket, durable_before)

    repeated = _cleanup(ticket)

    assert repeated.returncode == 0, repeated.stderr
    assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"


@pytest.mark.parametrize("failure_case", ("confirmed", "uncertain", "foreign"))
def test_installed_cleanup_retains_a_terminal_unmapped_startup_failure_after_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    failure_case: str,
) -> None:
    """Cleanup reports retained proof, refusing uncertain or foreign allocations."""
    ticket = _deliver_ticket(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=True,
        terminal_failed_start=True,
    )
    sessions = ticket.root / ".graphtraj" / "runner" / "sessions"
    failed_sessions = [sessions / alias for alias in ticket.failed_start_aliases]
    assert len(failed_sessions) == 1
    failed_session = failed_sessions[0]
    trace = (
        ticket.ticket_directory
        / "teams"
        / "1"
        / "traces"
        / failed_session.name
        / "events.jsonl"
    )
    launch = yaml.safe_load((failed_session / "launch.yml").read_text(encoding="utf-8"))
    failure = yaml.safe_load(
        (failed_session / "launch-error.yml").read_text(encoding="utf-8")
    )
    assert not (failed_session / "mapping.yml").exists()
    assert launch["mapping"]["alias"] == failed_session.name
    assert launch["mapping"]["ticket_id"] == ticket.ticket_id
    assert Path(launch["mapping"]["retained_batch_file"]).is_file()
    assert failure["terminal_confirmed"] is True
    assert (failed_session / "worker-stderr.log").is_file()
    # The Runner keeps its own records in the Session directory, while this
    # Runtime failure left the Trace entry empty and unlinked.
    session_records = (failed_session / "events.jsonl").read_text(encoding="utf-8")
    assert '"type":"runtime"' in session_records
    assert '"type": "runner-execution-start"' in session_records
    assert trace.is_file() and not trace.is_symlink()
    assert trace.read_bytes() == b""
    if failure_case == "uncertain":
        failure["terminal_confirmed"] = False
        failure["message"] = "private startup diagnostic fixture-secret"
        (failed_session / "launch-error.yml").write_text(yaml.safe_dump(failure))
    elif failure_case == "foreign":
        launch["mapping"]["ticket_id"] = "another-ticket"
        (failed_session / "launch.yml").write_text(yaml.safe_dump(launch))
    durable_before = _durable_contents(ticket)
    allocation_before = {path.name: path.read_bytes() for path in failed_session.iterdir()
                         if path.is_file() and not path.is_symlink()}

    cleaned = _cleanup(ticket)

    if failure_case != "confirmed":
        assert cleaned.returncode == 1, cleaned.stdout + cleaned.stderr
        document = yaml.safe_load(cleaned.stdout)
        assert document["error"]["code"] == "cleanup-ownership-mismatch"
        assert document["evidence"]["allocation_failures"][failed_session.name] == {
            "trace_valid": True,
            "launch_matches_ticket": failure_case != "foreign",
            "terminal_confirmed": failure_case != "uncertain",
        }
        assert "fixture-secret" not in cleaned.stdout
        assert ticket.worktree.is_dir()
        assert {path.name: path.read_bytes() for path in failed_session.iterdir()
                if path.is_file() and not path.is_symlink()} == allocation_before
        assert _durable_contents(ticket) == durable_before
        return

    assert cleaned.returncode == 0, cleaned.stderr
    document = yaml.safe_load(cleaned.stdout)
    assert document["cleanup_status"] == "cleaned"
    assert set(ticket.failed_start_aliases) <= set(document["aliases_removed"])
    assert all(not session.exists() for session in failed_sessions)
    _assert_durable_contents(ticket, durable_before)


def test_installed_cleanup_refuses_an_unattributed_session_record_without_partial_cleanup(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    sessions = ticket.root / ".graphtraj" / "runner" / "sessions"
    record = sessions / (ticket.ticket_id + "-" + ticket.ticket_name + "@e99")
    record.mkdir()
    (record / "events.jsonl").write_text(
        '{"type":"runtime","runtime":"codex"}\n', encoding="utf-8"
    )
    trace = (
        ticket.ticket_directory
        / "teams"
        / "1"
        / "traces"
        / record.name
        / "events.jsonl"
    )
    trace.parent.mkdir()
    trace.touch()
    mappings = _ticket_mappings(ticket)

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert ticket.worktree.is_dir()
    assert record.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_ticket_without_validated_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    ticket = _deliver_ticket(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
        integrate=False,
    )
    mappings = _ticket_mappings(ticket)

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-not-integrated"
    assert ticket.worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_branch_that_is_no_longer_integrated(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    later = ticket.worktree / "later-work.txt"
    later.write_text("not part of the validated candidate\n", encoding="utf-8")
    run_process(["git", "add", later.name], cwd=ticket.worktree).check_returncode()
    run_process(
        ["git", "commit", "-m", "Later Ticket work"], cwd=ticket.worktree
    ).check_returncode()
    mappings = _ticket_mappings(ticket)

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-not-integrated"
    assert ticket.worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_a_dirty_ticket_without_partial_cleanup(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    dirty = ticket.worktree / "unfinished.txt"
    dirty.write_text("uncommitted work\n", encoding="utf-8")
    mappings = _ticket_mappings(ticket)

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-dirty"
    assert dirty.read_text(encoding="utf-8") == "uncommitted work\n"
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


def test_installed_cleanup_refuses_an_executing_ticket_agent_without_partial_cleanup(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    mapping_directory = _ticket_mappings(ticket)[0]
    mapping_file = mapping_directory / "mapping.yml"
    mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    agent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    mapping["worker_pid"] = agent.pid
    mapping["runtime_pid"] = agent.pid
    mapping_file.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    try:
        result = _cleanup(ticket)
    finally:
        agent.terminate()
        agent.wait(timeout=5)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "worktree-busy"
    assert ticket.worktree.is_dir()
    assert mapping_directory.is_dir()
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


@pytest.mark.parametrize("change", ("worktree", "branch"))
def test_installed_cleanup_refuses_noncanonical_ticket_resources_without_partial_cleanup(
    change: str,
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    mappings = _ticket_mappings(ticket)
    if change == "worktree":
        moved = ticket.worktree.with_name("moved-by-operator")
        run_process(
            ["git", "worktree", "move", str(ticket.worktree), str(moved)],
            cwd=ticket.repository,
        ).check_returncode()
        retained_worktree = moved
    else:
        run_process(
            ["git", "switch", "-c", "operator-cleanup-branch"],
            cwd=ticket.worktree,
        ).check_returncode()
        retained_worktree = ticket.worktree

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-ownership-mismatch"
    assert retained_worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0


def test_cleanup_preserves_shared_worktree_with_another_ticket_execution(
    integrated_ticket: DeliveredTicket,
) -> None:
    """An unrelated active mapping using the same Worktree prevents deletion."""
    ticket = integrated_ticket
    original = _ticket_mappings(ticket)[0]
    mapping = yaml.safe_load((original / 'mapping.yml').read_text())
    alias = '86-other_ticket-handover0-researcher@shared'
    foreign = original.parent / alias
    foreign.mkdir()
    mapping.update(alias=alias, ticket_id='86', parent=None,
                   worktree_path=str(ticket.worktree), worker_pid=os.getpid(), runtime_pid=os.getpid())
    (foreign / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    before = (foreign / 'mapping.yml').read_bytes()

    result = _cleanup(ticket)

    assert result.returncode == 1, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout)['error']['code'] == 'worktree-busy'
    assert ticket.worktree.is_dir()
    assert (foreign / 'mapping.yml').read_bytes() == before
    assert not (foreign / 'stop.yml').exists()
    assert all((directory / 'mapping.yml').exists() for directory in _ticket_mappings(ticket))
