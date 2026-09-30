"""An owning Python host receives events in its original native parent Session."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket
from test_task_budget_control import BODY


CHILD = r'''
import os, sys, time, subprocess, json
from pathlib import Path
if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
prompt = sys.stdin.read()
phase = 'later' if prompt == 'later' else 'initial'
Path(os.environ['HOST_TEST_ROOT'], phase + '-ready').touch()
while not Path(os.environ['HOST_TEST_ROOT'], phase + '-release').exists():
    time.sleep(.02)
if phase == 'initial':
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    command = [os.environ['HOST_RUNNER'], 'submit-result', '--commit', commit,
               '--result-ref', 'README.md', '--completion', 'host-owned result']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
raise SystemExit(int(os.environ['HOST_FAIL']) if phase == 'later' else 0)
'''

HOST = r'''
import asyncio, json, os, sys, time
from pathlib import Path
import yaml
from graphtraj.interfaces.local_tool import bind
from graphtraj.execution.execution_budget import budget_notice_output
from graphtraj.runtimes.codex.app_server import CodexAppServer

root, scratch, peer = map(Path, sys.argv[1:4])

class Context:
    """Retain this fixture host's legitimately owned native Session settings."""
    runtime = 'codex'
    def session_document(self):
        return {'runtime':'codex','adapter_request': {'cwd':str(root)}}
    def runtime_environment(self):
        return {}

