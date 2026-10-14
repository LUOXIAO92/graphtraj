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
from test_task_graph import _change_status, _register, _task


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
    if native:
        # Keep the real user's existing official login; only fixture peers use
        # configure_harness's disposable user home. Never copy credentials.
        environment['HOME'] = os.environ['HOME']
    environment['CLAUDE_FIXTURE_HOME'] = str(tmp_path)
    if os.environ.get('CLAUDE_CONFIG_DIR'):
        environment['CLAUDE_CONFIG_DIR'] = os.environ['CLAUDE_CONFIG_DIR']
    task = _task('320', 'claude-probe')
    task['body'] = BODY + 'Reply with only CLAUDE-RUNNER-320. Do not use tools.'
    _register(commands, root, task)
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
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
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

    integrated = run_process([str(installed_commands.product), 'task', 'integrate', '--task-id', '320',
                              '--', sys.executable, '-c', 'pass'], cwd=root, env=environment, timeout=30)
    assert integrated.returncode == 0, integrated.stdout + integrated.stderr
    cleanup = command(installed_commands, root, environment, 'cleanup', '--task-id', '320')
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
    """Confirm retained settlement or current stopping when old receipts are missing."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    # The peer receives cancellation but settles only after the five-second
    # read loop ends, while the original Worker drains and closes its pipes.
    environment['CLAUDE_FIXTURE_STOP_DELAY'] = '6'
    if not native_idle:
        environment['CLAUDE_FIXTURE_NO_SETTLE'] = '1'
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
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

    # Wait for the public observation that the original Worker released its
    # lock, then attempt confirmation once; no PID or error prose is used.
    deadline = time.monotonic() + 15
    while settled(installed_commands, root, environment, alias)['activity'] != 'abnormal':
        assert time.monotonic() < deadline
        time.sleep(0.1)
    if not native_idle:
        # A historical Worker did not retain these fields. Public control must
        # establish present stopping without inventing an old EOF/idle receipt.
        (directory / f"claude-termination-{status['execution_id']}.yml").unlink()
    response = command(installed_commands, root, environment, 'interrupt', alias)
    assert response.returncode == 0, response.stdout + response.stderr
    result = yaml.safe_load(response.stdout)
    member = result['members'][0]
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
        assert member['interrupt_status'] == 'stopped', result
        evidence = yaml.safe_load(Path(member['evidence']).read_text())['evidence']
        assert evidence['method'] == 'current-process-group'
        assert evidence['running_members'] == []
        assert settled(installed_commands, root, environment, alias)['activity'] == 'idle'
        assert (directory / 'execution.yml').read_bytes() == original
        receipt = Path(member['evidence'])
        retained = receipt.read_bytes()
        assert yaml.safe_load(retained)['original_execution']['terminal_confirmed'] is False
        budget_file = root / '.graphtraj/state/tasks/320-claude-probe/execution-budget.yml'
        budget = yaml.safe_load(budget_file.read_text())
        # No new spending, reviewer, interactive prompt or replacement Session.
        recovered = command(
            installed_commands, root, environment, 'recover', alias,
            '--reason', 'Current native group stopping was verified',
            '--instruction', 'Complete the authorized original task',
            '--allowed-scope', 'Same Session fixture continuation',
            '--forbidden-scope', 'No new time or replacement',
            '--caused-by-event-id', events(root)[-1]['event_id'],
        )
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert yaml.safe_load(recovered.stdout)['recovery_status'] == 'resumed'
        resumed = settled(installed_commands, root, environment, alias)
        assert resumed['session'] == status['session']
        assert resumed['execution_id'] != status['execution_id']
        assert receipt.read_bytes() == retained
        after = yaml.safe_load(budget_file.read_text())
        for key in ('started_at', 'allowance_minutes', 'approved_minutes', 'sessions'):
            assert after.get(key) == budget.get(key)


@pytest.mark.parametrize('connection_role', [False, True])
def test_recovery_refreshes_only_original_role_read_paths(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    connection_role: bool,
) -> None:
    """Later explicit grants reach resumed CLI policy without replacing captured settings."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    role_file = root / '.graphtraj/roles.yml'
    original = yaml.safe_load(role_file.read_text())['roles']['researcher']
    if connection_role:
        # Only the disposable fixture HOME owns this catalog, never the user.
        catalog = Path(environment['HOME']) / '.graphtraj/connections.yml'
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(yaml.safe_dump({'version': 1, 'runtimes': {'claude': {
            'runtime': 'claude', 'providers': {'anthropic': {'models': {'opus-5_5': {
                'id': 'claude-opus-5-5', 'source': 'manual', 'supported_efforts': ['high'],
            }}}},
        }}}))
        original = {key: value for key, value in original.items() if key not in {'runtime', 'model'}}
        original['connection'] = 'claude/anthropic/opus-5_5'
    roles = {'roles': {'original_team': {'researcher': original},
                      'other_team': {'researcher': dict(original)}},
             'role_tree': {'original_team.researcher': {}, 'other_team.researcher': {}}}
    role_file.write_text(yaml.safe_dump(roles))
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'original_team.researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    first = settled(installed_commands, root, environment, alias)
    directory = root / '.graphtraj/runner/sessions' / alias
    captured = yaml.safe_load((directory / 'launch.yml').read_text())['adapter_request']
    if connection_role:
        assert captured['runtime'] == 'claude'
        assert captured['connection'] == 'claude/anthropic/opus-5_5'
        # Resumption must use captured connection settings, not this catalog.
        catalog.unlink()
    stopped = command(installed_commands, root, environment, 'interrupt', alias)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr

    resources = [root / 'approved/bin', root / 'approved/lib']
    for path in resources:
        path.mkdir(parents=True)
        (path / 'resource.txt').write_text('Explicit read-only resource\n')
    roles['roles']['original_team']['researcher'] = {
        **original, 'reasoning_effort': 'max',
        **({} if connection_role else {'model': 'later-model', 'base_url': 'https://later.invalid/v1'}),
        'claude': {'read_paths': list(map(str, resources)), 'permission_mode': 'auto'},
    }
    roles['roles']['other_team']['researcher']['claude'] = {'read_paths': [str(root / 'unrelated')]}
    role_file.write_text(yaml.safe_dump(roles))
    recovered = command(
        installed_commands, root, environment, 'recover', alias,
        '--reason', 'Apply later authorized read resources', '--instruction', 'Report resource configuration',
        '--allowed-scope', 'Read only explicitly authorized resources',
        '--forbidden-scope', 'No changes to model, connection, or other permissions',
        '--caused-by-event-id', events(root)[-1]['event_id'],
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert yaml.safe_load(recovered.stdout)['recovery_status'] == 'resumed'
    assert settled(installed_commands, root, environment, alias)['session'] == first['session']
    resumed = yaml.safe_load((directory / 'resume.yml').read_text())['adapter_request']
    assert resumed == {**captured, 'resources': list(map(str, resources))}
    native = json.loads((root / 'native-permissions.json').read_text())['settings']
    filesystem = native['sandbox']['filesystem']
    for path in resources:
        assert str(path.resolve()) in filesystem['allowRead']
        assert str(path.resolve()) in filesystem['denyWrite']
        assert str(path.resolve()) not in filesystem['allowWrite']
        assert str(path.resolve()) not in native['permissions']['additionalDirectories']
        assert f'Edit(/{path.resolve()}/**)' in native['permissions']['deny']
    assert str(root / 'unrelated') not in filesystem['allowRead']

    # A later role change still cannot expose private control/state paths.
    roles['roles']['original_team']['researcher']['claude']['read_paths'] = [str(root / '.graphtraj/state')]
    role_file.write_text(yaml.safe_dump(roles))
    refused = command(installed_commands, root, environment, 'send', alias,
                      '--instruction', 'Do not start with private resource access',
                      '--caused-by-event-id', events(root)[-1]['event_id'])
    assert refused.returncode != 0
    assert yaml.safe_load(refused.stdout)['error']['code'] == 'invalid-config'
    assert yaml.safe_load((directory / 'resume.yml').read_text())['adapter_request'] == resumed


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
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
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


@pytest.mark.skipif(not os.environ.get('CLAUDE_REAL_TEST_BINARY'), reason='Explicit real CLI probe only')
def test_real_claude_archive_public_query(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Collect a real Runner call and read its archive through the public gateway."""
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request

    root, environment = setup(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, os.environ['CLAUDE_REAL_TEST_BINARY'])
    batch = root / 'archive-probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    result = command(installed_commands, root, environment, '--swarm-input', str(batch))
    print('REAL_CLAUDE_321_HARNESS=' + str(root))
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    terminal = settled(installed_commands, root, environment, task['alias'])
    print(json.dumps(terminal))
    # The real Runner has already established this mapping. This test selects
    # that existing owner at the public host seam, without creating identity.
    with runtime_caller(root / '.graphtraj/runner', task['alias']):
        result = handle_request({'action': 'execute', 'feature': 'session_read',
                                 'arguments': {'session_id': 'claude:' + terminal['session']}}, cwd=root)
    data = result.document
    assert data['header']['graphtraj']['native']['sessionId'] == terminal['session']
    assert any(e.get('data', {}).get('record', {}).get('type') == 'result' for e in data['events'])
    print('REAL_CLAUDE_321_QUERY=' + json.dumps(data, ensure_ascii=False))
    assert terminal['last_outcome'] == 'completed', terminal
