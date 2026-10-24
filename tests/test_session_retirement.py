"""Retirement and replacement retries through installed public operations."""

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml
import pytest

from conftest import FakeCodex, InstalledCommands, wait_for_file
from runner_fixtures import configure_harness
from test_task_recovery import command, events, installed_commands, prepare


def _withdrawn_mapping(
    alias: str,
    root: Path,
    *,
    worker_pid: int,
    runtime_pid: int,
    session: str | None = None,
    parent: str | None = None,
) -> dict:
    """Return the mapping shape the withdrawn hosted registration actually wrote."""
    purpose = alias.split("_", 1)[0]
    return {
        "alias": alias, "purpose": purpose, "parent": parent, "runtime": "codex",
        "hosted": True, "role": purpose, "task_id": None, "team_generation": None,
        "worktree_path": str(root), "session": session,
        "worker_pid": worker_pid, "runtime_pid": runtime_pid,
    }


def _withdrawn_record(root: Path, alias: str, mapping: dict) -> Path:
    """Write one retained withdrawn hosted record beside the current sessions."""
    directory = root / ".graphtraj/runner/sessions" / alias
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.yml").write_text(
        yaml.safe_dump({"alias": alias, "purpose": mapping["purpose"]}))
    (directory / "mapping.yml").write_text(yaml.safe_dump(mapping))
    (directory / "events.jsonl").write_text(
        json.dumps({"operation": "adopt-main", "alias": alias}) + "\n")
    return directory


