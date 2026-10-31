"""A Runtime that fails to start tells its parent why (421)."""
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil

import pytest
import yaml

from agent_swarm.codex.app_server import CodexAppServer
from agent_swarm.codex.context import CodexAdapterError
from conftest import FakeCodex, InstalledCommands, run_process
from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, select_runtime_adapter
from graphtraj.workspace.runner_project import runtime_executable
from runner_fixtures import configure_harness
from test_task_graph import _change_status, _register, _task

REASON = 'Error: listen EPERM: operation not permitted 127.0.0.1'
CONNECTIONS = {'version': 1, 'runtimes': {'dsh': {'runtime': 'dsh', 'providers': {'deepseek-official': {
    'api_key_env': 'DSH_421_KEY',
    'models': {'deepseek-flash': {'id': 'deepseek-flash', 'source': 'manual'}},
}}}}}


def install_failing_dsh(host_bin: Path, package: Path) -> Path:
    """Install a DSH as Homebrew lays it out, whose process exits before authentication."""
    entry = package / 'lib/bin.js'
    entry.parent.mkdir(parents=True)
    entry.write_text(f'#!/bin/sh\necho "{REASON}"\nexit 1\n')
    entry.chmod(0o755)
    (package / 'package.json').write_text('{"version": "0.2.2-alpha.2"}')
    host_bin.mkdir(parents=True, exist_ok=True)
    (host_bin / 'dsh').symlink_to(entry)
    return host_bin / 'dsh'


def test_graphtraj_dispatch_reports_why_dsh_did_not_start(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The Runner allocates a 0-byte Trace; the parent still gets the DSH process's reason."""
    root, _, _, env = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    host_bin = tmp_path / 'host-bin'
    install_failing_dsh(host_bin, tmp_path / 'dsh-package')
    env = {name: value for name, value in env.items() if not name.startswith('GRAPHTRAJ_')}
    env.update(PATH=str(host_bin) + os.pathsep + env['PATH'], DSH_421_KEY='dummy')
    (tmp_path / 'operator-home/.graphtraj').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'operator-home/.graphtraj/connections.yml').write_text(yaml.safe_dump(CONNECTIONS))
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'member': {'connection': 'dsh/deepseek-official/deepseek-flash', 'reports': ['report.md']}},
        'role_tree': {'member': {}},
    }))
    _register(installed_commands, root, _task('421', 'dsh-start-failure'))
    _change_status(installed_commands, root, '421', 'ready')
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': 'member', 'task_id': '421', 'instruction': 'unused'}]}))

    result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root, env=env)

    assert result.returncode == 1
    [task] = yaml.safe_load(result.stdout)['tasks']
    assert task['launch_status'] == 'failed'
    assert REASON in task['error']['message']
    [failure] = (root / '.graphtraj/runner/sessions').glob('*/launch-error.yml')
    document = yaml.safe_load(failure.read_text())
    assert document['code'] == 'RUNTIME_START_FAILED'
    assert REASON in document['message']
    # The member's core Agent, which a parent's status and notices read, has the same reason.
    [agent] = (root / '.graphtraj/swarm/control/agents').glob('*.json')
    [ended] = json.loads(agent.read_text())['executions']
    assert ended['error']['code'] == 'RUNTIME_START_FAILED'
    assert REASON in ended['error']['message']


