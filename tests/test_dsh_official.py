"""Opt-in installed-product DSH model check; never part of default development runs."""

import json
import os
from pathlib import Path
import sys

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
