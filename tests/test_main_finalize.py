"""Public adopted-host finish-check and controlled native lifecycle evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Awaitable, Callable

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution import main_finalize
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.local_tool import HostTool, bind
from graphtraj.runtimes.codex import finalize
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.stop_hook import main as stop_hook


PEER = r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ['FINALIZE_TEST_ROOT'])
options = json.loads((root / 'options.json').read_text())

def send(message):
    print(json.dumps(message), flush=True)

def main_thread():
    return {'id':'main', 'sessionId':'shared-native-session', 'model':'configured-model', 'modelProvider':'actual-provider',
            'source':'appServer', 'parentThreadId':None,
            'status':options.get('thread_status', {'type':'active' if not options.get('stopped') else 'idle'}),
            **options.get('thread_config', {})}

for line in sys.stdin:
    request = json.loads(line)
    with (root / 'wire.jsonl').open('a') as stream:
        stream.write(json.dumps(request) + '\n')
    method, params = request['method'], request.get('params', {})
    if method == 'initialized': continue
    result = {}
    if method == 'thread/read':
        result = {'thread':main_thread()}
        if options.get('read_id_from_request'): result['thread']['id'] = params['threadId']
    elif method == 'thread/turns/list':
        turn = options.get('turns_by_thread', {}).get(params['threadId'], options.get('current_turn','main-turn'))
        result = {'data':[{'id':turn, 'status':options.get('turn_status','inProgress')}]}
    elif method == 'thread/fork':
        if options.get('fork_error'):
            send({'id':request['id'],'error':{'code':-32600,'message':'fork unavailable'}})
            continue
        # The peer owns context inheritance; the caller supplies no history.
        parent_context = ['original developer instructions','private context sentinel']
        child = {'id':options.get('child','checker'),'forkedFromId':'main'}
        (root / 'child-context.json').write_text(json.dumps(parent_context))
        result = {'thread':child, 'model':options.get('fork_model','actual-model'),
                  'modelProvider':'actual-provider'}
    elif method == 'turn/start':
        assert params['threadId'] == options.get('child','checker')
        context = json.loads((root / 'child-context.json').read_text())
        context.append(params['input'][0]['text'])
        (root / 'child-context.json').write_text(json.dumps(context))
        turn = {'id':'check-turn','status':'inProgress','items':[]}
        send({'id':request['id'],'result':{'turn':turn}})
        if options.get('wait_for_interrupt'):
            options['stopped'] = True
            continue
        if options.get('checker_hook_command'):
            import shlex, subprocess
            hook = subprocess.run(shlex.split(options['checker_hook_command']), input=json.dumps({
                'hook_event_name':'Stop','session_id':'shared-native-session',
                'turn_id':'check-turn','stop_hook_active':False,'model':'actual-model',
            }), text=True, capture_output=True, timeout=10)
            (root / 'checker-hook.json').write_text(hook.stdout)
        if options.get('tool_request'):
            send({'id':'checker-tool','method':'item/tool/call','params':{
                'threadId':options.get('tool_caller',params['threadId']),
                'turnId':'check-turn','callId':'checker-call','tool':'graphtraj',
                'arguments':options['tool_request']}})
            reply = json.loads(sys.stdin.readline())
            (root / 'tool-reply.json').write_text(json.dumps(reply))
        if options.get('usage'):
            send({'method':'thread/tokenUsage/updated','params':{
                'threadId':params['threadId'],'tokenUsage':options['usage']}})
        text = options.get('output',json.dumps({'status':'completed','reason':'All required tickets integrated.','nodes':[]}))
        send({'method':'item/completed','params':{'threadId':params['threadId'],'turnId':'check-turn',
              'item':{'id':'answer','type':'agentMessage','text':text}}})
        turn['status'] = 'completed'
        send({'method':'turn/completed','params':{'threadId':params['threadId'],'turn':turn}})
        if options.get('interrupt_during_check'): options['stopped'] = True
        continue
    send({'id':request['id'],'result':result})
    if method == 'turn/interrupt':
        send({'method':'turn/completed','params':{'threadId':params['threadId'],
              'turn':{'id':'check-turn','status':'interrupted','items':[]}}})
'''


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Adopt a host publicly; replace only its Codex wire peer."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    peer = tmp_path / 'peer.py'
    peer.write_text(PEER)
    (tmp_path / 'options.json').write_text('{}')
    monkeypatch.setenv('FINALIZE_TEST_ROOT', str(tmp_path))

    def connect(
        connection: dict,
        on_request: Callable[[CodexServerRequest], Awaitable[dict]] | None = None,
    ) -> CodexAppServer:
        """Retain the production Adapter while controlling its native transport."""
        return CodexAppServer(cwd=tmp_path, command=(sys.executable, str(peer)),
                              experimental_api=True, on_request=on_request)

    monkeypatch.setattr(finalize, 'proxy', connect)
    visible = []
    with bind(tmp_path, event_receiver=visible.append,
              recovery_reviewer=lambda proposal: {'decision': 'accept'}) as owning:
        owning.adopt_main('codex')
        yield tmp_path, owning, visible


def stop(host: tuple, **changes: object) -> dict:
    """Have the adopted owning host consume one native lifecycle event."""
    root, owning, _ = host
    return owning.finish_check(
        {'runtime': 'codex', 'session': 'main', 'codex_home': str(root)},
        {'hook_event_name': 'Stop', 'session_id': 'shared-native-session',
         'turn_id': 'main-turn', 'stop_hook_active': False, 'model': 'actual-model', **changes},
    )


def options(host: tuple, **values: object) -> None:
    """Set this controlled native peer's next response."""
    (host[0] / 'options.json').write_text(json.dumps(values))