def _exited_pid() -> int:
    """Return a process identifier whose process has already been reaped."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _current_mapping(alias: str, root: Path, *, parent: str | None = None) -> dict:
    """Return one complete current execution mapping for an adjacent Session."""
    return {
        "alias": alias, "runtime": "codex", "session": "native-session",
        "task_id": "154", "team_generation": 1, "role": "researcher", "parent": parent,
        "retained_batch_file": "batch.yml", "worktree_path": str(root),
        "trace_file": str(root / "trace"), "worker_pid": 111, "runtime_pid": 111,
    }


def _retired_record(root: Path, alias: str, *, parent: str) -> Path:
    """Write one retained record whose active mapping is already removed."""
    directory = (root / ".graphtraj/state/tasks/154-recovery/teams/1/traces"
                 / alias / "runner")
    directory.mkdir(parents=True, exist_ok=True)
    mapping = _withdrawn_mapping(
        alias, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid(), parent=parent)
    (directory / "session.yml").write_text(yaml.safe_dump(
        {"alias": alias, "purpose": mapping["purpose"],
         "retirement": {"member": None, "mapping": mapping}}))
    return directory


def test_withdrawn_hosted_record_retires_and_reports_retired(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Only the active mapping is removed; evidence and neighbors are retained."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path)
    alias = "main_" + "a" * 32 + "@m1"
    mapping = _withdrawn_mapping(
        alias, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid())
    directory = _withdrawn_record(root, alias, mapping)
    evidence = {name: (directory / name).read_bytes() for name in ("session.yml", "events.jsonl")}

    neighbor = root / ".graphtraj/runner/sessions/researcher@x1"
    neighbor.mkdir(parents=True)
    (neighbor / "mapping.yml").write_text(yaml.safe_dump(_current_mapping("researcher@x1", root)))
    neighbor_mapping = (neighbor / "mapping.yml").read_bytes()
    association = root / ".graphtraj/runner/main-sessions/finalize_keep/session.yml"
    association.parent.mkdir(parents=True)
    association.write_text(yaml.safe_dump(
        {"runtime": "codex", "session": "native-main", "summary_issue": ""}))
    association_record = association.read_bytes()

    retired = command(installed_commands, root, env, "retire", alias)
    assert retired.returncode == 0, retired.stdout + retired.stderr
    assert "retired" in retired.stdout
    assert not (directory / "mapping.yml").exists()
    record = yaml.safe_load((directory / "session.yml").read_text())
    assert record["alias"] == alias and record["purpose"] == "main"
    assert record["retirement"]["mapping"] == mapping
    assert (directory / "events.jsonl").read_bytes() == evidence["events.jsonl"]
    assert (neighbor / "mapping.yml").read_bytes() == neighbor_mapping
    assert association.read_bytes() == association_record

    status = command(installed_commands, root, env, "status", alias)
    assert "invalid" not in status.stdout, status.stdout
    assert "retire_status: retired" in status.stdout, status.stdout

    repeated = command(installed_commands, root, env, "retire", alias)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "retired" in repeated.stdout


def test_withdrawn_hosted_record_refusals_keep_every_record(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A live owner, a dependent record or a Main association refuses with no change."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path)

    # A live owner process proves the record is still in use.
    alive = "main_" + "b" * 32 + "@m1"
    _withdrawn_record(root, alive, _withdrawn_mapping(
        alive, root, worker_pid=os.getpid(), runtime_pid=_exited_pid()))

    # A recorded descendant still names the alias as its parent.
    parented = "main_" + "c" * 32 + "@m1"
    _withdrawn_record(root, parented, _withdrawn_mapping(
        parented, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid()))
    child = "checker_" + "d" * 32 + "@m1"
    child_directory = _withdrawn_record(root, child, _withdrawn_mapping(
        child, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid(), parent=parented))

    # A current Main association still references the recorded native Session.
    bound = "main_" + "e" * 32 + "@m1"
    _withdrawn_record(root, bound, _withdrawn_mapping(
        bound, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid(),
        session="native-bound"))
    association = root / ".graphtraj/runner/main-sessions/finalize_bound/session.yml"
    association.parent.mkdir(parents=True)
    association.write_text(yaml.safe_dump({"runtime": "codex", "session": "native-bound"}))

    sessions = root / ".graphtraj/runner/sessions"
    retained = {alias: (sessions / alias / "mapping.yml").read_bytes()
                for alias in (alive, parented, bound)}
    for alias, reason in (
        (alive, "owner-process-alive"),
        (parented, "descendant-record-present"),
        (bound, "main-association-active"),
    ):
        refused = command(installed_commands, root, env, "retire", alias)
        assert refused.returncode == 1, refused.stdout + refused.stderr
        assert reason in refused.stdout, refused.stdout
        assert (sessions / alias / "mapping.yml").is_file()
        record = yaml.safe_load((sessions / alias / "session.yml").read_text())
        assert record.get("retirement") is None
    assert all((sessions / alias / "mapping.yml").read_bytes() == content
               for alias, content in retained.items())
    assert (child_directory / "mapping.yml").is_file()


def test_retired_descendant_does_not_block_legacy_retirement(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A record that already retired keeps its historical parent without blocking."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path)
    alias = "main_" + "f" * 32 + "@m1"
    mapping = _withdrawn_mapping(
        alias, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid())
    directory = _withdrawn_record(root, alias, mapping)
    retired_child = _retired_record(root, "checker_" + "1" * 32 + "@m1", parent=alias)
    retired_record = (retired_child / "session.yml").read_bytes()
    neighbor = root / ".graphtraj/runner/sessions/researcher@x1"
    neighbor.mkdir(parents=True)
    (neighbor / "mapping.yml").write_text(yaml.safe_dump(_current_mapping("researcher@x1", root)))
    neighbor_mapping = (neighbor / "mapping.yml").read_bytes()

    retired = command(installed_commands, root, env, "retire", alias)
    assert retired.returncode == 0, retired.stdout + retired.stderr
    assert "retired" in retired.stdout
    assert not (directory / "mapping.yml").exists()
    record = yaml.safe_load((directory / "session.yml").read_text())
    assert record["retirement"]["mapping"] == mapping
    assert (retired_child / "session.yml").read_bytes() == retired_record
    assert (neighbor / "mapping.yml").read_bytes() == neighbor_mapping

    status = command(installed_commands, root, env, "status", alias)
    assert "invalid" not in status.stdout, status.stdout
    assert "retire_status: retired" in status.stdout, status.stdout


def test_current_or_unparented_descendant_still_blocks_legacy_retirement(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A current child names itself in the reason; an unknown record keeps refusing."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path)

    # A current, still-mapped child names the alias as its parent.
    parented = "main_" + "c" * 32 + "@m1"
    _withdrawn_record(root, parented, _withdrawn_mapping(
        parented, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid()))
    child = "analyst@x1"
    child_directory = root / ".graphtraj/runner/sessions" / child
    child_directory.mkdir(parents=True)
    (child_directory / "mapping.yml").write_text(
        yaml.safe_dump(_current_mapping(child, root, parent=parented)))

    retained = (child_directory / "mapping.yml").read_bytes()
    refused = command(installed_commands, root, env, "retire", parented)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "descendant-record-present:" + child in refused.stdout, refused.stdout
    assert (root / ".graphtraj/runner/sessions" / parented / "mapping.yml").is_file()
    assert (child_directory / "mapping.yml").read_bytes() == retained

    # A record without parentage cannot prove exclusion.
    unknown = "main_" + "9" * 32 + "@m1"
    _withdrawn_record(root, unknown, _withdrawn_mapping(
        unknown, root, worker_pid=_exited_pid(), runtime_pid=_exited_pid()))
    loose = "researcher@x1"
    loose_directory = root / ".graphtraj/runner/sessions" / loose
    loose_directory.mkdir(parents=True)
    (loose_directory / "mapping.yml").write_text(yaml.safe_dump({"alias": loose}))

    refused_unknown = command(installed_commands, root, env, "retire", unknown)
    assert refused_unknown.returncode == 1, refused_unknown.stdout
    assert "descendant-state-unknown" in refused_unknown.stdout, refused_unknown.stdout
    assert (root / ".graphtraj/runner/sessions" / unknown / "mapping.yml").is_file()
    assert (loose_directory / "mapping.yml").is_file()


def test_retire_refuses_running_descendant_then_preserves_history(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A terminal parent is insufficient; retirement neither interrupts nor deletes."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher', child=True)
    alias = task['alias']
    runner = root / '.graphtraj/runner/sessions'
    child = json.loads((Path(task['worktree_path']) / 'child.json').read_text())['alias']
    try:
        wait_for_file(runner / alias / 'execution.yml')
        original = yaml.safe_load((runner / alias / 'mapping.yml').read_text())
        refused = command(installed_commands, root, env, 'retire', alias)
        assert refused.returncode == 1 and 'replacement-not-stopped' in refused.stdout
        assert (runner / alias / 'mapping.yml').is_file()
        assert not (runner / alias / 'stop.yml').exists()
        assert not (runner / child / 'execution.yml').exists()
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        evidence = {name: (runner / alias / name).read_bytes()
                    for name in ('launch.yml', 'execution.yml', 'events.jsonl')}
        retired = command(installed_commands, root, env, 'retire', alias)
        assert retired.returncode == 0, retired.stdout + retired.stderr
        assert 'retired' in retired.stdout
        assert not (runner / alias).exists()
        assert yaml.safe_load((Path(original['trace_file']).parent / 'runner/session.yml').read_text())['retirement']['mapping'] == original
        assert all((Path(original['trace_file']).parent / 'runner' / name).read_bytes() == content for name, content in evidence.items())
        assert Path(task['worktree_path']).is_dir()
        assert yaml.safe_load((runner / child / 'mapping.yml').read_text())['parent'] == alias
        team = yaml.safe_load((root / '.graphtraj/state/tasks/154-recovery/teams/1/team.yml').read_text())
        assert alias not in {member['session_ref'] for member in team['members'].values()}
        from graphtraj.execution.runner_status import runtime_caller
        from graphtraj.interfaces.tools import read_reports

        with runtime_caller(runner.parent, child):
            assert read_reports({'alias': alias}, cwd=root).document['alias'] == alias
        assert command(installed_commands, root, env, 'status', alias).returncode == 0
        stale = command(installed_commands, root, env, 'send', alias, '--instruction', 'Work',
                        '--caused-by-event-id', events(root)[-1]['event_id'])
        assert stale.returncode == 1 and 'session-retired' in stale.stdout
        assert command(installed_commands, root, env, 'retire', alias).returncode == 0
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


def test_replace_retries_after_retirement_without_reviving_or_duplicating(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A repeatable Runtime preflight failure leaves a retired seat for public retry."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher')
    alias = task['alias']
    runner = root / '.graphtraj/runner/sessions'
    successor = None
    try:
        assert command(installed_commands, root, env, 'interrupt', alias).returncode == 0
        cause = events(root)[-1]['event_id']
        roles_file = root / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_file.read_text())
        roles['roles']['researcher']['instructions'] = 'missing-role-instructions.txt'
        roles_file.write_text(yaml.safe_dump(roles))
        failed = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert failed.returncode == 1, failed.stdout + failed.stderr
        result = yaml.safe_load(failed.stdout)
        assert result['completed_actions'] == ['retired']
        assert result['replace_status'] == 'failed' and result['error']
        assert not (runner / alias).exists()
        assert len(list(runner.iterdir())) == 0
        (root / 'missing-role-instructions.txt').write_text('Continue the accepted task.\n')
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        successor = yaml.safe_load(replaced.stdout)['replacement_alias']
        wait_for_file(runner / successor / 'execution.yml')
        repeated = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert yaml.safe_load(repeated.stdout)['replacement_alias'] == successor
        assert len(list(runner.iterdir())) == 1
        assert not (runner / alias).exists()
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', successor or alias)


def test_retire_unknown_termination_does_not_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable terminated Worker is uncertainty, not implicit stop authority."""
    from types import SimpleNamespace

    from graphtraj.execution import runner_control, runner_retirement, runner_status
    from graphtraj.execution.runner_models import RunnerError
    from test_direct_control_authority import _record_direct_session

    runner = tmp_path / 'runner'
    alias = '240-retirement-handover0-researcher@unknown'
    _record_direct_session(runner, alias, 'researcher', None)
    monkeypatch.setattr(runner_retirement, 'discover_project',
                        lambda *args, **kwargs: SimpleNamespace(runner_directory=runner))
    monkeypatch.setattr(runner_status, 'caller_alias', lambda directory: None)

    def unreachable(*args, **kwargs) -> dict:
        """Represent an owner that no longer answers native status."""
        raise RunnerError('operation-failed', 'Owner unavailable')

    monkeypatch.setattr(runner_status, 'session_operation', unreachable)
    monkeypatch.setattr(runner_status, '_unresponsive_status', lambda *args: {'activity': 'abnormal'})
    monkeypatch.setattr(runner_control, 'respond_to_abnormal_session',
                        lambda *args: pytest.fail('Retirement must not trigger interruption'))
    with pytest.raises(RunnerError, match='must be stopped'):
        runner_retirement.retire_session(alias, tmp_path)
    assert (runner / 'sessions' / alias / 'mapping.yml').is_file()
    assert not (runner / 'sessions' / alias / 'stop.yml').exists()
