"""538: a GraphTraj DSH Main gets each queued notice as its own relay from the member that ended.

Before 538 the DSH plugin sent all pending notices as one relay whose sender agent and session were both
'graphtraj', so graftling-dsh's browser module printed 'graphtraj' twice (and the Main's own session twice).
Now each notice is one relay: the sender is the member's alias, the model reads ``graftling.notice_text``
(title with the execution, the Markdown content, the Facts line with request ID and token), and graftling-dsh
draws who · event over the Markdown body.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from graphtraj.execution.main_continuity import current_main
from test_external_session_entry import dsh_session, native, project  # noqa: F401
from test_pi_main_notice_display_536 import REPLY, queue_two

TOOL = Path(__file__).resolve().parents[1] / 'src/graphtraj/runtimes/dsh/tool.mjs'
SCRIPT = '''
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
const [module, cwd] = process.argv.slice(1);
const { deliverNotices } = await import(pathToFileURL(module).href);
const sent = [];
const agent = { session: { id: 'dsh-main', header: { cwd } },
  send: (message, queue, wake) => sent.push({ message, queue, wake }) };
// The same native entry the plugin's apply() closes over.
const entry = (agent, event) => new Promise((resolve, reject) => {
  const child = spawn('graphtraj-session', ['dsh'], { cwd, env: { ...process.env,
    DSH_SESSION_ID: agent.session.id, DSH_GRAPHTRAJ_SESSION: agent.session.id, DSH_GRAPHTRAJ_SOURCE: 'main' } });
  let output = '';
  child.stdout.on('data', value => { output += value; });
  child.on('close', () => { const result = JSON.parse(output); result.error ? reject(new Error(result.error)) : resolve(result); });
  child.stdin.end(JSON.stringify(event));
});
const first = await deliverNotices(agent, entry);
const again = await deliverNotices(agent, entry);
console.log(JSON.stringify({ first, again, sent }));
'''


def test_dsh_main_gets_one_relay_per_notice_from_the_member(
    project: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    node = shutil.which('node')
    if node is None or shutil.which('dsh') is None:
        pytest.skip('Node and the installed DSH are required')
    dsh_session(monkeypatch, 'dsh-main')
    header = {'version': 4, 'id': 'dsh-main', 'isSeeded': False, 'cwd': str(project)}
    assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': header}) == {'source': 'main'}
    runner = project / '.graphtraj/runner'
    queue_two(runner, current_main(runner)['connection'])
    environment = {**os.environ, 'PATH': f'{Path(sys.executable).parent}{os.pathsep}{os.environ["PATH"]}',
                   'GRAPHTRAJ_DSH_PACKAGE': str(Path(shutil.which('dsh')).resolve()),
                   'GRAFTLING_DSH_PACKAGE': str(Path(shutil.which('dsh')).resolve())}
    result = subprocess.run([node, '--input-type=module', '-e', SCRIPT, str(TOOL), str(project)],
                            cwd=project, env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    shown = json.loads(result.stdout)
    assert (shown['first'], shown['again']) == (2, 0)          # delivered once, then acknowledged
    end, request = (item['message'] for item in shown['sent'])
    assert all(item['queue'] == 'next-step' and item['wake'] is True for item in shown['sent'])
    # Who sent it: the member's alias as agent and session (graftling-dsh prints an equal pair once),
    # to this Main's session; each relay has its own communication id.
    for message, alias in ((end, 'n536@advisor'), (request, 'w@engineer')):
        assert message['source'] == {'kind': 'agent-message', 'form': 'relay', 'senderSessionId': alias,
                                     'senderAgentId': alias, 'recipientAgentId': 'dsh-main',
                                     'communicationId': message['source']['communicationId']}
    assert end['source']['communicationId'] != request['source']['communicationId']
    # What the model reads: the shared notice text, the ids it needs included.
    text, asked = end['content'][0]['text'], request['content'][0]['text']
    assert text.startswith('[Graftling notice from n536@advisor · completed · execution exec-1]\n\n')
    assert REPLY in text and text.splitlines()[-1] == 'Facts: execution_id `exec-1` · outcome `completed`'
    assert asked.splitlines()[-1] == ('Facts: execution_id `exec-2` · request_id `req-9` · '
                                      'request_token `tok-7` · method `claude/can_use_tool`')
    assert 'graphtraj' not in json.dumps([end['source'], request['source']])