def records(root: Path) -> list[Path]:
    """Read retained checker execution evidence after the public call."""
    return list((root / '.graphtraj/runner/sessions').glob('checker_*/execution.yml'))


@pytest.mark.parametrize('status,reason,nodes', [
    ('completed', 'Current goal is integrated.', []),
    ('waiting', 'Required child remains running.', ['237']),
    ('waiting', 'User approval pending.', ['238']),
    ('actionable', '237 is authorized; implement its unfinished checker.', ['237']),
])
def test_main_end_decision(host: tuple, status: str, reason: str, nodes: list[str]) -> None:
    """Return the native same-Main decision and actually deliver visible events."""
    root, owning, visible = host
    options(host, output=json.dumps({'status': status, 'reason': reason, 'nodes': nodes}))
    result = stop(host)
    if status == 'actionable':
        assert result['decision'] == 'block' and '237' in result['reason']
    else:
        assert 'pass:' in result['systemMessage']
    assert [message['alias'] for message in visible] == [owning.alias, owning.alias]
    assert visible[0]['message'].startswith('[GraphTraj hook: finish-check] start:')
    assert reason in visible[-1]['message']
    wire = [json.loads(line) for line in (root / 'wire.jsonl').read_text().splitlines()]
    fork = next(item['params'] for item in wire if item['method'] == 'thread/fork')
    assert fork == {'threadId': 'main', 'model': 'actual-model',
                    'modelProvider': 'actual-provider', 'excludeTurns': True}
    context = json.loads((root / 'child-context.json').read_text())
    assert context[:2] == ['original developer instructions', 'private context sentinel']
    assert len(context) == 3
    evidence = yaml.safe_load(records(root)[0].read_text())
    assert evidence['model'] == 'actual-model' and evidence['session'] == 'checker'
    assert [m['params']['threadId'] for m in wire if m['method'] == 'turn/start'] == ['checker']
    native = yaml.safe_load(records(root)[0].with_name('native.yml').read_text())
    assert native['parent'] == owning.alias


@pytest.mark.parametrize('values', [
    {'fork_error': True}, {'fork_model': 'wrong-model'}, {'child': 'main'},
    {'output': 'not JSON'},
    {'output': json.dumps({'status': 'actionable', 'reason': 'Unfinished', 'nodes': []})},
    {'output': json.dumps({'status': 'error', 'reason': 'Issue unreadable', 'nodes': []})},
    {'thread_status': None}, {'thread_status': {}}, {'thread_status': {'type': 'systemError'}},
    {'thread_status': {'type': 'unknown'}}, {'thread_status': {'type': 'notLoaded'}},
    {'turn_status': None}, {'turn_status': 'failed'}, {'turn_status': 'unknown'},
])
def test_failures_visible_and_bounded(host: tuple, values: dict) -> None:
    """Initialization, state, execution and parsing failures never silently skip."""
    options(host, **values)
    first = stop(host)
    assert first.get('decision') == 'block' or first.get('continue') is False
    assert 'failure:' in first.get('reason', first.get('systemMessage', ''))
    assert 'failure:' in host[2][-1]['message']
    # Errors before normalization must also respect the trusted continuation flag.
    second = stop(host, stop_hook_active=True)
    assert second['continue'] is False and 'failure:' in second['systemMessage']


