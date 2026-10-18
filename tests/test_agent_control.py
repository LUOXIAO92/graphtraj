"""Task-free Agent control over a caller-chosen data root, without GraphTraj."""

import json
import os
import subprocess
import sys
import threading
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
            raise AgentsError('RUNTIME_EXECUTABLE_INVALID', 'Runtime is unavailable.')

    control = AgentControl(root, {'scripted': Failing()})
    created, failed = call(control, Caller('test-host', None), action='create',
                           runtime='scripted', instruction='go')
    assert failed and created['result']['state'] == 'standby'
    assert created['result']['last_result']['error'] == {
        'code': 'RUNTIME_EXECUTABLE_INVALID', 'message': 'Runtime is unavailable.'}
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


def test_core_imports_and_runs_without_graphtraj(tmp_path: Path) -> None:
    """The control core loads and starts with no GraphTraj module or project."""
    code = (
        'import sys, agent_swarm\n'
        'from agent_swarm import AgentControl, Caller, bind\n'
        'class D:\n'
        '    def prepare(self, runtime, caller): return {}\n'
        '    def start(self, run): run.events.session("s"); run.events.finished("completed")\n'
        'call = bind(AgentControl(sys.argv[1], {"r": D()}), Caller("h", None))\n'
        'created = call({"action": "create", "runtime": "r", "instruction": "x"}).document\n'
        'print(created["result"]["state"], created["session"],\n'
        '      sorted(m for m in sys.modules if m.split(".")[0] == "graphtraj"))\n'
    )
    output = subprocess.run(
        [sys.executable, '-c', code, str(tmp_path / 'root')], check=True, capture_output=True,
        text=True, env={**os.environ, 'PYTHONPATH': str(SOURCE)}, cwd=tmp_path,
    ).stdout.split()
    assert output == ['standby', 's', '[]']


def test_native_callback_binds_child_scope_and_expires_with_execution(root: Path) -> None:
    """A Driver gets only its own child's scope, and an old callback cannot resume authority."""
    class CapturedDriver(ScriptedDriver):
        """Retain public Run values handed to the driver for lifecycle assertions."""
        def start(self, run: agent_swarm.Run) -> None:
            """Capture the public callback before reporting native readiness."""
            self.run = run
            super().start(run)

    driver = CapturedDriver()
    control = AgentControl(root, {'scripted': driver})
    parent = agent_swarm.bind(control, Caller('test-host', None, session='main'))
    first = parent({'action': 'create', 'runtime': 'scripted', 'instruction': 'parent-child'})
    agent = first.document['agent']
    old = driver.run.call
    grandchild = old({'action': 'create', 'runtime': 'scripted', 'instruction': 'nested'})
    assert not grandchild.failed
    assert grandchild.document['result']['parent'] == agent
    # It cannot treat its own caller as a controllable descendant.
    refused = old({'action': 'interrupt', 'agent': agent})
    assert refused.failed and refused.document['error']['code'] == 'not-found'
    parent({'action': 'interrupt', 'agent': grandchild.document['agent']})
    parent({'action': 'wait', 'agent': grandchild.document['agent'], 'timeout_seconds': 5})
    parent({'action': 'interrupt', 'agent': agent})
    parent({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})
    assert old({'action': 'status'}).document['error']['code'] == 'stale-execution'
    resumed = parent({'action': 'resume', 'agent': agent, 'message': 'continue'})
    assert not resumed.failed
    assert old({'action': 'status'}).document['error']['code'] == 'stale-execution'
    current = driver.run.call({'action': 'status'})
    assert not current.failed
    assert [row['agent'] for row in current.document['result']['agents']] == [grandchild.document['agent']]
    parent({'action': 'interrupt', 'agent': agent})
    parent({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})
