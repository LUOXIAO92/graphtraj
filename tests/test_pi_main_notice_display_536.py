"""536: a GraphTraj Pi Main gets each queued notice as the shared notice text, drawn as who + Markdown.

GraphTraj queues Main notices itself (main_continuity.queue_notice), as for Claude in 533. The model
reads ``graftling.notice_text`` (title with execution, ``Facts`` with request ID and token); Pi draws
``agents · <sender> · <event>`` over the Markdown body instead of ``[graphtraj:main-notice]`` and an
end record as escaped JSON.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from graphtraj.execution.main_continuity import current_main, queue_notice
from test_external_session_entry import native, project  # noqa: F401
from test_pi_dsh_main_continuity import as_pi

REPLY = '## Reply from n536\n\n- one `agents`\n- two\n\n> quoted "line"'
EXTENSION = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/pi/extension.mjs'
SCRIPT = '''
import { pathToFileURL } from 'node:url';
const [module, cwd, piEntry] = process.argv.slice(1);
const { deliverNotices } = await import(pathToFileURL(module).href);
const { loadHostSdk, registerNoticeDisplay } = await import(pathToFileURL(
  process.env.GRAFTLING_EXTENSION).href);
const sdk = await loadHostSdk(piEntry);
sdk.initTheme();
const renderers = {}, sent = [];
const pi = { registerMessageRenderer: (type, renderer) => { renderers[type] = renderer; },
  sendMessage: (message, options) => sent.push({ message, options }) };
registerNoticeDisplay(pi, sdk, 'graphtraj:main-notice');
const environment = { GRAFTLING_NATIVE_RUNTIME: 'pi', GRAFTLING_NATIVE_SESSION: process.env.GRAFTLING_NATIVE_SESSION,
  GRAFTLING_NATIVE_SESSION_FILE: process.env.GRAFTLING_NATIVE_SESSION_FILE };
const count = await deliverNotices(pi, { cwd }, environment);
const drawn = sent.map(({ message }) => renderers[message.customType]?.(message, { expanded: false, outputPad: 1 })
  ?.render(70).join('\\n').replace(/\\x1b\\[[0-9;]*m/g, '') ?? null);
console.log(JSON.stringify({ count, sent, drawn }));
'''


def queue_two(runner: Path, connection: dict) -> None:
    """An end and a native permission request, as GraphTraj's notify_direct_parent queues them."""
    end = {'session': 's1', 'execution_id': 'exec-1', 'outcome': 'completed', 'terminal_confirmed': True,
           'session_id': 's1', 'permissions': {'requested': 'auto', 'matches_request': True},
           'last_agent_message': REPLY}
    queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'n536@advisor', 'event': 'completed',
                                      'message': 'Session execution ended:\n' + json.dumps(end, ensure_ascii=False),
                                      'execution': 'exec-1'})
    request = {'session': 's2', 'execution_id': 'exec-2', 'request_id': 'req-9', 'request_token': 'tok-7',
               'method': 'claude/can_use_tool', 'params': {'tool_name': 'Bash', 'input': {'command': 'ls'}}}
    queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'w@engineer', 'event': 'claude/can_use_tool',
                                      'message': 'Claude requires a native permission reply:\n' + json.dumps(request),
                                      'execution': 'exec-2', 'request_id': 'req-9'})


def test_pi_main_receives_notice_text_and_draws_who_and_markdown(
    project: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    node, pi = shutil.which('node'), shutil.which('pi')
    if node is None or pi is None:
        pytest.skip('Node and an installed Pi are required')
    import graftling

    assert native('pi', as_pi(project, monkeypatch, 'pi-main')) == {'source': 'main'}
    runner = project / '.graphtraj/runner'
    queue_two(runner, current_main(runner)['connection'])
    environment = {**os.environ, 'PATH': f'{Path(sys.executable).parent}{os.pathsep}{os.environ["PATH"]}',
                   'GRAFTLING_EXTENSION': str(Path(graftling.__file__).parent / 'pi/extension.mjs')}
    result = subprocess.run([node, '--input-type=module', '-e', SCRIPT, str(EXTENSION), str(project), pi],
                            cwd=project, env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    shown = json.loads(result.stdout)
    assert shown['count'] == 2 and len(shown['sent']) == 2
    end, request = (item['message'] for item in shown['sent'])
    assert all(item['options'] == {'triggerTurn': True, 'deliverAs': 'followUp'} for item in shown['sent'])
    # The model input: the shared title with the execution, the Markdown, and the Facts line.
    assert end['content'].startswith('[Graftling notice from n536@advisor · completed · execution exec-1]\n')
    assert REPLY in end['content']
    assert end['content'].splitlines()[-1] == 'Facts: execution_id `exec-1` · outcome `completed`'
    assert request['content'].splitlines()[-1] == ('Facts: execution_id `exec-2` · request_id `req-9` · '
                                                   'request_token `tok-7` · method `claude/can_use_tool`')
    for text in (end['content'], request['content']):
        for dropped in ('permissions', 'terminal_confirmed', '\\n', '\\"'):
            assert dropped not in text
    assert end['details'] == {'sender': 'n536@advisor', 'event': 'completed', 'body': REPLY, 'source': 'graphtraj'}
    # What the user sees: who and the rendered Markdown, no type label, title, Facts or JSON.
    drawn_end, drawn_request = shown['drawn']
    lines = [line.strip() for line in drawn_end.splitlines() if line.strip()]
    assert lines[0] == '[subagents · n536@advisor · completed]'
    assert 'Reply from n536' in lines[1] and '- one agents' in lines and not re.search(r'##|`|Facts|\{', drawn_end)
    assert drawn_request.splitlines()[2].strip() == '[subagents · w@engineer · claude/can_use_tool]'
    assert 'graphtraj:main-notice' not in drawn_end + drawn_request
    # Acknowledged once Pi took them.
    assert native('pi', {'event': 'notices'})['notices'] == 0
