"""Each queued notice reaches a Claude Main once: by the mod's push or with a result."""

from pathlib import Path
from uuid import uuid4

from agent_swarm import AgentControl
from agent_swarm.claude.host import IndependentCalls
from graphtraj.execution.main_continuity import queue_notice
from graphtraj.runtimes.claude.host import MainNotices, NativeCalls, main_calls
from test_agent_control import ScriptedDriver


def test_result_leaves_notices_a_push_holds_and_delivers_released_ones(tmp_path: Path) -> None:
    """A result never repeats a notice the push read; a failed push hands it back."""
    runner  = tmp_path / '.graphtraj/runner'
    session = str(uuid4())
    notices = MainNotices(runner)
    host    = NativeCalls(lambda session, cwd: None, tmp_path, notices)
    control = AgentControl(tmp_path / '.graphtraj/swarm', {'claude': ScriptedDriver()})
    call    = main_calls(tmp_path, control, None, notices)(session, tmp_path)
    discover = {'action': 'discover'}

    # The push read the notice before the result was built: only the push delivers it.
    queue_notice(runner, {'runtime': 'claude', 'session': session}, {'alias': 'leader@l1', 'message': 'ended'})
    pending = host.context({'operation': 'notices', 'session': session})
    assert [item['event']['alias'] for item in pending['notices']] == ['leader@l1']
    assert 'main_notices' not in call('tasks', discover).document
    host.context({'operation': 'acknowledge', 'session': session, 'position': pending['position']})
    assert 'main_notices' not in call('tasks', discover).document
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []

    # A failed submission releases the notice to the next result, once.
    queue_notice(runner, {'runtime': 'claude', 'session': session}, {'alias': 'leader@l2', 'message': 'ended'})
    assert host.context({'operation': 'notices', 'session': session})['notices']
    host.context({'operation': 'release', 'session': session})
    delivered = call('tasks', discover).document['main_notices']
    assert [item['event']['alias'] for item in delivered] == ['leader@l2']
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    assert 'main_notices' not in call('tasks', discover).document


def test_independent_result_leaves_notices_a_push_holds(tmp_path: Path) -> None:
    """The standalone host applies the same single delivery to its own queue."""
    host    = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    session = str(uuid4())
    call    = host.make_call(session, tmp_path)
    host.queue[session] = [{'event': {'alias': 'a@1', 'event': 'completed', 'message': 'done'}}]

    pending = host.context({'operation': 'notices', 'session': session})
    assert len(pending['notices']) == 1
    assert 'main_notices' not in call('agents', {'action': 'discover'}).document
    host.context({'operation': 'release', 'session': session})
    assert len(call('agents', {'action': 'discover'}).document['main_notices']) == 1
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []


def test_mod_releases_notices_when_submission_fails(tmp_path: Path) -> None:
    """The mod hands read notices back when Claude refused its prompt submission."""
    import subprocess

    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/agent_swarm/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const operations = [], timers = [];
const pending = {notices: [{at: 1, event: {alias: 'leader@l1', event: 'completed', message: 'done'}}], position: 1};
const host = {
 session: {id: async () => 'main-session'},
 command: {register: async () => {}},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   const document = JSON.parse(options.stdin);
   operations.push(document.operation);
   return {exitCode: 0, stdout: JSON.stringify(document.operation === 'notices' ? pending : {}), stderr: ''};
 }},
 prompt: {submit: async () => { const error = new Error('busy'); error.name = 'HooksError'; throw error; }},
 clock: {setTimeout: (fn) => timers.push(fn)},
 ui: {log: () => {}},
};
await handlers.get('session.start')(host, {}, async () => 'started');
await timers.shift()();
assert.deepEqual(operations, ['notices', 'release']);
assert.equal(timers.length, 1);
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
