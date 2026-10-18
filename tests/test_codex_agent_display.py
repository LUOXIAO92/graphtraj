"""The native hook CLI renders successful communication without model feedback."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def invoke(event: dict, directory: Path) -> dict:
    """Run the installed module entry with a native-shaped stdin document."""
    result = subprocess.run([
        sys.executable, '-m', 'graphtraj.runtimes.codex.display_hook',
        '--state-directory', str(directory),
    ], input=json.dumps(event), capture_output=True, text=True, check=True,
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
    return json.loads(result.stdout)


def event() -> dict:
    """Provide actual request/result fields consumed by the PostToolUse contract."""
    return {
        'hook_event_name': 'PostToolUse', 'session_id': 'native-session', 'tool_use_id': 'call-1',
        'tool_name': 'mcp__graphtraj__agents',
        'tool_input': {'action': 'execute', 'feature': 'create', 'arguments': {'instruction': 'Remember red.'}},
        'tool_response': {'isError': False, 'structuredContent': {
            'action': 'create', 'agent': 'agent-child', 'result': {'name': 'reader',
                'last_result': {'id': 'execution-1', 'outcome': 'completed', 'last_message': 'Remembered red.'}},
        }},
    }


def test_display_is_ui_only_and_deduplicated_across_hook_processes(tmp_path: Path) -> None:
    """One send and reply render once; later polls cannot replay the same reply."""
    source = event()
    original = copy.deepcopy(source)
    shown = invoke(source, tmp_path)
    assert set(shown) == {'systemMessage'}
    text = shown['systemMessage']
    assert 'Codex session native-session → reader [agent-child]' in text
    assert 'reader [agent-child] → Codex session native-session' in text
    assert 'Remember red.' in text and 'Remembered red.' in text
    assert source == original
    assert invoke(source, tmp_path) == {}
    source['tool_use_id'] = 'poll-2'
    source['tool_input'] = {'action': 'execute', 'feature': 'status', 'arguments': {'agent': 'agent-child'}}
    source['tool_response']['structuredContent']['action'] = 'status'
    assert invoke(source, tmp_path) == {}
    assert all('Remember' not in path.read_text() for path in tmp_path.glob('*.yml'))
    source['session_id'] = 'another-native-session'
    assert 'Remembered red.' in invoke(source, tmp_path)['systemMessage']


@pytest.mark.parametrize('kind', ['failure', 'discovery', 'stop', 'other-tool', 'empty-reply'])
def test_unrelated_and_cancelled_operations_add_no_chat_entry(tmp_path: Path, kind: str) -> None:
    """This observer never turns rejected, irrelevant or empty results into messages."""
    source = event()
    if kind == 'failure':
        source['tool_response']['isError'] = True
    elif kind == 'discovery':
        source['tool_input'] = {'action': 'discover'}
    elif kind == 'stop':
        source['hook_event_name'] = 'Stop'
    elif kind == 'other-tool':
        source['tool_name'] = 'mcp__other__agents'
    else:
        source['tool_input'] = {'action': 'execute', 'feature': 'interrupt', 'arguments': {'agent': 'agent-child'}}
        source['tool_response']['structuredContent']['result']['last_result']['last_message'] = None
    assert invoke(source, tmp_path) == {}
    assert not list(tmp_path.iterdir())


def test_retained_ordinary_receipt_is_shown_once_at_the_next_hook(tmp_path: Path) -> None:
    """A completed child end the Main did not start is shown, never sent as a turn."""
    from graphtraj.execution.runner_control import retain_parent_receipt
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    child = runner / 'sessions/research@x1'
    import yaml

    mapping = yaml.safe_load((child / 'mapping.yml').read_text())
    connection = {'runtime': 'codex', 'session': 'main-session', 'codex_home': str(tmp_path)}
    (child / 'mapping.yml').write_text(yaml.safe_dump({**mapping, 'parent_connection': connection}))
    retain_parent_receipt(child, 'Session execution ended:\n{"outcome": "completed"}',
                          {'type': 'completed', 'session': 'native-research@x1', 'execution_id': 'e1'})
    stop = {'hook_event_name': 'Stop', 'session_id': 'main-session', 'cwd': str(tmp_path)}

    shown = invoke(stop, tmp_path / 'display')
    assert set(shown) == {'systemMessage'}
    assert 'research@x1 → Codex session main-session' in shown['systemMessage']
    assert 'Session execution ended' in shown['systemMessage']
    assert invoke(stop, tmp_path / 'display') == {}
    assert invoke({**stop, 'session_id': 'other-main'}, tmp_path / 'display') == {}
