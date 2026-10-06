"""Adoption distinguishes retained failed allocations from execution identities."""

import io
import json
import os
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.execution import runner_worker
from graphtraj.execution.runner_transport import runtime_launch_failure
from graphtraj.interfaces.cli.graphtraj import main
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from test_host_adoption import external
from test_host_adoption import invoke_hook, EVENT
from test_main_finalize import host


def worker_attempt(root: Path, alias: str, monkeypatch: pytest.MonkeyPatch, *, fail: bool, parent_connection: dict | None = None) -> Path:
    """Execute a real Runner job, controlling only its native creation result."""
    directory = root / '.graphtraj/runner/sessions' / alias
    directory.mkdir()
    job = {'operation': 'launch', 'runtime': 'codex', 'adapter_request': {}, 'mapping': {
        'alias': alias, 'runtime': 'codex', 'parent': None, 'parent_connection': parent_connection, 'ticket_id': 'fixture',
        'team_generation': 1, 'role': 'engineer', 'worktree_path': str(root),
        'trace_file': str(directory / 'trace.jsonl'), 'retained_batch_file': str(root / 'batch.yml'),
    }}
    launch = directory / 'launch.yml'
    launch.write_text(yaml.safe_dump(job))

    class Execution:
        """Fail before creation or complete a genuinely published Worker binding."""

        execution_id = None

        def run(self) -> dict:
            """Publish only the successful attempt's native execution association."""
            if fail:
                raise RuntimeAdapterError('RUNTIME_START_FAILED', 'Controlled startup failure.',
                                          terminal_confirmed=True)
            created('retry-session', os.getpid())
            self.execution_id = 'retry-turn'
            started('retry-session', os.getpid())
            return {'session_id': 'retry-session', 'execution_id': 'retry-turn',
                    'outcome': 'completed', 'last_agent_message': 'retry completed'}

        def operate(self, request: dict) -> dict:
            """Keep the normal Worker control interface available."""
            return {'activity': 'running'}

        def terminate(self) -> bool:
            """This controlled execution has no surviving native process."""
            return True

    class Adapter:
        """Supply controlled creation callbacks through the existing Worker seam."""

        def managed_execution(self, *args: object, **kwargs: object) -> Execution:
            """Capture the production Worker's creation and execution publishers."""
            nonlocal created, started
            created = kwargs['session_created']
            started = args[3]
            return Execution()

    created = started = None
    with monkeypatch.context() as patch:
        patch.setattr(runner_worker, 'select_runtime_adapter', lambda runtime: Adapter())
        patch.setattr('sys.stdin', io.StringIO('Exercise retained startup history.'))
        assert runner_worker.run(launch) == (1 if fail else 0)
    return directory


def snapshot(directory: Path) -> dict:
    """Retain fixture bytes to prove adoption did not clean or rewrite history."""
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def close_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close the real foreground owner after the public readiness document."""
    original = runner_worker.run_external_main

    def run(cwd: Path, resume: str | None, ready: Callable) -> dict:
        """Exercise real ownership without leaving a test foreground process."""
        def published(document: dict) -> None:
            """Publish the actual result and request normal owner closure."""
            ready(document)
            signal.raise_signal(signal.SIGTERM)

        return original(cwd, resume, published)

    monkeypatch.setattr(runner_worker, 'run_external_main', run)


def test_failed_worker_and_retry_history_do_not_block_adoption(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Public adoption succeeds after a failed creation and successful Worker retry."""
    root, proposals, _ = external
    failed = worker_attempt(root, '272-fixture-handover0-engineer@failed', monkeypatch, fail=True)
    retried = worker_attempt(root, '272-fixture-handover0-engineer@retry', monkeypatch, fail=False)
    before = snapshot(failed), snapshot(retried)
    sessions = root / '.graphtraj/runner/sessions'
    aliases = set(sessions.iterdir())
    close_when_ready(monkeypatch)
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code == 0, result.output
    documents = [json.loads(line) for line in result.stdout.splitlines()]
    assert [d['adoption_status'] for d in documents] == ['ready', 'closed']
    assert len(proposals) == 1 and proposals[0]['operation'] == 'adopt-main'
    assert len(set(sessions.iterdir()) - aliases) == 1
    assert (snapshot(failed), snapshot(retried)) == before
    # The successful retry is an established member, not another Main candidate.
    monkeypatch.setenv('CODEX_THREAD_ID', 'retry-session')
    refused = CliRunner().invoke(main, ['adopt-main'])
    assert refused.exit_code != 0 and 'already belongs' in refused.output
    assert len(proposals) == 1