async def main():
    """Use one existing connection and Session for all received child events."""
    loop = asyncio.get_running_loop()
    actions = []
    current = None
    waiting = None
    async with CodexAppServer(cwd=root, command=[str(peer)], experimental_api=True) as adapter:
        session = await adapter.create_session(Context())
        # This Session exists before GraphTraj binding or child launch.
        current = await adapter.start_execution(session, 'hold' if os.environ['HOST_ACTIVE']=='1' else 'ready')
        waiting = asyncio.create_task(adapter.wait(current))
        if os.environ['HOST_ACTIVE'] != '1':
            await waiting

        async def forward(event):
            """Forward over the original client and observe the native parent's action."""
            nonlocal current, waiting
            prompt = json.dumps(event)
            if waiting is not None and not waiting.done():
                await adapter.send_input(current, prompt)
            else:
                current = await adapter.start_execution(session, prompt)
                waiting = asyncio.create_task(adapter.wait(current))
            result = await waiting
            assert result['session_id'] == session.thread_id
            assert result['last_agent_message'] == 'handled:' + event['event']
            actions.append({'event':event, 'result':result})

        refused = False

        def receiver(event):
            """Enter the owning client's loop; no second client or Session is opened."""
            nonlocal refused
            if os.environ['HOST_MODE']=='stop' and event['event']=='execution-budget-exceeded' and not refused:
                refused=True
                raise RuntimeError('controlled host refusal')
            asyncio.run_coroutine_threadsafe(forward(event), loop).result(timeout=8)

        tool = bind(root, event_receiver=receiver)
        def call(feature, arguments):
            """Run public operations in a thread so the host client continues reading."""
            return tool({'action':'execute','feature':feature,'arguments':arguments}).document

        def launch():
            """Exercise both detached return and an original waiting call."""
            if os.environ['HOST_WAIT'] != '1':
                return call('swarm', {'tasks':[{'ticket_id':'76','role':'researcher','instruction':'request:'+os.environ['HOST_MODE'] if os.environ['HOST_MODE'] in {'approval','input'} else 'initial'}]})
            read_fd, write_fd = os.pipe()
            try:
                with budget_notice_output(write_fd):
                    return call('swarm', {'tasks':[{'ticket_id':'76','role':'researcher','instruction':'request:'+os.environ['HOST_MODE'] if os.environ['HOST_MODE'] in {'approval','input'} else 'initial'}]})
            finally:
                os.close(write_fd)
                os.close(read_fd)

        async def until(predicate):
            """Await fixture synchronization, never poll child reports for an event."""
            deadline=loop.time()+30
            while not predicate():
                assert loop.time()<deadline, actions
                await asyncio.sleep(.02)

        alias = None
        try:
            launched = asyncio.create_task(asyncio.to_thread(launch))
            if os.environ['HOST_MODE'] in {'approval','input'}:
                document=await launched
                alias=document['tasks'][0]['alias']
                await until(lambda:len(actions)==2)
                assert actions[0]['event']['event']==('item/commandExecution/requestApproval' if os.environ['HOST_MODE']=='approval' else 'item/tool/requestUserInput')
                terminal=json.loads(actions[1]['event']['message'].split('\n')[-1])
                assert terminal['last_agent_message']==('approval:accept' if os.environ['HOST_MODE']=='approval' else json.dumps({'answers': {'color': {'answers': ['blue']}}},sort_keys=True)),terminal
                (scratch/'host-evidence.json').write_text(json.dumps({'session':session.thread_id,'actions':actions}))
                return
            await until(lambda:(scratch/'initial-ready').exists())
            if os.environ['HOST_WAIT']=='1':
                assert not launched.done()
            else:
                document = await launched
                assert not actions, actions
            (scratch/'initial-release').touch()
            await until(lambda:any(a['event']['event']=='completed' for a in actions))
            document = await launched
            alias = document['tasks'][0]['alias']
            assert any(a['event']['event']=='result-submitted' for a in actions)
            if os.environ['HOST_ACTIVE']=='1':
                current = await adapter.start_execution(session, 'hold')
                waiting = asyncio.create_task(adapter.wait(current))
            events=[json.loads(line) for shard in (root/'.graphtraj/state/worldline').glob('*.jsonl')
                    for line in shard.read_text().splitlines()]
            def wrong_receiver(event):
                """A later caller cannot replace the original receiver binding."""
                raise AssertionError('event was reparented to a different host')
            other = bind(root,event_receiver=wrong_receiver)
            try:
                response = await asyncio.to_thread(other,{'action':'execute','feature':'send_instruction','arguments':{
                    'alias':alias,'instruction':'later','caused_by_event_ids':[events[-1]['event_id']]}})
                ack=response.document
            finally:
                await asyncio.to_thread(other.close)
            assert ack['send_status']=='sent',ack
            await until(lambda:(scratch/'later-ready').exists())
            assert len(actions)==2,actions
            if os.environ['HOST_MODE']=='stop':
                from graphtraj.execution.execution_budget import execution_budget_monitor
                from unittest.mock import patch
                evidence=root/'.graphtraj/state/tickets/76-session-alias-control'
                monitor=execution_budget_monitor(evidence,'76','session-alias-control')
                usage=yaml.safe_load((evidence/'execution-budget.yml').read_text())
                with patch('graphtraj.execution.execution_budget.time.time',return_value=usage['started_at']+1200), patch('graphtraj.execution.execution_budget.random.random',return_value=.999):
                    assert monitor.check('researcher','researcher')
                expected='interrupted'
            else:
                (scratch/'later-release').touch()
                expected='runtime-error' if os.environ['HOST_FAIL']=='1' else 'completed'
            await until(lambda:any(a['event']['event']==expected and ack['execution_id'] in a['event']['message'] for a in actions[2:]))
            if os.environ['HOST_MODE']=='stop':
                assert refused
                assert any(a['event']['event']=='execution-budget-exceeded' for a in actions)
            assert actions[-1]['event']['event']==expected
            details=json.loads(actions[-1]['event']['message'].split('\n')[-1])
            assert details['execution_id']==ack['execution_id']
            (scratch/'host-evidence.json').write_text(json.dumps({
                'session':session.thread_id,'actions':actions,'ack':ack,
                'during_wait':os.environ['HOST_WAIT']=='1'}))
        finally:
            (scratch/'initial-release').touch()
            (scratch/'later-release').touch()
            if alias:
                await asyncio.to_thread(call,'interrupt',{'alias':alias})
            await asyncio.to_thread(tool.close)