def failing_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, close_failure: Exception) -> object:
    """Build a member whose process fails to start and whose closing up fails too."""
    from graphtraj.interfaces import hosted_cli
    from graphtraj.runtimes.dsh import execution

    class Service:
        """A DSH service that exits before authentication and then cannot be closed."""

        def __init__(self, executable: str, cwd: Path, environment: dict) -> None:
            """Keep nothing; the failure is all this service does."""
            self.process = None

        def start(self) -> None:
            """Fail as a DSH process that exited before authentication."""
            raise RuntimeAdapterError('RUNTIME_START_FAILED', REASON)

        def close(self) -> None:
            """Fail while closing up after the start failure."""
            raise close_failure

    monkeypatch.setenv('DSH_421_KEY', 'dummy')
    monkeypatch.setattr(execution, 'DshService', Service)
    monkeypatch.setattr(hosted_cli, 'cli_connection', lambda *args, **kwargs: nullcontext('/bound-channel'))
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    from graphtraj.configuration.project_configuration import default_configuration_content

    config.write_text(default_configuration_content(tmp_path, tmp_path))
    return select_runtime_adapter('dsh').managed_execution(
        {'executable': 'dsh', 'package': '/installed/dsh/package.json', 'tool': 'graphtraj-session',
         'worktree_path': str(tmp_path), 'harness_root': str(tmp_path), 'provider': 'deepseek-official',
         'model': 'deepseek-flash', 'reasoning_effort': 'low', 'api_key_env': 'DSH_421_KEY',
         'base_url': None, 'sandbox': 'workspace-write', 'instructions': '', 'reports': []},
        'unused', tmp_path, lambda session, pid: None, {},
        trace_file=tmp_path / 'trace.jsonl', expected_session=None,
        session_created=lambda session, pid: None,
    )


def test_a_failed_close_keeps_the_start_reason_and_the_unconfirmed_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent reads the start reason, learns the stop is unconfirmed, and the log keeps both."""
    close_failure = RuntimeAdapterError('RUNTIME_SHUTDOWN_FAILED', 'Owned DSH service did not stop.',
                                        terminal_confirmed=False)
    turn = failing_turn(tmp_path, monkeypatch, close_failure)

    with pytest.raises(RuntimeAdapterError) as caught:
        turn.run()

    assert (caught.value.code, caught.value.message) == ('RUNTIME_START_FAILED', REASON)
    assert caught.value.terminal_confirmed is False
    log = (tmp_path / 'stderr.log').read_text()
    assert REASON in log and 'Owned DSH service did not stop.' in log


def test_any_closing_failure_stays_behind_the_start_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected closing error neither replaces the reason nor claims the stop was unconfirmed."""
    turn = failing_turn(tmp_path, monkeypatch, OSError('log directory is gone'))

    with pytest.raises(RuntimeAdapterError) as caught:
        turn.run()

    assert (caught.value.code, caught.value.message) == ('RUNTIME_START_FAILED', REASON)
    assert caught.value.terminal_confirmed is True
    assert 'log directory is gone' in (tmp_path / 'stderr.log').read_text()


def test_codex_closing_failure_names_the_original_failure(tmp_path: Path) -> None:
    """A Codex service that will not exit stays unconfirmed, and its start reason still shows."""
    adapter = CodexAppServer(command=['unused'], cwd=tmp_path)

    async def close() -> None:
        """Fail as a service that did not exit after explicit close."""
        raise CodexAdapterError('RUNTIME_SHUTDOWN_FAILED', 'Codex service did not exit after explicit close.',
                                terminal_confirmed=False)

    adapter.close = close

    async def run() -> None:
        """Leave the service's context with a failed startup call in flight."""
        failure = CodexAdapterError('RUNTIME_START_FAILED', REASON)
        await adapter.__aexit__(type(failure), failure, None)

    with pytest.raises(CodexAdapterError) as caught:
        asyncio.run(run())

    assert caught.value.code == 'RUNTIME_SHUTDOWN_FAILED'
    assert REASON in caught.value.message
    assert caught.value.terminal_confirmed is False


@pytest.mark.parametrize('runtime', ['codex', 'pi'])
@pytest.mark.parametrize('layout', ['absent', 'dangling', 'not-executable'])
def test_an_unusable_runtime_executable_names_its_runtime(
    runtime: str, layout: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every refusal says which Runtime it is about, and no other."""
    other = {'codex': 'pi', 'pi': 'codex'}[runtime]
    found = tmp_path / runtime
    if layout == 'dangling':
        found.symlink_to(tmp_path / 'gone')
    elif layout == 'not-executable':
        found.write_text('')
        found.chmod(0o644)
    monkeypatch.setattr(shutil, 'which', lambda name: None if layout == 'absent' else str(found))

    with pytest.raises(RunnerError) as refused:
        runtime_executable(runtime)

    assert refused.value.code == 'RUNTIME_EXECUTABLE_INVALID'
    words = refused.value.message.lower().replace("'", ' ').replace('.', ' ').split()
    assert runtime in words and other not in words
