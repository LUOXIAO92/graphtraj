"""Task budgets use actual ownership and stop real native executions."""

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process, wait_for_file
from graphtraj.execution import execution_budget as budgets
from runner_fixtures import configure_harness
from test_ticket_integration import accepted_ticket
from test_ticket_graph import _change_status, _register, _ticket


BODY = '''---
difficulty: medium
difficulty_reason: Research and evidence
execution_budget:
  estimated_minutes: {research: 9, total: 10}
  planned_sessions: {researcher: 1}
  correction_rounds: 1
  estimation_note: One actual author
  on_exceed: Notify the parent
---
'''


@pytest.fixture
def commands(request: pytest.FixtureRequest) -> InstalledCommands:
    """Use an explicitly supplied candidate installation or the suite wheel."""
    candidate = os.environ.get('TICKET153_CANDIDATE_BIN')
    if candidate:
        return InstalledCommands(Path(candidate) / 'graphtraj', Path(candidate) / 'agent-runner')
    from conftest import _install_commands
    directory = request.getfixturevalue('tmp_path_factory').mktemp('budget-candidate')
    return _install_commands(directory / 'venv', request.getfixturevalue('built_wheel'))


@pytest.fixture
def installed_commands(commands: InstalledCommands) -> InstalledCommands:
    """Share the same candidate with the accepted integration input fixture."""
    return commands


def monitor_at(path: Path) -> budgets.ExecutionBudgetMonitor:
    """Create a registered task budget without any programming seats."""
    path.mkdir()
    (path / 'ticket.yml').write_text('current_definition: ticket.md\n')
    (path / 'ticket.md').write_text(BODY)
    return budgets.execution_budget_monitor(path, '153', 'research')