@pytest.mark.parametrize('values', [
    {'stopped': True}, {'current_turn': 'another-turn'}, {'interrupt_during_check': True},
])
def test_stopped_or_changed_main_not_continued(host: tuple, values: dict) -> None:
    """A stopped or replaced native turn cannot be awakened by its old check."""
    options(host, **values)
    assert 'skip:' in stop(host)['systemMessage']
    assert 'skip:' in host[2][-1]['message']


@pytest.mark.parametrize('event', [{'turn_id': None}, {'model': None}, {'stop_hook_active': None},
                                   {'session_id': None}, {'hook_event_name': None},
                                   {'hook_event_name': 'unknown'}])
def test_missing_event_metadata_fails(host: tuple, event: dict) -> None:
    """Missing lifecycle metadata is a visible failure."""
    result = stop(host, **event)
    assert 'failure:' in result.get('reason', result.get('systemMessage', ''))


@pytest.mark.parametrize('feature,allowed', [('agent_identity', True), ('ticket_graph', True),
                                            ('send_instruction', False)])
def test_checker_uses_graphtraj_identity(host: tuple, feature: str, allowed: bool) -> None:
    """Actual native tool requests run as the registered checker, never native-ID Main."""
    options(host, tool_request={'action': 'execute', 'feature': feature, 'arguments': {}})
    stop(host)
    reply = json.loads((host[0] / 'tool-reply.json').read_text())['result']
    assert reply['success'] is allowed
    if feature == 'agent_identity':
        identity = json.loads(reply['contentItems'][0]['text'])
        assert identity['purpose'] == 'checker' and identity['parent'] == host[1].alias
        assert identity['alias'] != 'checker'


def test_checker_exclusion_does_not_read_native_metadata(host: tuple) -> None:
    """A registered checker is excluded before any native connection access."""
    with host[1].register_checker(host[2].append) as checker:
        assert checker.finish_check({}, {})['status'] == 'skip'
        assert 'GraphTraj checker' in host[2][-1]['message']
    assert not (host[0] / 'wire.jsonl').exists()


def test_unknown_identity_and_delivery_failure_are_explicit(host: tuple) -> None:
    """Missing identity and failed visible delivery propagate to the owning host."""
    with bind(host[0], event_receiver=host[2].append) as unknown:
        with pytest.raises(RunnerError, match='no active GraphTraj identity'):
            unknown.finish_check({}, {})
    assert 'failure:' in host[2][-1]['message']

    def broken(message: dict) -> None:
        """Represent the real host refusing visible message delivery."""
        raise OSError('receiver unavailable')

    host[1].receiver = broken
    with pytest.raises(RunnerError, match='delivery failed'):
        stop(host)


def test_standalone_legacy_hook_cannot_claim_identity(tmp_path: Path) -> None:
    """Actual CLI stdout/stderr visibly refuse a missing authenticated host."""
    reply = CliRunner().invoke(stop_hook, ['--binding', str(tmp_path / 'absent'),
                                        '--hook-session', 'old'], input='{}')
    assert reply.exit_code == 0
    assert '[GraphTraj hook: finish-check] start:' in reply.stderr
    result = json.loads(reply.stdout)
    assert result['continue'] is False
    assert 'failure:' in result['systemMessage'] and 'authenticate' in result['systemMessage']


def test_legacy_binding_does_not_mutate_records(host: tuple) -> None:
    """Old bindings neither redefine identity nor persist a mandatory task target."""
    with pytest.raises(RunnerError) as rejected:
        host[1]({'action': 'execute', 'feature': 'bind_main_finalize', 'arguments': {}})
    assert rejected.value.code == 'authority-denied'
    assert not (host[0] / '.graphtraj/runner/main-sessions').exists()


