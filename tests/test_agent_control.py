"""Task-free Agent control over a caller-chosen data root, without GraphTraj."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import agent_swarm
from agent_swarm import AgentControl, AgentsError, Caller, ExecutionEvents


SOURCE = Path(__file__).resolve().parents[1] / 'src'


class ScriptedDriver:
    """In-process driver: each execution runs until released or interrupted.

    It counts executions per native Session so a test can prove that no two
    executions of one Session ever overlap.
    """

    def __init__(self, deliver_error: Exception | None = None) -> None:
        """Start with no executions; ``deliver_error`` makes delivery fail."""
        self.lock          = threading.Lock()
        self.releases      = {}
        self.inputs        = {}
        self.started       = []
        self.active        = {}
        self.max_active    = 0
        self.deliveries    = 0
        self.deliver_error = deliver_error
        self.replies       = []

    def prepare(self, runtime, caller):
        """Retain the continuation settings a caller would pass explicitly."""
        return {'cwd': '/explicit/cwd', 'runtime': runtime}

    def start(self, run):
        """Bind a Session at once, then work on a thread until released."""
        if hasattr(self, 'start_gate'):
            self.start_gate.wait(10)
        session = run.session or 'native-' + run.agent[-6:]
        release = threading.Event()
        with self.lock:
            self.releases[run.execution] = release
            self.inputs[run.execution]   = [run.message]
            self.started.append((run.agent, run.session, run.message, run.archive))
            self.active[session] = self.active.get(session, 0) + 1
            self.max_active      = max(self.max_active, self.active[session])
        run.events.session(session)
        run.events.process(runtime_pid=os.getpid())

        def work():
            """Finish with the inputs seen, as a Runtime result would."""
            release.wait(10)
            with self.lock:
                self.active[session] -= 1
                messages = '|'.join(self.inputs[run.execution])
            outcome = 'interrupted' if getattr(release, 'interrupted', False) else 'completed'
            run.events.finished(outcome, last_message=messages)

        threading.Thread(target=work, daemon=True).start()

    def deliver(self, run, message):
        """Add input to the running execution."""
        self.deliveries += 1
        if self.deliver_error is not None:
            raise self.deliver_error
        self.inputs[run.execution].append(message)

    def interrupt(self, run):
        """Stop the execution natively."""
        release = self.releases[run.execution]
        release.interrupted = True
        release.set()
        return True

    def requests(self, run):
        """Return one pending native approval."""
        return [{'request_token': 'token-1', 'method': 'native/approve', 'params': {'tool': 'Bash'}}]

    def reply(self, run, request, response):
        """Submit the reply; a second native submission would be a defect."""
        self.replies.append((request['request_token'], dict(response)))
        return {'reply_status': 'submitted'}

    def release(self, execution):
        """Let one execution complete normally."""
        self.releases[execution].set()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Use an arbitrary data root: no project, Task, Git or GraphTraj files."""
    return tmp_path / 'any-data-root'


def call(control, caller, **request):
    """Invoke the registered function and return its document."""
    result = agent_swarm.bind(control, caller)(request)
    return result.document, result.failed


