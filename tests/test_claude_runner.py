"""Claude lifecycle through installed Setup and Runner commands."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
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
    request: str = 'Reply with only CLAUDE-RUNNER-320. Do not use tools.',
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
    task['body'] = BODY + request
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


def test_child_registration_follows_its_owning_execution(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Only the completed registering execution starts its children.

    A registration left by a failed execution does not block the original
    Session's next one, and an unattributed one is reported, never replayed,
    until interruption withdraws it.
    """
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['helper'] = {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'high'}
    roles['role_tree'] = {'researcher': {'helper': {}}}
    roles_file.write_text(yaml.safe_dump(roles))
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    first = settled(installed_commands, root, environment, alias)
    sessions = root / '.graphtraj/runner/sessions'
    registration = sessions / alias / 'child-registration.yml'
    history = tmp_path / (first['session'].split(':')[-1] + '.json')
    trace, = (root / '.graphtraj/state').glob(f'**/traces/{alias}/events.jsonl')

    def send(instruction: str) -> dict:
        """Continue the original Session and observe its settled execution."""
        sent = command(installed_commands, root, environment, 'send', alias, '--instruction', instruction,
                       '--caused-by-event-id', events(root)[-1]['event_id'])
        assert sent.returncode == 0, sent.stdout + sent.stderr
        return settled(installed_commands, root, environment, alias)

    def helpers() -> list[Path]:
        """Return the helper Sessions Runner has started."""
        return [path for path in sessions.iterdir() if 'helper' in path.name]

    def withdrawn() -> list[dict]:
        """Return the registrations retained as withdrawn in the Session events."""
        records = [json.loads(line) for line in (sessions / alias / 'events.jsonl').read_text().splitlines()]
        return [record['registration'] for record in records
                if record.get('type') == 'runner-child-registration-withdrawn']

    def last_tool_result() -> dict:
        """Read the swarm outcome the native peer answered with in its Trace."""
        results = [json.loads(line) for line in trace.read_text().splitlines()
                   if json.loads(line).get('type') == 'assistant']
        return json.loads(results[-1]['message']['content'][0]['text'])

    failed = send('register-error')
    assert failed['last_outcome'] == 'runtime-error'
    stale = yaml.safe_load(registration.read_text())
    assert stale['execution_id'] == failed['execution_id']
    assert helpers() == []

    resumed = send('register')
    assert resumed['execution_id'] != failed['execution_id']
    assert not last_tool_result()['isError']
    assert withdrawn() == [stale]
    deadline = time.monotonic() + 60
    while not any('Direct child execution results' in text for text in json.loads(history.read_text())):
        assert time.monotonic() < deadline, 'registered child results never reached the parent'
        time.sleep(0.1)
    assert settled(installed_commands, root, environment, alias)['last_outcome'] == 'completed'
    assert len(helpers()) == 1 and not registration.exists()

    # A registration written before ownership was recorded names no execution.
    legacy = {key: value for key, value in stale.items() if key != 'execution_id'}
    registration.write_text(yaml.safe_dump(legacy))
    assert send('register')['last_outcome'] == 'completed'
    refused = last_tool_result()
    # MCP reports the message alone; it names the exact unattributed record.
    refusal = refused['content'][0]['text']
    assert refused['isError']
    assert str(registration) in refusal and legacy['retained_batch_file'] in refusal
    assert yaml.safe_load(registration.read_text()) == legacy
    assert len(helpers()) == 1
    stopped = command(installed_commands, root, environment, 'interrupt', alias)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not registration.exists() and withdrawn() == [stale, legacy]
    assert len(helpers()) == 1


