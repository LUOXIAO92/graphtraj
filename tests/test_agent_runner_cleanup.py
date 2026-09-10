from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_ticket_graph import _change_status, _register, _ticket


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
) -> DeliveredTicket:
    root, worktrees, _, environment = configure_harness(
        commands, repository, fake_codex, tmp_path
    )
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
                        "role": "team-leader",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    failed_start_aliases: tuple[str, ...] = ()
    if failed_start:
        environment["FAKE_CODEX_UNSUPPORTED"] = "1"
        failed = run_process(
            [str(commands.runner), "--batch-input", str(batch)],
            cwd=root,
            env=environment,
            timeout=15,
        )
        assert failed.returncode == 1
        failed_start_aliases = tuple(
            directory.name
            for directory in (root / ".graphtraj" / "runner" / "sessions").iterdir()
            if directory.is_dir()
        )
        assert failed_start_aliases
        environment.pop("FAKE_CODEX_UNSUPPORTED")
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(commands.runner),
    )
    launched = run_process(
        [str(commands.runner), "--batch-input", str(batch)],
        cwd=root,
        env=environment,
        timeout=15,
    )
    assert launched.returncode == 0, launched.stderr

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
    return run_process(
        [
            str(ticket.commands.runner),
            "cleanup",
            "--ticket-id",
            ticket.ticket_id,
        ],
        cwd=ticket.root,
        env=ticket.environment,
        timeout=15,
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


def _append_worldline_reference(ticket: DeliveredTicket, evidence: Path) -> dict:
    event = ticket.root / "cleanup-evidence.yml"
    event.write_text(
        yaml.safe_dump(
            {
                "kind": "cleanup-evidence-recorded",
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
    assert all(not path.exists() for path in mappings)
    assert _durable_contents(ticket) == durable_before
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"

    repeated = _cleanup(ticket)

    assert repeated.returncode == 0, repeated.stderr
    repeated_document = yaml.safe_load(repeated.stdout)
    assert repeated_document["cleanup_status"] == "already-cleaned"
    assert "run_id" not in repeated_document
    assert _durable_contents(ticket) == durable_before
    assert historical_marker.read_text(encoding="utf-8") == "historical evidence\n"


@pytest.mark.parametrize("referenced_path", ("mapping", "worktree", "worktree-state"))
def test_installed_cleanup_refuses_worldline_evidence_selected_for_deletion(
    referenced_path: str,
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    mappings = _ticket_mappings(ticket)
    evidence = (
        mappings[0] / "mapping.yml"
        if referenced_path == "mapping"
        else (
            ticket.worktree / "README.md"
            if referenced_path == "worktree"
            else ticket.worktree / ".state" / "ticket.yml"
        )
    )
    evidence_before = evidence.read_bytes()
    branch_before = run_process(
        ["git", "rev-parse", ticket.branch], cwd=ticket.repository
    ).stdout
    event = _append_worldline_reference(ticket, evidence)
    durable_before = _durable_contents(ticket)

    result = _cleanup(ticket)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    assert document["cleanup_status"] == "refused"
    assert document["error"]["code"] == "cleanup-failed"
    assert document["evidence"] == {
        "event_id": event["event_id"],
        "evidence_ref": evidence.relative_to(ticket.root).as_posix(),
        "deletion_target": str(
            mappings[0] if referenced_path == "mapping" else ticket.worktree
        ),
    }
    assert evidence.read_bytes() == evidence_before
    assert ticket.worktree.is_dir()
    assert all(path.is_dir() for path in mappings)
    assert run_process(
        ["git", "rev-parse", ticket.branch], cwd=ticket.repository
    ).stdout == branch_before
    assert run_process(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + ticket.branch],
        cwd=ticket.repository,
    ).returncode == 0
    assert _durable_contents(ticket) == durable_before
    assert run_process(
        [str(ticket.commands.product), "worldline", "read"],
        cwd=ticket.root,
        env=ticket.environment,
    ).returncode == 0


def test_installed_cleanup_removes_a_preflight_failed_team_session_after_integration(
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
    assert {path.name for path in failed_session.iterdir()} == {"events.jsonl"}
    assert events.read_bytes() == b""
    assert os.path.samefile(events, trace)
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
    assert all(not mapping.exists() for mapping in mappings)
    assert trace.read_bytes() == b""
    assert _durable_contents(ticket) == durable_before

    repeated = _cleanup(ticket)

    assert repeated.returncode == 0, repeated.stderr
    assert yaml.safe_load(repeated.stdout)["cleanup_status"] == "already-cleaned"


def test_installed_cleanup_refuses_an_unattributed_session_record_without_partial_cleanup(
    integrated_ticket: DeliveredTicket,
) -> None:
    ticket = integrated_ticket
    sessions = ticket.root / ".graphtraj" / "runner" / "sessions"
    record = sessions / (ticket.ticket_id + "-" + ticket.ticket_name + "@e99")
    record.mkdir()
    (record / "events.jsonl").touch()
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