@pytest.mark.parametrize('kind', ['empty', 'empty-events'])
def test_prelaunch_allocation_is_preserved(external: tuple, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """An allocation without a launch request cannot own a native execution."""
    root, proposals, _ = external
    directory = root / '.graphtraj/runner/sessions/272-fixture-handover0-engineer@prelaunch'
    directory.mkdir()
    if kind == 'empty-events':
        (directory / 'events.jsonl').touch()
    before = snapshot(directory)
    close_when_ready(monkeypatch)
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code == 0, result.output
    assert len(proposals) == 1 and snapshot(directory) == before


@pytest.mark.parametrize('kind', [
    'pending-root', 'unconfirmed', 'mapping', 'session', 'native', 'native-session',
    'execution', 'unknown', 'symlink', 'broken-symlink',
])
def test_uncertain_or_established_allocation_refuses_before_review(external: tuple, kind: str) -> None:
    """Only confirmed absence of execution permits exclusion; uncertainty stays visible."""
    root, proposals, _ = external
    sessions = root / '.graphtraj/runner/sessions'
    directory = sessions / '272-fixture-handover0-engineer@uncertain'
    if kind in ('symlink', 'broken-symlink'):
        target = root / 'link-target'
        if kind == 'symlink':
            target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
    else:
        directory.mkdir()
        (directory / 'launch.yml').write_text(yaml.safe_dump({
            'operation': 'launch', 'mapping': {'alias': directory.name, 'parent': None},
        }))
        if kind != 'pending-root':
            (directory / 'launch-error.yml').write_text(yaml.safe_dump(runtime_launch_failure(
                'RUNTIME_START_FAILED', 'Controlled retained failure.', '',
                terminal_confirmed=kind != 'unconfirmed',
            )))
        if kind not in ('pending-root', 'unconfirmed'):
            name = 'notes.txt' if kind == 'unknown' else f'{kind}.yml'
            if kind == 'unknown':
                (directory / 'launch-error.yml').unlink()
            (directory / name).write_text('uncertain record')
    aliases = set(sessions.iterdir())
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0
    assert directory.name in result.output and 'before adoption review' in result.output
    assert '"adoption_status": "ready"' not in result.output
    assert not proposals and set(sessions.iterdir()) == aliases


def test_restore_connection_conflict_still_refuses(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipping a failed allocation cannot authorize changing a restored native owner."""
    root, proposals, _ = external
    close_when_ready(monkeypatch)
    result = CliRunner().invoke(main, ['adopt-main'])
    alias = json.loads(result.stdout.splitlines()[0])['alias']
    monkeypatch.setenv('CODEX_HOME', str(root / 'different-native-home'))
    result = CliRunner().invoke(main, ['adopt-main', '--resume', alias])
    assert result.exit_code != 0 and 'cannot change the owning native connection' in result.output
    assert len(proposals) == 1


def test_pending_allocation_during_review_reports_registration_stage(
    external: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launch beginning during review cannot be silently ignored after registration."""
    from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter

    root, proposals, _ = external
    directory = root / '.graphtraj/runner/sessions/272-fixture-handover0-engineer@starting'
    directory.mkdir()
    original = CodexRuntimeAdapter.native_recovery_approval

    def review(adapter: object, proposal: dict, cwd: Path) -> dict:
        """Model the authoritative Runner writing a launch while approval is pending."""
        (directory / 'launch.yml').write_text(yaml.safe_dump({
            'operation': 'launch', 'mapping': {'alias': directory.name, 'parent': None},
        }))
        return original(adapter, proposal, cwd)

    monkeypatch.setattr(CodexRuntimeAdapter, 'native_recovery_approval', review)
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0 and 'after Agent registration' in result.output
    assert directory.name in result.output and '"adoption_status": "ready"' not in result.output
    assert len(proposals) == 1


def test_retired_checker_history_still_blocks_promotion(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Actual public retirement does not turn an established checker into an allocation."""
    from graphtraj.execution import host_adoption, runner_retirement
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces import tools

    root, proposals, _ = external
    runner = root / '.graphtraj/runner'
    monkeypatch.setattr(runner_retirement, 'discover_project', lambda *args, **kwargs: SimpleNamespace(
        runner_directory=runner, state_directory=root / '.graphtraj/state', harness_root=root,
    ))
    with host_adoption.external_main(root) as prepared:
        assert 'pass:' in invoke_hook(prepared, EVENT).stdout
        with runtime_caller(runner, prepared['alias']):
            records = tools.TOOLS['alias_status'].handler({}, cwd=root).document['agents']
            checker = next(record['alias'] for record in records if record.get('purpose') == 'checker')
            result = tools.TOOLS['retire'].handler({'alias': checker}, cwd=root)
            assert result.document['retire_status'] == 'retired'
        retained = runner / 'sessions' / checker
        before = snapshot(retained)
    monkeypatch.setenv('CODEX_THREAD_ID', 'checker')
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0 and 'already belongs' in result.output
    assert snapshot(retained) == before and len(proposals) == 1