def test_actual_usage_is_retained(host: tuple) -> None:
    """Retain measured token accounting without inventing cache hits."""
    usage = {'last': {'inputTokens': 113, 'cachedInputTokens': 0, 'outputTokens': 19}}
    options(host, usage=usage)
    stop(host)
    assert yaml.safe_load(records(host[0])[0].read_text())['usage'] == usage


class ControlledAdapter:
    """A non-Codex host with inherited goals, opaque handles and visible decisions."""

    def __init__(self) -> None:
        """Keep current native conversation context independently of Issue hints."""
        self.goal = 'current-goal'
        self.model = 'actual-current-model'
        self.sources = {'current-goal': ['272'], 'next-goal': []}
        self.calls = []
        self.interrupted = False

    def verify_finalize_main(self, connection: dict) -> str:
        """Resolve only this native execution handle, not GraphTraj identity."""
        assert connection == {'runtime': 'controlled', 'endpoint': 'owned'}
        return 'opaque-owner'

    def finalize_event(self, binding: dict, event: dict) -> dict:
        """Normalize this host's non-Codex lifecycle."""
        assert event == {'end': True}
        return {'continued': False}

    def check_main_finalize(
        self, binding: dict, context: dict, prompt: str, created: Callable[[str], None],
    ) -> dict:
        """Model controlled checker behavior using the inherited current goal."""
        handle = f'opaque-child-{len(self.calls)}'
        created(handle)
        checker = binding['checker_tool']
        identity = checker({'action': 'execute', 'feature': 'agent_identity', 'arguments': {}})
        assert identity.document['purpose'] == 'checker'
        self.calls.append({'goal': self.goal, 'model': self.model, 'prompt': prompt,
                           'parent': identity.document['parent']})
        if self.interrupted:
            raise KeyboardInterrupt
        # This controlled peer implements task selection; it proves transport
        # independence, not a real model's ability to follow the supplied prompt.
        if self.goal not in self.sources:
            result = {'status': 'error', 'reason': 'Current goal unclear or sources unreadable.', 'nodes': []}
        else:
            nodes = self.sources[self.goal]
            result = {'status': 'actionable' if nodes else 'completed',
                      'reason': f'Current authoritative goal: {self.goal}', 'nodes': nodes}
        return {'session': handle, 'output': json.dumps(result), 'model': self.model}

    def finalize_response(self, result: dict | None, continued: bool) -> dict:
        """Return the decision in the other host's own lifecycle shape."""
        return {'end': result is None or result['status'] in ('completed', 'waiting'),
                'check': result}


def test_non_codex_current_task_changes_and_visible_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """No native Codex fields or fixed Issue binding enter the shared behavior."""
    configuration = tmp_path / '.graphtraj/config.yml'
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    adapter = ControlledAdapter()
    monkeypatch.setattr(main_finalize, 'select_runtime_adapter', lambda runtime: adapter)

    def display(message: dict) -> None:
        """Actually display host receiver output at its public terminal boundary."""
        print(message['message'], flush=True)

    with bind(tmp_path, event_receiver=display,
              recovery_reviewer=lambda proposal: {'decision': 'accept'}) as owning:
        alias = owning.adopt_main('controlled')
        connection = {'runtime': 'controlled', 'endpoint': 'owned'}
        first = owning.finish_check(connection, {'end': True}, summary_issue='stale-wrong-goal')
        assert first['end'] is False and first['check']['nodes'] == ['272']
        output = capsys.readouterr().out
        assert output.startswith('[GraphTraj hook: finish-check] start:')
        assert '[GraphTraj hook: finish-check] continue:' in output
        adapter.goal = 'next-goal'
        adapter.model = 'actual-next-model'
        second = owning.finish_check(connection, {'end': True}, summary_issue='current-goal')
        assert second['end'] is True and second['check']['status'] == 'completed'
        assert '[GraphTraj hook: finish-check] pass:' in capsys.readouterr().out
        assert owning.alias == alias
        assert [(c['goal'], c['model'], c['parent']) for c in adapter.calls] == [
            ('current-goal', 'actual-current-model', alias), ('next-goal', 'actual-next-model', alias),
        ]
        adapter.goal = 'unreadable'
        failed = owning.finish_check(connection, {'end': True})
        assert failed['check']['status'] == 'error' and failed['end'] is False
        assert '[GraphTraj hook: finish-check] failure:' in capsys.readouterr().out
        adapter.interrupted = True
        with pytest.raises(KeyboardInterrupt):
            owning.finish_check(connection, {'end': True})
        output = capsys.readouterr().out
        marker = '[GraphTraj hook: finish-check] skip:'
        assert marker in output
        assert output.split(marker, 1)[1].strip()
    assert len(records(tmp_path)) == 3


