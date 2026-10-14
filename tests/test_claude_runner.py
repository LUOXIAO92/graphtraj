"""Claude lifecycle through installed Setup and Runner commands."""
import json
import os
from pathlib import Path
import shutil
import time

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_task_recovery import installed_commands, events
from test_task_budget_control import BODY
from test_ticket_graph import _change_status, _register, _ticket


def setup(
    commands: InstalledCommands,
    repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    native: str | None = None,
) -> tuple[Path, dict]:
    """Create a disposable Harness using Setup; configure its explicit test role."""
    root, _, _, environment = configure_harness(commands, repository, fake_codex, tmp_path)
    binary = fake_codex.executable.with_name('claude')
    if native:
        binary.symlink_to(native)
    else:
        import sys

        binary.write_text(f'#!{sys.executable}\n' + Path(__file__).with_name('claude_cli_fixture.py').read_text())
        binary.chmod(0o755)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'claude', 'model': 'claude-opus-5-5',
                                 'reasoning_effort': 'high', 'reports': ['evidence.md']}},
        'role_tree': {'researcher': {}},
    }))
    environment['CLAUDE_FIXTURE_HOME'] = str(tmp_path)
    if os.environ.get('CLAUDE_CONFIG_DIR'):
        environment['CLAUDE_CONFIG_DIR'] = os.environ['CLAUDE_CONFIG_DIR']
    ticket = _ticket('320', 'claude-probe')
    ticket['body'] = BODY + 'Reply with only CLAUDE-RUNNER-320. Do not use tools.'
    _register(commands, root, ticket)
    _change_status(commands, root, '320', 'ready')
    return root, environment


def command(commands: InstalledCommands, root: Path, environment: dict, *args: str):
    """Invoke the public installed Runner with a finite command timeout."""
    return run_process([str(commands.runner), *args], cwd=root, env=environment, timeout=65)


