"""Opt-in installed-product DSH model check; never part of default development runs."""

import json
import os
from pathlib import Path
import sys
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.environ.get('TASK334_OFFICIAL_DSH') != '1', reason='Requires assigned official host slot.')
def test_installed_dsh_model_mcp_and_same_session(tmp_path: Path) -> None:
    """Use the public Agents API and actual installed DSH, with no controlled peer."""
    from agent_swarm import AgentControl, Caller, bind
    from agent_swarm.dsh import DshDriver

    assert os.environ.get('DEEPSEEK_API_KEY'), 'The existing named credential must be available.'
    driver = DshDriver(tmp_path, {
        'model': 'deepseek-flash', 'reasoning_effort': None, 'sandbox': 'workspace-write',
        'base_url': 'https://api.deepseek.com/anthropic', 'api_key_env': 'DEEPSEEK_API_KEY',
        'mcp': {'command': sys.executable, 'args': ['-I', '-m', 'agent_swarm.mcp']},
    })
    control = AgentControl(tmp_path / 'agents', {'dsh': driver})
    call = bind(control, Caller('official-validation', None))
    created = call({'action': 'create', 'runtime': 'dsh', 'instruction':
        'Remember marker DSH334-cobalt. Use the agents MCP tool: discover status, describe status '
        'with schema=true, then execute status. Do not use shell tools. Reply with the marker.'})
    assert not created.failed, created.document
    agent, session = created.document['agent'], created.document['session']
    try:
        done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 90})
        assert not done.failed, done.document
        result = done.document['result']
        assert result['state'] == 'standby', result
        assert result['last_result']['outcome'] == 'completed', result
        assert 'DSH334-cobalt' in result['last_result']['last_message'], result
        trace = tmp_path / 'agents/native' / agent / 'trace.jsonl'
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        calls = [row['data'] for row in rows if row.get('type') == 'tool/call']
        assert len([item for item in calls if item['name'] == 'mcp__agents__agents']) >= 3, calls
        resumed = call({'action': 'resume', 'agent': agent, 'message': 'What marker did I ask you to remember? Reply only with it.'})
        assert not resumed.failed and resumed.document['session'] == session, resumed.document
        recalled = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 90})
        assert recalled.document['result']['state'] == 'standby', recalled.document
        assert 'DSH334-cobalt' in recalled.document['result']['last_result']['last_message'], recalled.document
        print(json.dumps({'agent': agent, 'session': session, 'trace': str(trace),
                          'mcp_calls': len(calls), 'model_turns': 2}))
    finally:
        # Stop only this test's active execution; retain its identity and history.
        state = call({'action': 'status', 'agent': agent})
        if state.document.get('result', {}).get('state') == 'active':
            call({'action': 'interrupt', 'agent': agent})
            call({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})


@pytest.mark.skipif(not os.environ.get('TASK334_DSH_TRACE'), reason='Requires one explicitly retained native trace.')
def test_retained_official_trace_messages(tmp_path: Path) -> None:
    """Compare the actual native projection and JSONL archive without more turns."""
    from agent_swarm.sessions.dsh import collect_jsonl
    from agent_swarm.sessions.archive import SessionArchive

    trace = Path(os.environ['TASK334_DSH_TRACE'])
    header, *events = [json.loads(line) for line in trace.read_text().splitlines()]
    archive = SessionArchive(tmp_path / 'archive', save_normalized_sessions=True)
    collect_jsonl(archive, header, [{'event': row} for row in events])
    store = archive.store('dsh:' + header['id'])
    native = subprocess.run([
        shutil.which('node'), str(Path(__file__).parent / 'fixtures/dsh_compare_trace.mjs'),
        str(Path(shutil.which('dsh')).resolve()), str(trace),
    ], capture_output=True, text=True, check=True, timeout=10)
    assert store.messages() == json.loads(native.stdout)
    assert [row['graphtraj']['native']['record'] for row in store.page(limit=1000)['events']] == events
    print(json.dumps({'native_session': header['id'], 'events': len(events),
                      'messages': len(store.messages()), 'native_projection_equal': True}))