def test_lifecycle_create_send_wait_interrupt_resume_retire(root: Path) -> None:
    """Two visible states only; stop keeps the Session; retire hides but keeps."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None, session='host-session')

    created, failed = call(control, main, action='create', runtime='scripted',
                           instruction='Remember 7.', name='helper')
    agent, session, first = created['agent'], created['session'], created['execution']
    assert not failed and created['result']['state'] == 'active'
    assert created['result']['parent'] is None and created['result']['host'] == 'test-host'

    sent, _ = call(control, main, action='send', agent=agent, message='And 8.')
    assert sent['execution'] == first and sent['result']['delivery']['delivery'] == 'submitted'

    timed, _ = call(control, main, action='wait', agent=agent, timeout_seconds=0.1)
    assert timed['result']['timed_out'] and timed['result']['state'] == 'active'
    driver.release(first)
    waited, _ = call(control, main, action='wait', agent=agent, timeout_seconds=5)
    assert waited['result']['state'] == 'standby' and not waited['result']['timed_out']
    assert waited['result']['last_result']['last_message'] == 'Remember 7.|And 8.'

    # An idle send continues the same native Session; interrupt returns to standby.
    again, _ = call(control, main, action='send', agent=agent, message='Recall.')
    assert again['execution'] != first and again['session'] == session
    stopped, _ = call(control, main, action='interrupt', agent=agent)
    assert stopped['result']['interrupt'] == 'requested'
    stopped, _ = call(control, main, action='wait', agent=agent, timeout_seconds=5)
    assert stopped['result']['state'] == 'standby'
    assert stopped['result']['last_result']['outcome'] == 'interrupted'

    resumed, _ = call(control, main, action='resume', agent=agent, message='Continue.')
    assert resumed['session'] == session and resumed['result']['state'] == 'active'
    assert [entry[1] for entry in driver.started] == [None, session, session]
    driver.release(resumed['execution'])
    call(control, main, action='wait', agent=agent, timeout_seconds=5)

    tree, _ = call(control, main, action='status')
    assert [node['agent'] for node in tree['result']['agents']] == [agent]
    assert {node['state'] for node in tree['result']['agents']} <= {'active', 'standby'}

    retired, failed = call(control, main, action='retire', agent=agent)
    assert not failed and retired['result']['retired']
    tree, _ = call(control, main, action='status')
    assert tree['result']['agents'] == []
    kept, _ = call(control, main, action='status', agent=agent)
    assert kept['result']['state'] == 'standby' and kept['result']['retired_at']
    assert kept['session'] == session
    refused, failed = call(control, main, action='send', agent=agent, message='More.')
    assert failed and refused['error']['code'] == 'retired'

    record = json.loads((root / 'control/agents' / f'{agent}.json').read_text())
    assert len(record['executions']) == 3 and record['settings'] == {'cwd': '/explicit/cwd',
                                                                     'runtime': 'scripted'}
    assert not set(record) & {'task_id', 'team', 'round', 'worldline', 'budget', 'report', 'worktree'}


def test_hierarchy_uses_true_parents_and_caller_scope(root: Path) -> None:
    """A child's own creation nests under it; other root callers see nothing."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None, session='host-session')

    child, _      = call(control, main, action='create', runtime='scripted', instruction='a')
    grandchild, _ = call(control, Caller('test-host', child['agent']),
                         action='create', runtime='scripted', instruction='b')

    tree, _ = call(control, main, action='status')
    [node]  = tree['result']['agents']
    assert node['agent'] == child['agent']
    assert [item['agent'] for item in node['children']] == [grandchild['agent']]
    assert node['children'][0]['parent'] == child['agent']

    stranger = Caller('test-host', None, session='another-session')
    tree, _  = call(control, stranger, action='status')
    assert tree['result']['agents'] == []
    hidden, failed = call(control, stranger, action='interrupt', agent=child['agent'])
    assert failed and hidden['error']['code'] == 'not-found'

    # Retiring the child keeps the grandchild visible under the nearest visible ancestor.
    for execution in list(driver.releases):
        driver.release(execution)
    call(control, main, action='wait', agent=child['agent'], timeout_seconds=5)
    call(control, main, action='retire', agent=child['agent'])
    tree, _ = call(control, main, action='status')
    assert [node['agent'] for node in tree['result']['agents']] == [grandchild['agent']]
    assert tree['result']['agents'][0]['parent'] == child['agent']