def settled(commands: InstalledCommands, root: Path, environment: dict, alias: str) -> dict:
    """Observe one current execution until its native process has settled."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = command(commands, root, environment, 'status', alias)
        assert result.returncode == 0, result.stdout + result.stderr
        value = yaml.safe_load(result.stdout)['aliases'][0]
        if value['activity'] != 'running':
            return value
        time.sleep(0.1)
    raise AssertionError('Runner did not report settlement within 30 seconds')


def test_claude_public_launch_resume_interrupt(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Run registration, continuation and actual peer termination through Runner."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '320', 'role': 'researcher'}]}))
    result = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    alias = task['alias']
    first = settled(installed_commands, root, environment, alias)
    assert first['last_outcome'] == 'completed'
    delivered = command(installed_commands, root, environment, 'send', alias, '--instruction', 'deliver',
                        '--caused-by-event-id', events(root)[-1]['event_id'])
    assert delivered.returncode == 0, delivered.stdout + delivered.stderr
    assert settled(installed_commands, root, environment, alias)['last_outcome'] == 'completed'
    follow = command(installed_commands, root, environment, 'send', alias, '--instruction', 'wait-public',
                     '--caused-by-event-id', events(root)[-1]['event_id'])
    assert follow.returncode == 0, follow.stdout + follow.stderr
    stopped = command(installed_commands, root, environment, 'interrupt', alias)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    second = settled(installed_commands, root, environment, alias)
    assert second['last_outcome'] == 'interrupted'
    assert second['session'] == first['session']
    assert second['execution_id'] != first['execution_id']

    reports = command(installed_commands, root, environment, 'reports', alias)
    submission = yaml.safe_load(reports.stdout)['submissions'][-1]
    accepted = command(installed_commands, root, environment, 'decide-result',
                       '--submission-id', submission['event_id'], '--commit', submission['candidate'],
                       '--decision', 'accepted', '--reason', 'Controlled result verified',
                       '--evidence-ref', submission['evidence_refs'][0])
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    import sys

    integrated = run_process([str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '320',
                              '--', sys.executable, '-c', 'pass'], cwd=root, env=environment, timeout=30)
    assert integrated.returncode == 0, integrated.stdout + integrated.stderr
    cleanup = command(installed_commands, root, environment, 'cleanup', '--ticket-id', '320')
    assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr
    assert yaml.safe_load(cleanup.stdout)['cleanup_status'] == 'cleaned'
    assert not Path(task['worktree_path']).exists()


@pytest.mark.parametrize('native_idle', [True, False])
def test_claude_public_interrupt_rechecks_drained_termination(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    native_idle: bool,
) -> None:
    """Late native settlement can be confirmed; pipe exit alone cannot be."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    # The peer receives cancellation but settles only after the five-second
    # read loop ends, while the original Worker drains and closes its pipes.
    environment['CLAUDE_FIXTURE_STOP_DELAY'] = '6'
    if not native_idle:
        environment['CLAUDE_FIXTURE_NO_SETTLE'] = '1'
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    settled(installed_commands, root, environment, alias)
    sent = command(installed_commands, root, environment, 'send', alias, '--instruction', 'wait-late-idle',
                   '--caused-by-event-id', events(root)[-1]['event_id'])
    assert sent.returncode == 0, sent.stdout + sent.stderr
    command(installed_commands, root, environment, 'interrupt', alias)
    status = settled(installed_commands, root, environment, alias)
    assert status['activity'] in {'abnormal', 'unreachable'}
    assert status['terminal_confirmed'] is False
    directory = root / '.graphtraj/runner/sessions' / alias
    original = (directory / 'execution.yml').read_bytes()
    reports = command(installed_commands, root, environment, 'reports', alias)
    assert reports.returncode == 0, reports.stdout + reports.stderr
    assert yaml.safe_load(reports.stdout)['execution']['terminal_confirmed'] is False

    # Confirmation is forbidden while that same Worker still owns its lock.
    # Poll the public interrupt until its owner has returned; no PID is used.
    deadline = time.monotonic() + 15
    while True:
        response = command(installed_commands, root, environment, 'interrupt', alias)
        assert response.returncode == 0, response.stdout + response.stderr
        result = yaml.safe_load(response.stdout)
        member = result['members'][0]
        if member.get('error', {}).get('message', '').startswith('The original Worker'):
            assert time.monotonic() < deadline
            time.sleep(0.1)
            continue
        break
    assert (directory / 'execution.yml').read_bytes() == original
    if native_idle:
        assert member['interrupt_status'] == 'stopped', result
        assert settled(installed_commands, root, environment, alias)['activity'] == 'idle'
        confirmation = Path(member['evidence']).read_bytes()
        retained = command(installed_commands, root, environment, 'reports', alias)
        report = yaml.safe_load(retained.stdout)
        assert report['execution']['terminal_confirmed'] is False
        assert report['termination_confirmation']['evidence']['native_idle'] is True
        again = command(installed_commands, root, environment, 'interrupt', alias)
        assert yaml.safe_load(again.stdout)['interrupt_status'] == 'interrupted'
        assert Path(member['evidence']).read_bytes() == confirmation
        denied = command(installed_commands, root, environment, 'send', alias, '--instruction', 'continue',
                         '--caused-by-event-id', events(root)[-1]['event_id'])
        assert denied.returncode != 0
        assert 'subtree-stopped' in denied.stdout + denied.stderr
        retired = command(installed_commands, root, environment, 'retire', alias)
        assert retired.returncode == 0, retired.stdout + retired.stderr
        assert settled(installed_commands, root, environment, alias)['activity'] == 'idle'
    else:
        assert member['interrupt_status'] == 'unconfirmed'
        assert 'native_idle' in member['error']['message']
        assert settled(installed_commands, root, environment, alias)['activity'] == 'abnormal'
        # Model the supported historical record, which stored only the merged
        # false outcome and no separate native/process/pipe observations.
        (directory / f"claude-termination-{status['execution_id']}.yml").unlink()
        legacy = command(installed_commands, root, environment, 'interrupt', alias)
        missing = yaml.safe_load(legacy.stdout)['members'][0]
        assert missing['interrupt_status'] == 'unconfirmed'
        assert 'process_group_closed, stdout_eof, stderr_eof, pipes_closed, native_idle' in missing['error']['message']
        assert (directory / 'execution.yml').read_bytes() == original


@pytest.mark.skipif(not os.environ.get('CLAUDE_REAL_TEST_BINARY'), reason='Explicit real CLI probe only')
def test_real_claude_public_runner_startup(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Retain actual startup evidence; authentication failure is never success."""
    native = os.environ['CLAUDE_REAL_TEST_BINARY']
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path, native)
    batch = root / 'real-probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '320', 'role': 'researcher'}]}))
    result = command(installed_commands, root, environment, '--swarm-input', str(batch))
    print('REAL_CLAUDE_HARNESS=' + str(root))
    print(result.stdout)
    print(result.stderr)
    document = yaml.safe_load(result.stdout)
    assert result.returncode == 0, document
    task = document['tasks'][0]
    terminal = settled(installed_commands, root, environment, task['alias'])
    print(json.dumps(terminal))
    assert terminal['last_outcome'] == 'completed', terminal