@pytest.mark.skipif(os.environ.get('TASK334_FINAL_DSH') != '1', reason='Requires final assigned host slot.')
def test_actual_client_interrupt_and_memory(tmp_path: Path) -> None:
    """Capture the official browser and interrupt one real tool before resuming."""
    import time
    from playwright.sync_api import sync_playwright
    from agent_swarm import AgentControl, Caller, bind
    from agent_swarm.dsh import DshDriver

    driver = DshDriver(tmp_path, {
        'model': 'deepseek-flash', 'reasoning_effort': None, 'sandbox': 'workspace-write',
        'base_url': 'https://api.deepseek.com/anthropic', 'api_key_env': 'DEEPSEEK_API_KEY',
        'mcp': {'command': sys.executable, 'args': ['-I', '-m', 'agent_swarm.mcp']},
    })
    control = AgentControl(tmp_path / 'agents', {'dsh': driver})
    call = bind(control, Caller('official-final-validation', None))
    created = call({'action': 'create', 'runtime': 'dsh', 'instruction':
        'Remember marker DSH334-amber. Use agents MCP execute status with empty arguments once. '
        'Then use bash to execute sleep 45. This harmless wait is an authorized interruption test. '
        'Do not ask questions, create agents, or change files. After the wait reply with the marker.'})
    assert not created.failed, created.document
    agent, session = created.document['agent'], created.document['session']
    pids = []
    try:
        turn = driver.turns[created.document['execution']]
        pids.append(turn.service.process.pid)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            with turn.lock:
                sleeping = any(item['tool'] == 'bash' and 'sleep 45' in str(item['arguments'])
                               for item in turn.tool_calls.values())
            if sleeping:
                break
            assert not turn.finished.is_set(), 'Native execution ended before the interruption target.'
            time.sleep(.05)
        assert sleeping, 'No native active bash call observed.'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(Path.home() /
                'Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'))
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_cookies([{'name': item.split('=', 1)[0], 'value': item.split('=', 1)[1],
                                     'url': turn.service.origin} for item in turn.service.cookie.split('; ')])
                page = context.new_page()
                page.goto(turn.service.origin, wait_until='networkidle', timeout=20000)
                page.screenshot(path=str(tmp_path / 'official-client.png'), full_page=True)
                (tmp_path / 'official-client.txt').write_text(page.locator('body').inner_text())
            finally:
                browser.close()
        stopped = call({'action': 'interrupt', 'agent': agent})
        assert not stopped.failed, stopped.document
        ended = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
        assert ended.document['result']['last_result']['outcome'] == 'interrupted', ended.document
        resumed = call({'action': 'resume', 'agent': agent, 'message':
                        'The interruption test is finished. What marker did I ask you to remember? Reply only with it. Do not call tools.'})
        assert not resumed.failed and resumed.document['session'] == session, resumed.document
        pids.append(driver.turns[resumed.document['execution']].service.process.pid)
        recalled = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 60})
        assert 'DSH334-amber' in recalled.document['result']['last_result']['last_message'], recalled.document
        trace = tmp_path / 'agents/native' / agent / 'trace.jsonl'
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        tools = next(row['data']['header']['tools'] for row in rows if row.get('type') == 'request/header')
        (tmp_path / 'initial-tools.json').write_text(json.dumps(tools, indent=2))
        names = [item['name'] for item in tools]
        assert len(names) == len(set(names))
        assert [name for name in names if name.startswith('mcp__')] == ['mcp__agents__agents']
        assert 'agents' not in names and 'graphtraj' not in names
        entry = next(item for item in tools if item['name'] == 'mcp__agents__agents')
        assert set(entry['parameters']['properties']) <= {'action', 'query', 'feature', 'schema', 'arguments'}
        print(json.dumps({'agent': agent, 'session': session, 'dsh_executions': 2,
                          'pi_executions': 0, 'runtime_pids': pids, 'initial_tools': names,
                          'active_interrupt': True, 'same_session_memory': True, 'evidence': str(tmp_path)}))
    finally:
        state = call({'action': 'status', 'agent': agent}).document['result']
        if state['state'] == 'active':
            call({'action': 'interrupt', 'agent': agent})
            call({'action': 'wait', 'agent': agent, 'timeout_seconds': 30})
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)