def test_repeated_controls_never_run_one_session_twice(root: Path) -> None:
    """Concurrent sends, resumes and interrupts share one current execution."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None)

    created, _ = call(control, main, action='create', runtime='scripted', instruction='go')
    agent      = created['agent']
    driver.release(created['execution'])
    call(control, main, action='wait', agent=agent, timeout_seconds=5)

    # While the native start is still in progress, repeats are refused or no-ops.
    driver.start_gate = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(call, control, main, action='send', agent=agent, message='first')
        while len(json.loads((root / 'control/agents' / f'{agent}.json').read_text())['executions']) < 2:
            pass
        starting, failed = call(control, main, action='send', agent=agent, message='early')
        assert failed and starting['error']['code'] == 'starting'
        early_stop, failed = call(control, main, action='interrupt', agent=agent)
        assert failed and early_stop['error']['code'] == 'starting'
        early_resume, _ = call(control, main, action='resume', agent=agent, message='r')
        assert early_resume['result']['reason'] == 'already-active'
        driver.start_gate.set()
        first_document, _ = first.result(timeout=5)

    with ThreadPoolExecutor(max_workers=8) as pool:
        sends = list(pool.map(lambda index: call(control, main, action='send', agent=agent,
                                                 message=f'm{index}'), range(8)))
        resumes = list(pool.map(lambda index: call(control, main, action='resume', agent=agent,
                                                   message='r'), range(4)))
    executions = {document['execution'] for document, failed in sends + resumes}
    assert executions == {first_document['execution']} and len(driver.started) == 2
    assert driver.max_active == 1
    assert all(document['result']['delivery']['delivery'] == 'submitted' for document, _ in sends)
    assert all(document['result']['reason'] == 'already-active' for document, _ in resumes)

    with ThreadPoolExecutor(max_workers=4) as pool:
        stops = list(pool.map(lambda _: call(control, main, action='interrupt', agent=agent), range(4)))
    assert sorted(document['result']['interrupt'] for document, _ in stops).count('requested') == 1
    waited, _ = call(control, main, action='wait', agent=agent, timeout_seconds=5)
    assert waited['result']['state'] == 'standby'
    assert driver.max_active == 1


def test_unknown_delivery_is_recorded_and_not_resent(root: Path) -> None:
    """A transport failure with an unknown result keeps its receipt and is not retried."""
    driver  = ScriptedDriver(deliver_error=OSError('pipe closed'))
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None)

    created, _ = call(control, main, action='create', runtime='scripted', instruction='go')
    sent, failed = call(control, main, action='send', agent=created['agent'], message='once')
    assert failed and sent['result']['delivery']['delivery'] == 'unknown'
    assert sent['result']['delivery']['error']['message'] == 'pipe closed'
    assert driver.deliveries == 1
    record = json.loads((root / 'control/agents' / f"{created['agent']}.json").read_text())
    assert record['executions'][-1]['inputs'][0]['delivery'] == 'unknown'
    driver.release(created['execution'])


def test_native_requests_reply_once_and_reject_stale_executions(root: Path) -> None:
    """A repeated reply returns the first receipt without a second native reply."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None)

    created, _ = call(control, main, action='create', runtime='scripted', instruction='go')
    agent      = created['agent']

    # The Runtime retains a request: a waiting caller learns of it at once.
    ExecutionEvents(control, agent, created['execution']).request(
        {'request_token': 'token-1', 'method': 'native/approve'})
    waited, _ = call(control, main, action='wait', agent=agent, timeout_seconds=5)
    assert not waited['result']['timed_out'] and waited['result']['state'] == 'active'
    assert waited['result']['pending_requests'] == 1

    listed, _  = call(control, main, action='requests', agent=agent)
    [request]  = listed['result']['requests']
    assert request['execution'] == created['execution']

    first, _  = call(control, main, action='reply', agent=agent, request=request,
                     response={'behavior': 'allow'})
    second, _ = call(control, main, action='reply', agent=agent, request=request,
                     response={'behavior': 'deny'})
    assert first['result']['reply_status'] == 'submitted' and second['result']['duplicate']
    assert driver.replies == [('token-1', {'behavior': 'allow'})]

    # An answered request no longer ends a wait.
    waited, _ = call(control, main, action='wait', agent=agent, timeout_seconds=0.2)
    assert waited['result']['timed_out'] and 'pending_requests' not in waited['result']

    stale, failed = call(control, main, action='requests', agent=agent, execution='old')
    assert failed and stale['error']['code'] == 'stale-execution'
    driver.release(created['execution'])