def test_unsupported_native_capability_is_visible(host: tuple) -> None:
    """A real unsupported Adapter reports a capability failure, never simulated success."""
    with bind(host[0], event_receiver=host[2].append,
              recovery_reviewer=lambda proposal: {'decision': 'accept'}) as owning:
        owning.adopt_main('pi')
        with pytest.raises(RunnerError, match='not supported'):
            owning.finish_check({'runtime': 'pi'}, {})
    assert 'failure:' in host[2][-1]['message']


def test_state_read_failure_is_visible(host: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure to read authoritative project state cannot become completion."""
    def unreadable(state: Path) -> dict:
        """Inject an unavailable task source at the existing shared graph boundary."""
        raise OSError('task graph unreadable')

    monkeypatch.setattr(main_finalize, 'read_graph', unreadable)
    response = stop(host)
    assert response['continue'] is False
    assert 'task graph unreadable' in response['stopReason']
    assert 'failure:' in host[2][-1]['message']


def test_native_stop_cancels_running_checker(host: tuple) -> None:
    """A real controlled wire interruption cancels the fork and cannot continue Main."""
    options(host, wait_for_interrupt=True)
    result = stop(host)
    assert 'skip:' in result['systemMessage']
    wire = [json.loads(line) for line in (host[0] / 'wire.jsonl').read_text().splitlines()]
    cancelled = [m['params'] for m in wire if m['method'] == 'turn/interrupt']
    assert cancelled == [{'threadId': 'checker', 'turnId': 'check-turn'}]
    assert 'skip:' in host[2][-1]['message']


def test_closed_owning_host_does_not_request_continuation(host: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing during native preparation cannot issue a new checker action."""
    from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter

    def close_owner(
        adapter: object,
        connection: dict,
        task_name: str,
        prompt: str,
        turn: str | None,
    ) -> dict:
        """Close the actual HostTool while its native preparation call is outstanding."""
        host[1].close()
        return {'session': 'main', 'turn': 'main-turn', 'input_ids': [], 'task_name': task_name}

    monkeypatch.setattr(CodexRuntimeAdapter, 'prepare_main_check', close_owner)
    response = stop(host)
    assert host[1].closed
    assert response['continue'] is False and 'decision' not in response
    assert 'failure:' in response['systemMessage']
    assert not records(host[0])


@pytest.mark.parametrize('event', [
    {'session_id': 'different'}, {'turn_id': 'checker-turn'},
    {'hook_event_name': 'Interrupt'}, {'hook_event_name': 'SubagentStop'},
])
def test_unrelated_native_events_do_not_fork(host: tuple, event: dict) -> None:
    """Transport filtering does not confuse a child turn with the owning Main turn."""
    assert 'skip:' in stop(host, **event)['systemMessage']
    wire = [json.loads(line) for line in (host[0] / 'wire.jsonl').read_text().splitlines()]
    assert not any(item['method'] == 'thread/fork' for item in wire)


def test_public_command_attaches_to_existing_authenticated_host(
    host: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepare then execute the generated native carrier on the same registered owner."""
    import os
    import shlex
    import subprocess
    from graphtraj.execution.runner_process import process_ancestors
    from graphtraj.interfaces.hosted_cli import CONNECTION_ENV

    root, owning, visible = host
    monkeypatch.setenv('CODEX_THREAD_ID', 'main')
    monkeypatch.setenv('CODEX_HOME', str(root))
    writers = []

    def authenticate(pid: int) -> None:
        """This controlled host owns the sole Agent and these direct subprocesses."""
        assert os.getpid() in process_ancestors(pid)
        writers.append(pid)

    with owning.cli_channel(authenticate) as address:
        environment = {**os.environ, CONNECTION_ENV: address,
                       'PYTHONPATH': str(Path(main_finalize.__file__).resolve().parents[2])}
        prepared = subprocess.run(
            [sys.executable, '-c', 'from graphtraj.interfaces.cli.graphtraj import main; main()',
             'bind-finalize'], cwd=root, env=environment, capture_output=True, text=True, timeout=15,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        document = json.loads(prepared.stdout)
        assert document['alias'] == owning.alias
        command = document['hook']['hooks']['Stop'][0]['hooks'][0]['command']
        event = {'hook_event_name': 'Stop', 'session_id': 'shared-native-session',
                 'turn_id': 'main-turn', 'stop_hook_active': False, 'model': 'actual-model'}
        options(host, output=json.dumps({'status': 'actionable', 'reason': 'Continue authorized272 work',
                                        'nodes': ['272']}))
        result = subprocess.run(shlex.split(command), input=json.dumps(event), cwd=root,
                                env=environment, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert '[GraphTraj hook: finish-check] start:' in result.stderr
        decision = json.loads(result.stdout)
        assert decision['decision'] == 'block' and '272' in decision['reason']
        assert '[GraphTraj hook: finish-check] continue:' in decision['reason']
        assert visible[-1]['alias'] == owning.alias
        assert len(writers) == 2 and writers[0] != writers[1]
        # The hook contains only an authenticated channel, never native identity.
        assert '--channel' in shlex.split(command) and '--hook-session' not in shlex.split(command)
        assert owning.alias == document['alias']
    # The retained command is not a credential after the genuine owner closes.
    result = subprocess.run(shlex.split(command), input=json.dumps(event), cwd=root,
                            env=environment, capture_output=True, text=True, timeout=15)
    assert json.loads(result.stdout)['continue'] is False
    assert '[GraphTraj hook: finish-check] failure:' in result.stdout


def test_command_hook_channel_rejects_foreign_writer(host: tuple) -> None:
    """Knowing the channel address never supplies its Agent identity."""
    import os
    import subprocess
    from graphtraj.interfaces.hosted_cli import CONNECTION_ENV

    def refuse(pid: int) -> None:
        """The owning host does not assign this writer to its Agent."""
        raise RunnerError('authority-denied', 'Writer is not assigned to this Agent.')

    with host[1].cli_channel(refuse) as address:
        environment = {**os.environ, CONNECTION_ENV: address,
                       'PYTHONPATH': str(Path(main_finalize.__file__).resolve().parents[2])}
        result = subprocess.run(
            [sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook'], input='{}',
            cwd=host[0], env=environment, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)['continue'] is False
        assert '[GraphTraj hook: finish-check] failure:' in result.stdout
        assert not (host[0] / 'wire.jsonl').exists()


@pytest.mark.parametrize('hosted_channel', [True, False])
def test_registered_checker_command_hook_skips(host: tuple, hosted_channel: bool) -> None:
    """A checker using its own authentic channel never reaches native fork execution."""
    import os
    import subprocess
    from graphtraj.execution.runner_process import process_ancestors
    from graphtraj.interfaces.hosted_cli import CONNECTION_ENV

    def authenticate(pid: int) -> None:
        """The controlled host assigns this sole subprocess to its checker."""
        assert os.getpid() in process_ancestors(pid)

    from graphtraj.interfaces.hosted_cli import cli_connection

    with host[1].register_checker(host[2].append) as checker:
        channel = (checker.cli_channel(authenticate) if hosted_channel else
                   cli_connection(host[0], checker.alias, {'agent_identity'}, authenticate=authenticate))
        with channel as address:
            environment = {**os.environ, CONNECTION_ENV: address,
                           'PYTHONPATH': str(Path(main_finalize.__file__).resolve().parents[2])}
            result = subprocess.run(
                [sys.executable, '-m', 'graphtraj.runtimes.codex.stop_hook',
                 '--channel', str(host[0] / 'foreign-root-channel')], input='{}',
                cwd=host[0], env=environment, capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0
            assert '[GraphTraj hook: finish-check] skip:' in json.loads(result.stdout)['systemMessage']
            assert not (host[0] / 'wire.jsonl').exists()