@pytest.mark.skipif(not os.environ.get('TASK334_INTERRUPTED_ROOT'), reason='Requires retained interrupted official Session.')
def test_continue_actual_interrupted_session() -> None:
    """Resume the interrupted execution through public control, without repeating it."""
    from agent_swarm import AgentControl, Caller, bind
    from agent_swarm.dsh import DshDriver

    root = Path(os.environ['TASK334_INTERRUPTED_ROOT'])
    # Read only the explicitly assigned validation Agent's own retained record.
    record = json.loads(next((root / 'control/agents').glob('*.json')).read_text())
    assert record['executions'][-1]['outcome'] == 'interrupted'
    driver = DshDriver(root.parent, {})  # Resume uses retained settings, not a new prepare.
    call = bind(AgentControl(root, {'dsh': driver}), Caller('official-final-validation', None))
    resumed = call({'action': 'resume', 'agent': record['agent'], 'message':
        'The interruption test is finished. What marker did I ask you to remember? Reply only with it. Do not call tools.'})
    assert not resumed.failed and resumed.document['session'] == record['session'], resumed.document
    pid = driver.turns[resumed.document['execution']].service.process.pid
    try:
        done = call({'action': 'wait', 'agent': record['agent'], 'timeout_seconds': 60})
        result = done.document['result']
        assert result['state'] == 'standby' and result['last_result']['outcome'] == 'completed', done.document
        assert 'DSH334-amber' in result['last_result']['last_message'], done.document
        print(json.dumps({'agent': record['agent'], 'session': record['session'],
                          'execution': resumed.document['execution'], 'runtime_pid': pid,
                          'active_interrupt_then_memory': True, 'additional_dsh_executions': 1}))
    finally:
        state = call({'action': 'status', 'agent': record['agent']}).document['result']
        if state['state'] == 'active':
            call({'action': 'interrupt', 'agent': record['agent']})
            call({'action': 'wait', 'agent': record['agent'], 'timeout_seconds': 30})
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.skipif(not os.environ.get('TASK334_DSH_TRACE'), reason='Requires one explicitly retained native trace.')
def test_actual_initial_tool_catalog() -> None:
    """Inspect the complete tools sent in the actual first model request."""
    rows = [json.loads(line) for line in Path(os.environ['TASK334_DSH_TRACE']).read_text().splitlines()]
    tools = next(row['data']['header']['tools'] for row in rows if row.get('type') == 'request/header')
    names = [item['name'] for item in tools]
    assert len(names) == len(set(names))
    assert [name for name in names if name.startswith('mcp__')] == ['mcp__agents__agents']
    assert 'agents' not in names and 'graphtraj' not in names
    entry = next(item for item in tools if item['name'] == 'mcp__agents__agents')
    assert set(entry['parameters']['properties']) <= {'action', 'query', 'feature', 'schema', 'arguments'}
    assert not entry['parameters']['properties']['arguments'].get('properties')
    print(json.dumps({'actual_initial_tool_names': names, 'project_mcp_entries': 1,
                      'subfunction_schemas_in_initial_tools': False}))