def test_failed_start_keeps_the_native_reason(root: Path) -> None:
    """A Runtime start failure leaves standby with its exact native code."""
    class Failing(ScriptedDriver):
        """Reject the native start."""

        def start(self, run):
            """Raise the Runtime's own rejection."""
            run.events.process(runtime_exit={
                'runtime_exit_code': 1, 'wrapper_exited': True,
                'owned_process_group_exited': None, 'terminal_confirmed': False})
            raise AgentsError('RUNTIME_EXECUTABLE_INVALID', 'Runtime is unavailable.')

    control = AgentControl(root, {'scripted': Failing()})
    created, failed = call(control, Caller('test-host', None), action='create',
                           runtime='scripted', instruction='go')
    assert failed and created['result']['state'] == 'standby'
    assert created['result']['last_result']['error'] == {
        'code': 'RUNTIME_EXECUTABLE_INVALID', 'message': 'Runtime is unavailable.'}
    exit_facts = created['result']['last_result']['runtime_exit']
    assert exit_facts == {'runtime_exit_code': 1, 'wrapper_exited': True,
                          'owned_process_group_exited': None, 'terminal_confirmed': False}
    exit_facts['runtime_exit_code'] = 0
    status, _ = call(control, Caller('test-host', None), action='status', agent=created['agent'])
    assert status['result']['last_result']['runtime_exit']['runtime_exit_code'] == 1
    retry, failed = call(control, Caller('test-host', None), action='send',
                         agent=created['agent'], message='again')
    assert failed and retry['error']['code'] == 'no-session'