def test_stopped_child_is_reported_as_stopped(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A child interrupted through a recorded stop is not a retryable failure."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['helper'] = {'runtime': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'high'}
    roles['role_tree'] = {'researcher': {'helper': {}}}
    roles_file.write_text(yaml.safe_dump(roles))
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    first = settled(installed_commands, root, environment, alias)
    history = tmp_path / (first['session'].split(':')[-1] + '.json')
    sessions = root / '.graphtraj/runner/sessions'
    environment['CLAUDE_FIXTURE_HOLD_FILE'] = str(tmp_path / 'hold')
    (tmp_path / 'hold').touch()
    sent = command(installed_commands, root, environment, 'send', alias, '--instruction', 'register',
                   '--caused-by-event-id', events(root)[-1]['event_id'])
    assert sent.returncode == 0, sent.stdout + sent.stderr
    deadline = time.monotonic() + 30
    while not [path for path in sessions.iterdir() if 'helper' in path.name and (path / 'mapping.yml').exists()]:
        assert time.monotonic() < deadline, 'the registered child never started'
        time.sleep(0.1)
    helper, = [path.name for path in sessions.iterdir() if 'helper' in path.name]
    while yaml.safe_load(command(installed_commands, root, environment, 'status', helper).stdout)['aliases'][0]['activity'] != 'running':
        assert time.monotonic() < deadline, 'the registered child never ran'
        time.sleep(0.1)
    stopped = command(installed_commands, root, environment, 'interrupt', helper)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    while not any('Direct child execution results' in text for text in json.loads(history.read_text())):
        assert time.monotonic() < deadline + 30, 'the stopped child result never reached the parent'
        time.sleep(0.1)
    notice = next(text for text in json.loads(history.read_text()) if 'Direct child execution results' in text)
    child = yaml.safe_load(notice.split('\n', 1)[1])['tasks'][0]
    assert child['launch_status'] == 'stopped'
    assert child['error']['code'] == 'subtree-stopped'


def test_public_interrupt_reconfirms_an_undrained_worker(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A Worker whose pipes stay open reports unconfirmed; the public interrupt rechecks the group."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    environment['CLAUDE_FIXTURE_NO_SETTLE'] = '1'
    escaped = tmp_path / 'escaped.pid'
    environment['CLAUDE_FIXTURE_ESCAPED_PIPE'] = str(escaped)
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
    deadline = time.monotonic() + 45
    while (status := settled(installed_commands, root, environment, alias))['activity'] != 'abnormal':
        assert time.monotonic() < deadline, status
        time.sleep(0.1)
    assert status['terminal_confirmed'] is False
    directory = root / '.graphtraj/runner/sessions' / alias
    evidence = yaml.safe_load((directory / f"claude-termination-{status['execution_id']}.yml").read_text())
    assert evidence['pipes_closed'] is False
    # The owned group cannot see the escaped child, so recheck only after it
    # is released and has ended: retained unconfirmed, confirmed later.
    pid = int(escaped.read_text())
    escaped.with_name(escaped.name + '.release').touch()
    released = time.monotonic() + 10
    try:
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            assert time.monotonic() < released, 'the released child never ended'
            time.sleep(0.1)
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    response = command(installed_commands, root, environment, 'interrupt', alias)
    assert response.returncode == 0, response.stdout + response.stderr
    member = yaml.safe_load(response.stdout)['members'][0]
    assert member['interrupt_status'] == 'stopped', response.stdout
    receipt = yaml.safe_load(Path(member['evidence']).read_text())
    assert receipt['evidence']['method'] == 'current-process-group'
    assert receipt['evidence']['running_members'] == []
    assert receipt['original_execution']['terminal_confirmed'] is False
    assert settled(installed_commands, root, environment, alias)['activity'] == 'idle'


@pytest.mark.parametrize('native_idle', [True, False])
def test_claude_interrupt_confirms_a_killed_unsettled_runtime(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    native_idle: bool,
) -> None:
    """A runtime killed after its stop window is terminated, interrupted and recoverable."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    # The peer receives cancellation but settles only after the five-second
    # read loop ends, while the original Worker drains and closes its pipes.
    environment['CLAUDE_FIXTURE_STOP_DELAY'] = '6'
    if not native_idle:
        environment['CLAUDE_FIXTURE_NO_SETTLE'] = '1'
    # Like the observed runs (exit 143), the CLI ignores stdin closure and is
    # stopped by SIGTERM, so the Worker's close outlasts 10 seconds.
    environment['CLAUDE_FIXTURE_HOLD_ON_EOF'] = '1'
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    settled(installed_commands, root, environment, alias)
    sent = command(installed_commands, root, environment, 'send', alias, '--instruction', 'wait-late-idle',
                   '--caused-by-event-id', events(root)[-1]['event_id'])
    assert sent.returncode == 0, sent.stdout + sent.stderr
    first = command(installed_commands, root, environment, 'interrupt', alias)
    # The Worker's close outlasts the ordinary 10-second control deadline, yet
    # the first interrupt receives its confirmed result.
    assert first.returncode == 0, first.stdout + first.stderr
    assert yaml.safe_load(first.stdout)['members'][0]['interrupt_status'] == 'interrupted', first.stdout
    # The peer settles too late (or never) and is killed after its stop
    # window: its exit and closed group confirm termination directly, while
    # the retained native observation stays as it was.
    status = settled(installed_commands, root, environment, alias)
    assert status['activity'] == 'idle', status
    directory = root / '.graphtraj/runner/sessions' / alias
    execution = yaml.safe_load((directory / 'execution.yml').read_text())
    assert execution['outcome'] == 'interrupted' and execution['terminal_confirmed'] is True
    evidence = yaml.safe_load((directory / f"claude-termination-{status['execution_id']}.yml").read_text())
    assert evidence['process_group_closed'] is True and evidence['pipes_closed'] is True
    assert evidence['native_idle'] is native_idle and evidence['runtime_exit_code'] == -15
    assert not (directory / f"terminal-confirmation-{status['execution_id']}.yml").exists()
    budget_file = root / '.graphtraj/state/tasks/320-claude-probe/execution-budget.yml'
    budget = yaml.safe_load(budget_file.read_text())
    # No second interrupt, new spending, reviewer or replacement Session.
    recovered = command(
        installed_commands, root, environment, 'recover', alias,
        '--reason', 'Native group stopping was confirmed at close',
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
def test_real_claude_input_echo_order(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Record where Claude echoes input delivered while a permission request waits.

    Only record kinds, states, identities and marker presence are printed;
    the probe judges nothing and always interrupts its own Session.
    """
    root, environment = setup(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
        os.environ['CLAUDE_REAL_TEST_BINARY'],
        'Use the Write tool to create probe-325.txt containing PROBE-325, then reply with only DONE-325.',
    )
    batch = root / 'echo-probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    print('REAL_CLAUDE_325_HARNESS=' + str(root))
    sessions = root / '.graphtraj/runner/sessions'
    alias = None
    trace = None

    def records() -> list[dict]:
        """Read the retained native records in arrival order."""
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace else []

    def wait(condition, seconds: float) -> bool:
        """Poll an observation without treating timeout as evidence."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.2)
        return False

    def pending() -> list[dict]:
        """Read the public pending native requests of this Session."""
        listed = command(installed_commands, root, environment, 'requests', alias)
        assert listed.returncode == 0, listed.stdout + listed.stderr
        return yaml.safe_load(listed.stdout)['requests']

    marks = {}
    launch_log = (tmp_path / 'swarm.log').open('w', encoding='utf-8')
    # The root launch keeps its reader alive through the first execution,
    # which waits on the permission request this probe must answer.
    launched = None
    try:
        launched = subprocess.Popen([str(installed_commands.runner), '--swarm-input', str(batch)],
                                    cwd=root, env=environment, text=True,
                                    stdout=launch_log, stderr=subprocess.STDOUT)
        assert wait(lambda: any((path / 'mapping.yml').is_file() for path in sessions.glob('320-*')), 120), \
            'no Session mapping'
        alias, = [path.name for path in sessions.glob('320-*') if (path / 'mapping.yml').is_file()]
        trace, = (root / '.graphtraj/state').glob(f'**/traces/{alias}/events.jsonl')
        assert wait(lambda: bool(pending()), 180), 'no native permission request'
        request = pending()[0]
        marks['request_method'] = request['method']
        marks['before_send_2'] = len(records())
        sent = command(installed_commands, root, environment, 'send', alias, '--instruction',
                       'MARK-325-SECOND: after the file step also reply with SECOND-325.',
                       '--caused-by-event-id', events(root)[-1]['event_id'])
        assert sent.returncode == 0, sent.stdout + sent.stderr
        marks['after_send_2'] = len(records())
        time.sleep(5)
        marks['before_reply'] = len(records())
        request_file = tmp_path / 'probe-request.yml'
        request_file.write_text(yaml.safe_dump(request))
        replied = command(installed_commands, root, environment, 'reply', alias,
                          '--request-file', str(request_file), '--response', json.dumps({'behavior': 'allow'}))
        assert replied.returncode == 0, replied.stdout + replied.stderr
        marks['after_reply'] = len(records())
        wait(lambda: any(record.get('type') == 'result' for record in records()[marks['before_reply']:]), 240)
        time.sleep(20)
    finally:
        retained = records()
        summary = [{
            'line': index, 'type': record.get('type'), 'subtype': record.get('subtype'),
            'state': record.get('state'), 'isReplay': record.get('isReplay'),
            'uuid': record.get('uuid'), 'parent_tool_use_id': record.get('parent_tool_use_id'),
            'tool_result': '"tool_result"' in json.dumps(record),
            'mark_1': 'probe-325.txt' in json.dumps(record),
            'mark_2': 'MARK-325-SECOND' in json.dumps(record),
            'keys': sorted(record),
        } for index, record in enumerate(retained) if record.get('type') != 'stream_event']
        print('REAL_CLAUDE_325_ALIAS=' + str(alias))
        print('REAL_CLAUDE_325_MARKS=' + json.dumps(marks))
        print('REAL_CLAUDE_325_ORDER=' + json.dumps(summary))
        if alias is not None:
            print('REAL_CLAUDE_325_STATUS=' + command(installed_commands, root, environment, 'status', alias).stdout)
            stopped = command(installed_commands, root, environment, 'interrupt', alias)
            print('REAL_CLAUDE_325_INTERRUPT=' + stopped.stdout + stopped.stderr)
        if launched is not None:
            try:
                print('REAL_CLAUDE_325_SWARM_EXIT=' + str(launched.wait(timeout=60)))
            except subprocess.TimeoutExpired:
                # An unconfirmed process is reported, never signalled here.
                print('REAL_CLAUDE_325_SWARM_STILL_RUNNING pid=' + str(launched.pid))
        launch_log.close()
        print('REAL_CLAUDE_325_SWARM_OUTPUT=' + (tmp_path / 'swarm.log').read_text())


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


def test_public_interrupt_confirms_an_exited_owner_without_terminal_record(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """An owner and Runtime that both exited are confirmed stopped, not natively ended."""
    from graphtraj.execution.runner_heartbeat import ownership_is_held

    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    settled(installed_commands, root, environment, alias)
    sent = command(installed_commands, root, environment, 'send', alias, '--instruction', 'wait',
                   '--caused-by-event-id', events(root)[-1]['event_id'])
    assert sent.returncode == 0, sent.stdout + sent.stderr
    directory = root / '.graphtraj/runner/sessions' / alias
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())

    # Both recorded processes end without any terminal record.
    os.killpg(mapping['runtime_pid'], signal.SIGKILL)
    os.kill(mapping['worker_pid'], signal.SIGKILL)
    deadline = time.monotonic() + 15
    while ownership_is_held(directory, mapping['worker_pid']):
        assert time.monotonic() < deadline, 'the killed owner still holds its lock'
        time.sleep(0.02)
    for leftover in directory.glob('control-*'):
        shutil.rmtree(leftover, ignore_errors=True)
    assert not (directory / 'execution.yml').exists()

    response = command(installed_commands, root, environment, 'interrupt', alias)
    assert response.returncode == 0, response.stdout + response.stderr
    member = yaml.safe_load(response.stdout)['members'][0]
    assert member['interrupt_status'] == 'stopped', response.stdout

    # The owner exit stays an unconfirmed runtime error; the separate receipt
    # records only the current confirmation that the Runtime group is gone.
    execution = yaml.safe_load((directory / 'execution.yml').read_text())
    assert execution['outcome'] == 'runtime-error'
    assert execution['terminal_confirmed'] is False
    assert execution['error']['code'] == 'owner-exited'
    assert execution['execution_id'] == mapping['execution_id']
    receipt = yaml.safe_load((directory / f"terminal-confirmation-{mapping['execution_id']}.yml").read_text())
    assert receipt['terminal_confirmed'] is True
    assert receipt['original_execution'] == execution
    assert receipt['evidence']['running_members'] == []
    status = settled(installed_commands, root, environment, alias)
    assert status['activity'] == 'idle', status
    assert status['last_outcome'] == 'runtime-error'

    # The confirmed stop is the replacement precondition; authority is unchanged.
    replaced = command(installed_commands, root, environment, 'replace', alias,
                       '--caused-by-event-id', events(root)[-1]['event_id'])
    assert 'replacement-not-stopped' not in replaced.stdout + replaced.stderr
    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    assert yaml.safe_load(replaced.stdout)['replacement_alias'] != alias


def test_startup_hook_reply_does_not_wait_for_another_startup(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Another process holding the project startup lock must not delay the hook reply."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    log = tmp_path / 'hook-replies.log'
    environment.update(CLAUDE_FIXTURE_START_LOCK=str(root / '.graphtraj/runner/execution-start.lock'),
                       CLAUDE_FIXTURE_START_LOCK_SECONDS='4', CLAUDE_FIXTURE_HOOK_LOG=str(log))
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    result = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert result.returncode == 0, result.stdout + result.stderr
    alias = yaml.safe_load(result.stdout)['tasks'][0]['alias']
    assert settled(installed_commands, root, environment, alias)['last_outcome'] == 'completed'
    assert Path(str(root / '.graphtraj/runner/execution-start.lock') + '.held').exists()
    assert float(log.read_text().split()[0]) < 2


def test_stop_published_during_startup_refuses_the_first_turn(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A public interrupt between process start and the startup hook still stops the turn."""
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    gate = tmp_path / 'hook-gate'
    log = tmp_path / 'hook-replies.log'
    environment.update(CLAUDE_FIXTURE_HOOK_GATE=str(gate), CLAUDE_FIXTURE_HOOK_LOG=str(log))
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launch = subprocess.Popen([str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root,
                              env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 30
    while not Path(str(gate) + '.waiting').exists():
        assert time.monotonic() < deadline and launch.poll() is None
        time.sleep(0.05)
    alias = next(path.name for path in (root / '.graphtraj/runner/sessions').iterdir() if path.is_dir())
    stopping = subprocess.Popen([str(installed_commands.runner), 'interrupt', alias], cwd=root,
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The interrupt publishes its stop before addressing the execution; the
    # held hook is then released so this execution reaches Session binding.
    time.sleep(1)
    gate.touch()
    stdout, stderr = stopping.communicate(timeout=60)
    launched, launch_error = launch.communicate(timeout=60)
    assert stopping.returncode == 0, stdout + stderr
    assert launch.returncode != 0
    assert 'subtree-stopped' in launched + launch_error
    assert not log.exists()