@pytest.mark.skipif(not os.environ.get('TASK334_CROSS_ROOT'), reason='Requires fixed Pi combination and final host slot.')
def test_actual_pi_reply_resumes_standby_dsh() -> None:
    """Use the existing verified controller caller for one Pi child and its reply."""
    import time
    from agent_swarm import AgentControl, Caller, bind
    from agent_swarm.dsh import DshDriver
    from graphtraj.runtimes.pi.driver import PiDriver

    assert time.time() < float(os.environ['TASK334_UI_DEADLINE']), 'The authorized UI window has ended.'
    root = Path(os.environ['TASK334_CROSS_ROOT'])
    agent_id = 'agent-55a851da1900487193f749f3c4c34847'
    expected_session = 'session-e873e3ae-e177-4a06-9550-e2fdf8eaf5c6'
    phases = []
    handoff = Path('/private/tmp/task334-ui-final')
    handoff.mkdir(exist_ok=True)

    def configure(turn, run) -> None:
        """Hold only service cleanup briefly so the official client can capture it."""
        started = turn.started

        def ready(session: str, pid: int) -> None:
            close = turn.service.close

            def capture_then_close() -> None:
                phase = len(phases) + 1
                phases.append({'execution': run.execution, 'session': session, 'pid': pid})
                path = handoff / f'phase-{phase}.json'
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    json.dump({'origin': turn.service.origin, 'cookie': turn.service.cookie,
                               'session': session}, stream)
                (handoff / f'phase-{phase}.origin').write_text(turn.service.origin)
                print(f'UI phase {phase}: {turn.service.origin}', flush=True)
                deadline = float(os.environ['TASK334_UI_DEADLINE'])
                while not (handoff / f'phase-{phase}.done').exists() and time.time() < deadline:
                    time.sleep(.1)
                close()
            turn.service.close = capture_then_close
            started(session, pid)
        turn.started = ready

    driver = DshDriver(root.parent, {}, configure=configure)
    # The common controller passes its verified Runtime caller to prepare;
    # no model field or manually constructed Pi caller chooses the parent.
    prepared = json.loads(Path('/private/tmp/graphtraj-333-preflight/host-config.json').read_text())['adapter_request']
    prepared['worktree_path'] = str(root.parent)
    pi = PiDriver(prepared)
    control = AgentControl(root, {'dsh': driver, 'pi': pi})
    call = bind(control, Caller('official-final-validation', None))
    status = call({'action': 'status', 'agent': agent_id})
    record = status.document.get('result', {})
    if (status.failed or record.get('agent') != agent_id or record.get('runtime') != 'dsh'
            or record.get('session') != expected_session):
        error_path = handoff / 'status-error.json'
        error_path.write_text(json.dumps(status.document, indent=2))
        pytest.fail(f'The fixed DSH Agent/Session status did not match; retained at {error_path}')

    def pi_children() -> list[dict]:
        """Read only the fixed parent's direct Pi children through public status."""
        visible = call({'action': 'status'})
        assert not visible.failed, visible.document
        return [child for node in visible.document['result']['agents']
                if node['agent'] == agent_id for child in node.get('children', [])
                if child.get('parent') == agent_id and child.get('runtime') == 'pi']

    def execution_ids(child: dict) -> set[str]:
        """Include both active and last-ended IDs without relying on event time."""
        return {value for value in (child.get('execution'), child.get('last_result', {}).get('id'))
                if value is not None}

    baseline_ids = {value for child in pi_children() for value in execution_ids(child)}
    (handoff / 'child-execution-baseline.json').write_text(json.dumps(sorted(baseline_ids)))
    resumed = call({'action': 'resume', 'agent': agent_id, 'message':
        'Current host facts: this authorized Main test host differs from the earlier engineering '
        'execution context. Evidence /private/tmp/task334-main-host-preflight.json records the unchanged '
        'Pi sandbox policy wrapping /usr/bin/true, returncode=0, policy_unchanged=true, model_requests=0. '
        'This proves only the sandbox preflight, not complete Pi startup or model success. '
        'Keep the sandbox and all history. One create attempt on this current host is now authorized. '
        'Use agents MCP describe create schema=true then execute create exactly once with runtime pi. '
        'Child instruction: "Use bash to run sleep 180, then reply exactly PI334-REPLY. Do not spawn agents or edit files." '
        'After create returns, reply exactly WAITING and end your turn immediately. Do not call wait/status. '
        'When the child reply later arrives, reply ACK PI334-REPLY and the marker I asked you to remember.'})
    assert not resumed.failed, resumed.document
    try:
        deadline = float(os.environ['TASK334_UI_DEADLINE'])
        while time.time() < deadline:
            state = call({'action': 'status', 'agent': record['agent']}).document['result']
            children = [child for child in pi_children() if execution_ids(child) - baseline_ids]
            new_ids = {value for child in children for value in execution_ids(child)} - baseline_ids
            assert len(new_ids) <= 1, {'unexpected_new_child_executions': sorted(new_ids)}
            if len(phases) >= 2 and state['state'] == 'standby':
                break
            if len(phases) == 1 and state['state'] == 'standby':
                assert children, {'no_new_child_execution': state, 'baseline_ids': sorted(baseline_ids)}
                failed = [child for child in children
                          if child.get('last_result', {}).get('id') in new_ids
                          and child['last_result'].get('outcome') == 'failed']
                assert not failed, {'current_child_execution_failed': failed}
            time.sleep(.2)
        assert len(phases) == 2, {'phases': phases, 'state': state}
        assert len(children) == 1 and len(new_ids) == 1, children
        child = children[0]
        child_result = child.get('last_result', {})
        assert child_result.get('id') in new_ids and child_result.get('outcome') == 'completed', child
        assert child.get('session'), child
        assert phases[0]['execution'] == resumed.document['execution'], phases
        assert phases[1]['execution'] == state['last_result']['id'] != phases[0]['execution'], phases
        assert all(phase['session'] == expected_session for phase in phases), phases
        assert state['session'] == record['session']
        assert 'PI334-REPLY' in state['last_result']['last_message'], state
        assert 'DSH334-amber' in state['last_result']['last_message'], state
        trace = root / 'native' / record['agent'] / 'trace.jsonl'
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        replies = [row for row in rows if row.get('type') == 'user/message'
                   and row['data'].get('source', {}).get('kind') == 'agent-message'
                   and row['data']['source'].get('communicationId') == child_result['id']]
        assert len(replies) == 1, replies
        source = replies[0]['data']['source']
        assert source.get('senderSessionId') == child['session'], source
        assert source.get('senderAgentId') == child['agent'], source
        assert source.get('recipientAgentId') == agent_id, source
        print(json.dumps({'phases': phases, 'native_reply_count': 1, 'standby_reply_processed': True,
                          'child_agent': child['agent'], 'child_session': child['session'],
                          'child_execution': child_result['id'], 'baseline_ids': sorted(baseline_ids),
                          'additional_dsh_executions': 2, 'pi_executions': 1}))
    finally:
        for path in handoff.glob('phase-*.json'):
            path.with_suffix('.done').touch()
        hierarchy = call({'action': 'status'}).document['result']['agents']
        for node in hierarchy:
            for target in [*node.get('children', []), node]:
                if target.get('state') == 'active':
                    call({'action': 'interrupt', 'agent': target['agent']})
                    call({'action': 'wait', 'agent': target['agent'], 'timeout_seconds': 20})
        for path in handoff.glob('phase-*.json'):
            path.unlink(missing_ok=True)