def sample_stop(monitor: budgets.ExecutionBudgetMonitor, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Advance the existing budget clock and force the existing stochastic draw."""
    before = yaml.safe_load((monitor.ticket_directory / 'execution-budget.yml').read_text())
    with monkeypatch.context() as patch:
        patch.setattr(budgets.time, 'time', lambda: before['started_at'] + 20 * 60)
        patch.setattr(budgets.random, 'random', lambda: .999)
        assert monitor.check('researcher', 'researcher')
    return before


def test_budget_accepts_actual_work_and_keeps_allowance_across_roles_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renaming or resuming a participant never creates a fresh Ticket allowance."""
    monitor = monitor_at(tmp_path / 'ticket')
    monitor.record_session('researcher', 'researcher')
    before = sample_stop(monitor, monkeypatch)
    monitor.record_session('analyst', 'analyst')
    monitor.continue_after_stop()
    after = yaml.safe_load((monitor.ticket_directory / 'execution-budget.yml').read_text())
    assert after['sessions'] == {'researcher': 1, 'analyst': 1}
    for field in ('started_at', 'allowance_minutes'):
        assert after[field] == before[field]
    assert after['stopping_checks'] > before['stopping_checks']
    assert not after['stopped']
    assert len(after['parent_notices']) == 3


def test_existing_notice_records_stay_readable_under_the_parent_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Records named leader_notices stay readable and keep their accounted facts."""
    monitor = monitor_at(tmp_path / 'retained-budget')
    monitor.record_session('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    usage_file = monitor.ticket_directory / 'execution-budget.yml'

    current = yaml.safe_load(usage_file.read_text())
    assert 'parent_notices' in current and 'leader_notices' not in current

    # An earlier release retained the same queue under leader_notices.
    retained = dict(current)
    retained['leader_notices'] = retained.pop('parent_notices')
    retained['leader_notices'][0]['delivered'] = True
    usage_file.write_text(yaml.safe_dump(retained))

    pending = monitor.pending_parent_notices()
    assert [notice['key'] for notice in pending] == [
        notice['key'] for notice in retained['leader_notices'][1:]
    ]

    # The parent acknowledgement path marks only the acknowledged key and
    # leaves every accounted fact unchanged.
    monitor.mark_parent_notices_delivered([pending[0]['key']])
    after = yaml.safe_load(usage_file.read_text())
    for field in ('started_at', 'allowance_minutes', 'sessions', 'corrections',
                  'stopping_checks', 'stopped', 'notifications', 'budget'):
        assert after[field] == retained[field]
    assert [notice['key'] for notice in after['parent_notices']] == [
        notice['key'] for notice in retained['leader_notices']
    ]
    delivered = {notice['key']: notice['delivered'] for notice in after['parent_notices']}
    assert delivered[retained['leader_notices'][0]['key']] is True
    assert delivered[pending[0]['key']] is True
    assert delivered[pending[1]['key']] is False
    assert 'leader_notices' not in after


def test_distinct_configured_roles_keep_independent_budget_counts(tmp_path: Path) -> None:
    """Each actual role crosses only its own configured Session threshold."""
    monitor = monitor_at(tmp_path / 'ticket')
    definition = monitor.ticket_directory / 'ticket.md'
    definition.write_text(BODY.replace(
        'planned_sessions: {researcher: 1}',
        'planned_sessions: {researcher: 1, engineer: 1, engineer_expert: 1}',
    ))
    for role in ('engineer', 'engineer-expert', 'researcher'):
        monitor.record_session(role, role)
    usage = monitor.ticket_directory / 'execution-budget.yml'
    before = yaml.safe_load(usage.read_text())
    assert before['sessions'] == {'engineer': 1, 'engineer_expert': 1, 'researcher': 1}
    assert not before['notifications']
    for role, key in (('engineer-expert', 'engineer_expert'), ('engineer', 'engineer'),
                      ('researcher', 'researcher')):
        monitor.record_session(role, role)
        after = yaml.safe_load(usage.read_text())
        assert after['sessions'][key] == 2
        assert after['notifications'][-1] == 'planned_sessions.' + key + ':1'
    assert after['sessions'] == {'engineer': 2, 'engineer_expert': 2, 'researcher': 2}


@pytest.mark.parametrize('role', ['researcher', 'analyst'])
def test_runner_physically_interrupts_any_role_and_retains_trace_and_result(
    commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    """A persisted stop interrupts native work even with no caller reading notices."""
    root, _, _, env = configure_harness(commands, temporary_git_repository, fake_codex, tmp_path)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {role: {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {role: {}},
    }))
    ticket = _ticket('153', 'research')
    ticket['body'] = BODY + ticket['body']
    _register(commands, root, ticket)
    _change_status(commands, root, '153', 'ready')
    release = tmp_path / 'release'
    scenario = '''
import json, os, sys, time
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
sys.stdin.read()
Path('result.md').write_text('Research retained before interruption')
while not Path(os.environ['BUDGET_RELEASE']).exists():
    time.sleep(.02)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}}))
'''
    fake_codex.executable.write_text(app_server_peer('#!' + sys.executable + '\n' + scenario,
                                                    "os.environ['GRAPHTRAJ_PARENT_ALIAS']"))
    protocol = tmp_path / 'native-protocol.jsonl'
    peer = tmp_path / 'budget-peer.py'
    original_peer = Path(__file__).with_name('runner_codex_peer.py')
    peer.write_text(original_peer.read_text().replace(
        "    method = request['method']",
        "    with open(os.environ['BUDGET_PROTOCOL'], 'a') as stream:\n"
        "        stream.write(json.dumps(request) + '\\n')\n"
        "    method = request['method']",
    ))
    fake_codex.executable.write_text(fake_codex.executable.read_text().replace(str(original_peer), str(peer)))
    env['BUDGET_PROTOCOL'] = str(protocol)
    env['BUDGET_RELEASE'] = str(release)
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': role, 'ticket_id': '153'}]}))
    # No caller metadata means no notice reader; this path remains detached.
    result = subprocess.run(
        [str(commands.runner.with_name('graphtraj-mcp'))], cwd=root, env=env,
        input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'graphtraj', 'arguments': {
                              'action': 'execute', 'feature': 'swarm',
                              'arguments': yaml.safe_load(batch.read_text())}}}) + '\n',
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    launched = json.loads(result.stdout)['result']['structuredContent']['tasks'][0]
    alias = launched['alias']
    directory = root / '.graphtraj/runner/sessions' / alias
    evidence = root / '.graphtraj/state/tickets/153-research'
    try:
        wait_for_file(Path(launched['worktree_path']) / 'result.md')
        # The Session may wait normally without being classified as failed.
        status = run_process([str(commands.runner), 'status', alias], cwd=root, env=env)
        assert yaml.safe_load(status.stdout)['aliases'][0]['activity'] == 'running'
        # Only the parent is live; retained child mappings are controlled
        # inputs to the notice seam. A nested sender must address its own
        # parent, never skip it to reach a running ancestor.
        parent_mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        for mode in ("direct", "nested", "admission"):
            nested = mode == "nested"
            other = monitor_at(tmp_path / (mode + '-budget'))
            other.record_session('author', 'author')
            root_child = directory.parent / (mode + '@x1')
            root_child.mkdir()
            child_mapping = dict(parent_mapping, alias=root_child.name, ticket_id='other', parent=alias)
            if mode == 'admission':
                launch = yaml.safe_load((directory / 'launch.yml').read_text())
                launch['mapping'] = {key: value for key, value in child_mapping.items()
                                     if key not in {'session', 'execution_id', 'worker_pid', 'runtime_pid'}}
                (root_child / 'launch.yml').write_text(yaml.safe_dump(launch))
            else:
                (root_child / 'mapping.yml').write_text(yaml.safe_dump(child_mapping))
            sender = root_child
            if nested:
                sender = directory.parent / 'nested@x2'
                sender.mkdir()
                (sender / 'mapping.yml').write_text(yaml.safe_dump(dict(
                    child_mapping, alias=sender.name, parent=root_child.name,
                )))
            sample_stop(other, monkeypatch)
            # Earlier releases retained this queue as leader_notices; notices
            # from such a record must still reach the actual parent.
            record = yaml.safe_load((other.ticket_directory / 'execution-budget.yml').read_text())
            record['leader_notices'] = record.pop('parent_notices')
            (other.ticket_directory / 'execution-budget.yml').write_text(yaml.safe_dump(record))
            if mode == 'admission':
                stopped = run_process(
                    [str(commands.runner.with_name('python')), '-I', '-m',
                     'graphtraj.execution.runner_worker', str(root_child / 'launch.yml')],
                    cwd=root, env={**env, 'GRAPHTRAJ_EVIDENCE': str(other.ticket_directory),
                                   'GRAPHTRAJ_TICKET_NAME': 'research'}, timeout=10,
                )
                assert stopped.returncode == 1, stopped.stdout + stopped.stderr
                failure = yaml.safe_load((root_child / 'launch-error.yml').read_text())
                assert failure['code'] == 'EXECUTION_BUDGET_STOPPED'
                assert failure['terminal_confirmed']
                assert not (root_child / 'mapping.yml').exists()
                assert not (root_child / 'session.yml').exists()
            read_fd, write_fd = os.pipe()
            try:
                with budgets.budget_notice_output(write_fd):
                    other.deliver_parent_notices(sender)
                    if nested:
                        failed = [json.loads(line) for line in (sender / 'parent-notices.jsonl').read_text().splitlines()]
                        assert all(item['parent'] == root_child.name for item in failed)
                        assert all(item['delivery'] == 'not-delivered' for item in failed)
                        assert all(not item['delivered'] for item in other.pending_parent_notices())
                    other.deliver_parent_notices(root_child)
                os.close(write_fd)
                assert os.read(read_fd, 10000) == b''  # no extra caller copy
            finally:
                os.close(read_fd)
            retained = yaml.safe_load((other.ticket_directory / 'execution-budget.yml').read_text())
            assert all(notice['delivered'] for notice in retained['parent_notices'])
        native = [json.loads(line) for line in protocol.read_text().splitlines()]
        assert len([request for request in native if request['method'] == 'turn/steer']) == 9
        assert len([request for request in native if request['method'] == 'turn/start']) == 1
        monitor = budgets.execution_budget_monitor(evidence, '153', 'research')
        with (evidence / '.execution-budget-notices.lock').open('a+') as notice_lock:
            fcntl.flock(notice_lock.fileno(), fcntl.LOCK_EX)
            before = sample_stop(monitor, monkeypatch)
            wait_for_file(directory / 'execution.yml')
            fcntl.flock(notice_lock.fileno(), fcntl.LOCK_UN)
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted', terminal
        assert terminal['budget_stopped'] is True
        assert (Path(launched['worktree_path']) / 'result.md').read_text() == 'Research retained before interruption'
        trace = evidence / 'teams/1/traces' / alias / 'events.jsonl'
        assert trace.read_text()
        after = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        assert after['allowance_minutes'] == before['allowance_minutes']
        assert after['sessions'][role.replace('-', '_')] == 1
        assert all(not notice['delivered'] for notice in after['parent_notices'])
        pending = monitor_at(tmp_path / 'idle-parent-budget')
        pending.record_session('researcher', 'researcher')
        sample_stop(pending, monkeypatch)
        resumed_notice = run_process(
            [str(commands.runner.with_name('python')), '-I', '-c',
             'from pathlib import Path; from graphtraj.execution.execution_budget import ExecutionBudgetMonitor; '
             'import sys; ExecutionBudgetMonitor(Path(sys.argv[1]), "153", "research").deliver_parent_notices(Path(sys.argv[2]))',
             str(pending.ticket_directory), str(root_child)], cwd=root, env=env, timeout=15,
        )
        assert resumed_notice.returncode == 0, resumed_notice.stderr
        received = yaml.safe_load((pending.ticket_directory / 'execution-budget.yml').read_text())
        assert all(notice['delivered'] for notice in received['parent_notices'])
        resumed_mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        assert resumed_mapping['session'] == parent_mapping['session']
        assert resumed_mapping['execution_id'] != parent_mapping['execution_id']
        native = [json.loads(line) for line in protocol.read_text().splitlines()]
        continuation = [item for item in native if item['method'] == 'turn/start'][1]
        message = json.loads(continuation['params']['input'][0]['text'])
        assert set(message) == {'source', 'alias', 'event', 'message'}
        assert message['source'] == 'graphtraj' and message['alias'] == root_child.name
        assert message['event'] == 'execution-budget-exceeded'

        release.touch()
        events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
                  for line in shard.read_text().splitlines()]
        resumed = run_process(
            [str(commands.runner), 'send', alias, '--instruction', 'Return the existing research.',
             '--caused-by-event-id', events[-1]['event_id']], cwd=root, env=env, timeout=15,
        )
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        resume = yaml.safe_load((directory / 'resume.yml').read_text())
        assert not resume['drive_children'] and not resume.get('monitor_execution_budget', False)
        permissions = resume['adapter_request']['session_parameters']['config']['permissions']
        assert any(profile['filesystem'][':workspace_roots']['.'] == 'read'
                   for profile in permissions.values())
        retained = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        for field in ('started_at', 'allowance_minutes', 'sessions', 'stopping_checks', 'stopped'):
            assert retained[field] == after[field]

    finally:
        release.touch()


def test_top_level_caller_channel_is_retained_without_claiming_agent_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound caller receives each event once; persistence is not native receipt."""
    monitor = monitor_at(tmp_path / 'ticket')
    monitor.record_session('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    session = tmp_path / 'runner/sessions/research@x1'
    session.mkdir(parents=True)
    (session / 'launch.yml').write_text(yaml.safe_dump({'mapping': {
        'alias': session.name, 'ticket_id': '153', 'parent': None,
    }}))
    read_fd, write_fd = os.pipe()
    try:
        with budgets.budget_notice_output(write_fd):
            monitor.deliver_parent_notices(session)
            monitor.deliver_parent_notices(session)
        os.close(write_fd)
        events = [json.loads(line) for line in os.read(read_fd, 10000).splitlines()]
    finally:
        os.close(read_fd)
    assert [event['threshold']['kind'] for event in events] == [
        'elapsed_minutes', 'additional_allowance', 'stochastic_stop',
    ]
    usage = yaml.safe_load((monitor.ticket_directory / 'execution-budget.yml').read_text())
    assert all(notice['channel_written'] and not notice['delivered'] for notice in usage['parent_notices'])


@pytest.mark.parametrize('when', ['before-create', 'during-create'])
def test_sampled_stop_blocks_native_execution_admission(
    commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    when: str,
) -> None:
    """No turn starts after a stop, including while thread/start is in flight."""
    root, _, _, env = configure_harness(commands, temporary_git_repository, fake_codex, tmp_path)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    ticket = _ticket('153', 'research')
    ticket['body'] = BODY + ticket['body']
    _register(commands, root, ticket)
    _change_status(commands, root, '153', 'ready')
    evidence = root / '.graphtraj/state/tickets/153-research'
    monitor = budgets.execution_budget_monitor(evidence, '153', 'research')
    monitor.check('researcher', 'researcher')
    if when == 'before-create':
        sample_stop(monitor, monkeypatch)
    original_peer = Path(__file__).with_name('runner_codex_peer.py')
    peer = tmp_path / 'admission-peer.py'
    hook = '''
        import yaml
        from graphtraj.execution import execution_budget as budget
        evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
        usage = yaml.safe_load((evidence / 'execution-budget.yml').read_text())
        budget.time.time = lambda: usage['started_at'] + 1200
        budget.random.random = lambda: .999
        monitor = budget.execution_budget_monitor(evidence, '153', 'research')
        assert monitor.check('researcher', 'researcher')
'''
    peer.write_text(original_peer.read_text().replace(
        "        result = {'thread': {'id': session, 'path': str(native)}}",
        hook + "        result = {'thread': {'id': session, 'path': str(native)}}",
    ))
    fake_codex.executable.write_text(fake_codex.executable.read_text().replace(str(original_peer), str(peer)))
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': 'researcher', 'ticket_id': '153'}]}))
    result = run_process([str(commands.runner), '--swarm-input', str(batch)], cwd=root, env=env, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    assert task['launch_status'] == 'stopped', task
    assert task['error']['code'] == 'EXECUTION_BUDGET_STOPPED', task
    directories = list((root / '.graphtraj/runner/sessions').iterdir())
    assert len(directories) == 1
    if when == 'before-create':
        assert not (directories[0] / 'session.yml').exists()
    else:
        assert (directories[0] / 'session.yml').is_file()
        terminal = yaml.safe_load((directories[0] / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
        trace = next((evidence / 'teams/1/traces').glob('*/events.jsonl'))
        assert 'session_meta' in trace.read_text()
        assert 'turn_context' not in trace.read_text()


@pytest.mark.parametrize('caller', ['cli', 'codex-binding'])
def test_integration_helper_stops_and_returns_notice_to_its_caller(
    commands: InstalledCommands,
    accepted_ticket: tuple,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
) -> None:
    """The synchronous integration helper interrupts instead of waiting on model work."""
    root, worktrees, state, _ = accepted_ticket
    dev = worktrees / 'dev'
    (dev / 'TEAM_ROUND_DELIVERED.txt').write_text('conflicting integration work\n')
    run_process(['git', 'add', 'TEAM_ROUND_DELIVERED.txt'], cwd=dev).check_returncode()
    run_process(['git', 'commit', '-m', 'Independent integration work'], cwd=dev).check_returncode()
    command = [str(commands.product), 'ticket', 'integrate', '--ticket-id', '83']
    validation = [sys.executable, '-c', 'pass']
    conflict = run_process(command + ['--', *validation], cwd=root)
    assert conflict.returncode == 1
    release = root / 'release-resolver'
    environment = {
        **os.environ, 'HOME': str(root / 'operator-home'),
        'PATH': str(fake_codex.executable.parent) + os.pathsep + os.environ['PATH'],
        'FAKE_CODEX_LOG': str(fake_codex.log_file),
        'FAKE_CODEX_LIFECYCLE_ACTION': 'resolve-integration',
        'GRAPHTRAJ_AGENT_RUNNER': str(commands.runner),
        'FAKE_CODEX_RELEASE_FILE': str(release),
        'CODEX_THREAD_ID': 'bound-caller' if caller == 'codex-binding' else '',
    }
    process = subprocess.Popen(command + ['--resolve-conflict', 'Preserve both lines', '--role', 'coding_team.merge_resolver', '--', *validation],
                               cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        sessions = root / '.graphtraj/runner/sessions'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            mappings = list(sessions.glob('*merge_resolver@*/mapping.yml'))
            if mappings:
                break
            time.sleep(.02)
        assert mappings
        directory = mappings[0].parent
        monitor = budgets.execution_budget_monitor(state / 'tickets/83-integration', '83', 'integration')
        before = yaml.safe_load((monitor.ticket_directory / 'execution-budget.yml').read_text())
        with monkeypatch.context() as patch:
            patch.setattr(budgets.time, 'time', lambda: before['started_at'] + 100000)
            patch.setattr(budgets.random, 'random', lambda: .999)
            assert monitor.check('merge-resolver', 'merge-resolver')
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 1, stdout + stderr
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
        events = [json.loads(line) for line in stderr.splitlines() if line.startswith('{')]
        if caller == 'cli':
            assert any(event['threshold']['kind'] == 'stochastic_stop' for event in events), stderr
        else:
            deliveries = yaml.safe_load(stdout)['stop_deliveries']
            assert len(deliveries) == 1
            assert deliveries[0]['ticket']['ticket_id'] == '83'
            assert deliveries[0]['delivered_at'] and deliveries[0]['triggered_at']
            assert not events  # one connected caller, no duplicate stderr channel
        assert not release.exists()  # stopped before the test/model chose to finish
        usage = yaml.safe_load((monitor.ticket_directory / 'execution-budget.yml').read_text())
        assert usage['allowance_minutes'] == before['allowance_minutes']
    finally:
        release.touch()
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)