def test_lost_owner_keeps_process_facts_and_blocks_duplicates(root: Path) -> None:
    """A dead owner with a live Runtime stays active; a fully dead one ends."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None)
    created, _ = call(control, main, action='create', runtime='scripted', instruction='go')
    path       = root / 'control/agents' / f"{created['agent']}.json"

    dead = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'],
                          capture_output=True, text=True, check=True).stdout.strip()
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=int(dead), runtime_pid=os.getpid())
    path.write_text(json.dumps(record))

    status, _ = call(control, main, action='status', agent=created['agent'])
    assert status['result']['state'] == 'active' and 'owner-exited' in status['result']['diagnostic']
    resumed, _ = call(control, main, action='resume', agent=created['agent'], message='x')
    assert resumed['result']['reason'] == 'already-active' and len(driver.started) == 1

    record = json.loads(path.read_text())
    record['executions'][-1]['process']['runtime_pid'] = int(dead)
    path.write_text(json.dumps(record))
    status, _ = call(control, main, action='status', agent=created['agent'])
    assert status['result']['state'] == 'standby'
    assert status['result']['last_result']['error']['code'] == 'owner-exited'
    kept = json.loads(path.read_text())['executions'][-1]['process']
    assert kept['worker_pid'] == int(dead) and kept['owned_at']
    driver.release(created['execution'])


def test_direct_parent_confirms_an_ended_execution_whose_processes_are_gone(root: Path) -> None:
    """Only a verified-gone owner and Runtime let the direct parent confirm the end."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    main    = Caller('test-host', None, session='host-session')
    parent, _ = call(control, main, action='create', runtime='scripted', instruction='lead')
    lead      = Caller('test-host', parent['agent'])
    child, _  = call(control, lead, action='create', runtime='scripted', instruction='work')
    unknown, _ = call(control, lead, action='create', runtime='scripted', instruction='work')
    grouped, _ = call(control, lead, action='create', runtime='scripted', instruction='work')
    path = root / 'control/agents' / f"{child['agent']}.json"

    # The owner and Runtime are real processes that this test ends itself.
    worker, runtime = (subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
                       for _ in range(2))
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=worker.pid, runtime_pid=runtime.pid)
    path.write_text(json.dumps(record))
    for process in (worker, runtime):
        refused, failed = call(control, lead, action='interrupt', agent=child['agent'])
        assert failed and refused['error']['code'] == 'not-owned'
        process.kill()
        process.wait()

    ended, _ = call(control, lead, action='status', agent=child['agent'])
    assert ended['result']['state'] == 'standby'
    assert ended['result']['last_result']['terminal_confirmed'] is False
    with pytest.raises(AgentsError) as stopped:
        control.configure_stopped(child['agent'], {'cwd': '/moved'}, lead)
    assert stopped.value.code == 'turn-running'
    denied, failed = call(control, main, action='interrupt', agent=child['agent'])
    assert failed and denied['error']['code'] == 'authority-denied'

    confirmed, failed = call(control, lead, action='interrupt', agent=child['agent'])
    assert not failed and confirmed['result']['interrupt'] == 'stopped'
    assert confirmed['result']['termination_confirmed'] == [child['execution']]
    last = confirmed['result']['last_result']
    assert last['terminal_confirmed'] is False and last['error']['code'] == 'owner-exited'
    assert last['termination_confirmation']['evidence'] == {
        'worker_pid': worker.pid, 'runtime_pid': runtime.pid,
        'worker_alive': False, 'runtime_alive': False}
    assert last['termination_confirmation']['by']['agent'] == parent['agent']
    repeated, _ = call(control, lead, action='interrupt', agent=child['agent'])
    assert repeated['result']['interrupt'] == 'not-running'

    # The confirmed Agent is configured and continued under the normal rules.
    control.configure_stopped(child['agent'], {'cwd': '/moved'}, lead)
    resumed, failed = call(control, lead, action='resume', agent=child['agent'], message='again')
    assert not failed and resumed['session'] == child['session']
    driver.release(resumed['execution'])

    # A Runtime group member that outlived the recorded Runtime blocks confirmation.
    group  = subprocess.Popen([sys.executable, '-c', 'import subprocess, sys; subprocess.Popen('
                               '[sys.executable, "-c", "import time; time.sleep(60)"])'], start_new_session=True)
    group.wait()
    path   = root / 'control/agents' / f"{grouped['agent']}.json"
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=worker.pid, runtime_pid=group.pid)
    path.write_text(json.dumps(record))
    refused, failed = call(control, lead, action='interrupt', agent=grouped['agent'])
    assert failed and refused['error']['code'] == 'termination-unconfirmed'
    assert 'termination_confirmation' not in json.loads(path.read_text())['executions'][-1]
    os.killpg(group.pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.killpg(group.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    confirmed, failed = call(control, lead, action='interrupt', agent=grouped['agent'])
    assert not failed and confirmed['result']['interrupt'] == 'stopped'

    # An execution without a recorded Runtime process cannot be verified.
    path   = root / 'control/agents' / f"{unknown['agent']}.json"
    record = json.loads(path.read_text())
    record['executions'][-1]['process'].update(worker_pid=worker.pid, runtime_pid=None)
    path.write_text(json.dumps(record))
    refused, failed = call(control, lead, action='interrupt', agent=unknown['agent'])
    assert failed and refused['error']['code'] == 'termination-unconfirmed'
    assert 'termination_confirmation' not in json.loads(path.read_text())['executions'][-1]


def test_config_is_owned_by_the_data_root(root: Path) -> None:
    """Standalone defaults are off; consumer defaults respect explicit choices."""
    assert agent_swarm.read_config(root) == {'save_normalized_sessions': False,
                                             'backfill_history': False}
    assert not (root / 'config.yml').exists()

    assert agent_swarm.default_config(root, save_normalized_sessions=True)['save_normalized_sessions']
    agent_swarm.write_config(root, save_normalized_sessions=False, backfill_history=True)
    effective = agent_swarm.default_config(root, save_normalized_sessions=True, backfill_history=False)
    assert effective == {'save_normalized_sessions': False, 'backfill_history': True}
    assert (root / 'config.yml').read_text() == ('save_normalized_sessions: false\n'
                                                 'backfill_history: true\n')

    (root / 'config.yml').write_text('save_normalized_sessions: yes\n')
    with pytest.raises(ValueError):
        agent_swarm.read_config(root)


def test_archive_is_bound_only_when_enabled(root: Path) -> None:
    """Archiving off keeps full control; on, the bound archive reaches the driver."""
    driver  = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    archive = object()
    bound   = agent_swarm.bind(control, Caller('test-host', None), archive=archive)

    off = bound({'action': 'create', 'runtime': 'scripted', 'instruction': 'a'}).document
    agent_swarm.write_config(root, save_normalized_sessions=True)
    on  = bound({'action': 'create', 'runtime': 'scripted', 'instruction': 'b'}).document
    assert [entry[3] for entry in driver.started] == [None, archive]
    for document in (off, on):
        driver.release(document['execution'])


@pytest.mark.parametrize('configuration', [None, 'existing-user-connection'])
def test_core_imports_and_runs_without_graphtraj(tmp_path: Path, configuration: str | None) -> None:
    """The control core loads and starts with no GraphTraj module or project."""
    code = (
        'import sys, agent_swarm\n'
        'from agent_swarm import AgentControl, Caller, bind\n'
        'class D:\n'
        '    def prepare(self, runtime, caller, *, configuration=None):\n'
        '        assert configuration == (sys.argv[2] or None)\n'
        '        return {"selected": configuration}\n'
        '    def start(self, run): run.events.session("s"); run.events.finished("completed")\n'
        'call = bind(AgentControl(sys.argv[1], {"r": D()}), Caller("h", None))\n'
        'selection = {"configuration": sys.argv[2]} if sys.argv[2] else {}\n'
        'created = call({"action": "create", "runtime": "r", "instruction": "x", **selection}).document\n'
        'print(created["result"]["state"], created["session"],\n'
        '      sorted(m for m in sys.modules if m.split(".")[0] == "graphtraj"))\n'
    )
    output = subprocess.run(
        [sys.executable, '-c', code, str(tmp_path / 'root'), configuration or ''], check=True, capture_output=True,
        text=True, env={**os.environ, 'PYTHONPATH': str(SOURCE)}, cwd=tmp_path,
    ).stdout.split()
    assert output == ['standby', 's', '[]']


def test_public_creator_preserves_external_root_scope(root: Path) -> None:
    """Expose the stored external source without inventing a parent or changing access."""
    driver = ScriptedDriver()
    control = AgentControl(root, {'scripted': driver})
    parent = Caller('claude-native', None, 'original-native-session', 'claude')
    created, failed = call(control, parent, action='create', runtime='scripted', instruction='hello')
    assert not failed
    try:
        expected = {'host': 'claude-native', 'agent': None, 'session': 'original-native-session'}
        assert created['result']['parent'] is None
        assert created['result']['creator'] == expected
        created['result']['creator']['session'] = 'not-authority'
        status, failed = call(control, parent, action='status', agent=created['agent'])
        assert not failed and status['result']['creator'] == expected
        hierarchy, failed = call(control, parent, action='status')
        assert not failed and hierarchy['result']['agents'][0]['creator'] == expected
        stranger = Caller('claude-native', None, 'different-native-session', 'claude')
        denied, failed = call(control, stranger, action='status', agent=created['agent'])
        assert failed and denied['error']['code'] == 'not-found'
    finally:
        driver.release(created['execution'])
        stopped, failed = call(control, parent, action='wait', agent=created['agent'], timeout_seconds=2)
        assert not failed and stopped['result']['state'] == 'standby'


@pytest.mark.parametrize('missing', [None, 'prompt_started', 'native_session_bound',
                                   'wrapper_exited', 'owned_process_group_exited'])
def test_same_agent_retries_only_proven_unbound_start(root: Path, missing: str | None) -> None:
    """Retained startup facts permit a retry without rewriting the old failure."""
    facts = {'prompt_started': False, 'native_session_bound': False,
             'wrapper_exited': True, 'owned_process_group_exited': True,
             'terminal_confirmed': False, 'runtime_exit_code': 1}
    if missing:
        facts.pop(missing)

    class StartupFailure(ScriptedDriver):
        """Fail once before binding, then use the ordinary controlled Runtime."""
        attempted = False

        def start(self, run):
            """Supply owned exit evidence for the failed initial execution."""
            if not self.attempted:
                self.attempted = True
                run.events.process(runtime_exit=facts)
                run.events.finished('failed', terminal_confirmed=False)
                raise AgentsError('startup-failed', 'controlled startup failure')
            super().start(run)

    driver = StartupFailure()
    control = AgentControl(root, {'scripted': driver})
    caller = Caller('test-host', None)
    first, failed = call(control, caller, action='create', runtime='scripted', instruction='first')
    assert failed
    previous = first['result']['last_result']
    retried, failed = call(control, caller, action='resume', agent=first['agent'], message='retry')
    if missing:
        assert failed and retried['error']['code'] == 'no-session'
        assert not driver.started
        return
    assert not failed
    assert retried['agent'] == first['agent']
    assert retried['execution'] != first['execution']
    assert retried['session'] is not None
    assert retried['result']['last_result'] == previous
    assert previous['terminal_confirmed'] is False
    driver.release(retried['execution'])
    call(control, caller, action='wait', agent=first['agent'], timeout_seconds=5)
