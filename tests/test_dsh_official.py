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
    from graphtraj.runtimes.dsh.collection import collect_jsonl
    from graphtraj.sessions.archive import SessionArchive

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