asyncio.run(main())
'''


@pytest.mark.parametrize('active,wait,failure,mode', [(True, True, False, 'normal'), (False, False, True, 'normal'), (False, False, False, 'stop'), (False, False, False, 'approval'), (True, False, False, 'input')])
def test_owning_host_processes_events_during_and_after_tool_call(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    active: bool,
    wait: bool,
    failure: bool,
    mode: str,
) -> None:
    """Original host Session acts on submission and post-return completion/failure."""
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    _register_ready_ticket(installed_commands, root, body=BODY)
    fake_codex.executable.write_text(app_server_peer(
        '#!' + sys.executable + '\n' + CHILD, "os.environ['GRAPHTRAJ_PARENT_ALIAS']",
    ))
    if mode in {'approval','input'}:
        child_peer=Path(__file__).with_name('managed_codex_peer.py').read_text().replace(
            "ask('permissions' if 'request:permissions' in prompt else 'approval')",
            "ask('input' if 'request:input' in prompt else 'approval')")
        fake_codex.executable.write_text('#!' + sys.executable + '\n' + child_peer)
    parent_peer = tmp_path / 'parent-peer'
    peer = Path(__file__).with_name('codex_stdio_peer.py').read_text()
    anchor = "def complete(thread_id: str, turn_id: str, text: str, status: str = 'completed') -> None:"
    # The controlled native parent performs a public Runner operation after
    # consuming input. It is not the host receiver callback asserting delivery.
    assert anchor in peer
    peer = peer.replace(anchor, anchor + r'''
    if text.startswith('{') and json.loads(text).get('source') == 'graphtraj':
        import subprocess
        event = json.loads(text)
        operation = 'reports' if event['event'] == 'result-submitted' else 'status'
        arguments=[operation,event['alias']]
        if event['event'] in {'item/commandExecution/requestApproval','item/tool/requestUserInput'}:
            operation='reply'
            import tempfile
            details=json.loads(event['message'].split('\n')[-1])
            with tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False) as target:
                json.dump(details,target)
            arguments=['reply',event['alias'],'--request-file',target.name,'--response',json.dumps({'decision':'accept'} if event['event'].endswith('requestApproval') else {'answers':{'color':{'answers':['blue']}}})]
        action = subprocess.run([os.environ['HOST_RUNNER'], *arguments],
                                cwd=os.environ['HOST_PROJECT'], capture_output=True, text=True)
        assert action.returncode == 0, action.stdout + action.stderr
        with open(os.environ['HOST_ACTIONS'], 'a') as stream:
            stream.write(json.dumps({'session':thread_id,'event':event['event'],
                                     'operation':operation,'output':action.stdout})+'\n')
        text = 'handled:' + event['event']
''')
    parent_peer.write_text('#!' + sys.executable + '\n' + peer)
    parent_peer.chmod(0o755)
    host = tmp_path / 'host.py'
    host.write_text(HOST)
    environment.pop('PYTHONPATH', None)
    environment.update({
        'CODEX_HOME':str(tmp_path/'native-home'), 'HOST_TEST_ROOT':str(tmp_path),
        'HOST_RUNNER':str(installed_commands.runner), 'HOST_PROJECT':str(root),
        'HOST_ACTIONS':str(tmp_path/'parent-actions.jsonl'), 'HOST_MODE':mode,
        'MANAGED_NATIVE_ROOT':str(tmp_path/'native'),
        'PEER_PROTOCOL_LOG':str(tmp_path/'parent-protocol.jsonl'),
        'HOST_ACTIVE':str(int(active)), 'HOST_WAIT':str(int(wait)), 'HOST_FAIL':str(int(failure)),
    })
    result = run_process([str(installed_commands.runner.with_name('python')), '-I', str(host),
                          str(root), str(tmp_path), str(parent_peer)],
                         cwd=root, env=environment, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence=json.loads((tmp_path/'host-evidence.json').read_text())
    actions=[json.loads(line) for line in (tmp_path/'parent-actions.jsonl').read_text().splitlines()]
    assert len(actions)==len(evidence['actions'])
    assert {a['session'] for a in actions}=={evidence['session']}
    assert [a['operation'] for a in actions][:2]==(['reply','status'] if mode in {'approval','input'} else ['reports','status'])
    protocol = [json.loads(line) for line in (tmp_path/'parent-protocol.jsonl').read_text().splitlines()]
    assert sum(r.get('method') == 'thread/start' for r in protocol) == 1
    assert not any(r.get('method') == 'thread/resume' for r in protocol)
    inputs = [r for r in protocol if r.get('method') in {'turn/start', 'turn/steer'}
              and r['params']['input'][0]['text'].startswith('{')]
    assert len(inputs) == len(actions)
    assert all(r['params']['threadId'] == evidence['session'] for r in inputs)
    assert any(r['method'] == 'turn/steer' for r in inputs) == active
    for request in inputs:
        event = json.loads(request['params']['input'][0]['text'])
        assert set(event) == {'source', 'alias', 'event', 'message'}
        assert event['source'] == 'graphtraj'
