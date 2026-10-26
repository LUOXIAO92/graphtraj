"""Each queued notice reaches a Claude Main once: by the mod's push or with a result."""

from pathlib import Path
import subprocess
from uuid import uuid4

from agent_swarm import AgentControl
from agent_swarm.claude.host import IndependentCalls
from graphtraj.execution.main_continuity import queue_notice
from graphtraj.runtimes.claude.host import MainNotices, NativeCalls, main_calls
from test_agent_control import ScriptedDriver


def graphtraj_host(tmp_path: Path):
    """Return a GraphTraj host's mod channel, one Main call and a notice queuer."""
    runner  = tmp_path / '.graphtraj/runner'
    session = str(uuid4())
    notices = MainNotices(runner)
    control = AgentControl(tmp_path / '.graphtraj/swarm', {'claude': ScriptedDriver()})
    call    = main_calls(tmp_path, control, None, notices)(session, tmp_path)

    def queue(alias: str) -> None:
        """Queue one member completion for this Main."""
        queue_notice(runner, {'runtime': 'claude', 'session': session}, {'alias': alias, 'message': 'ended'})

    return NativeCalls(lambda session, cwd: None, tmp_path, notices), session, \
        lambda: call('tasks', {'action': 'discover'}).document, queue


def independent_host(tmp_path: Path):
    """Return the standalone host's mod channel, one Main call and a notice queuer."""
    host    = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    session = str(uuid4())
    call    = host.make_call(session, tmp_path)

    def queue(alias: str) -> None:
        """Queue one member completion as the host's event receiver does."""
        host.queue.setdefault(session, []).append({'event': {'alias': alias, 'event': 'completed', 'message': 'ended'}})

    return host, session, lambda: call('agents', {'action': 'discover'}).document, queue


def aliases(notices: list[dict]) -> list[str]:
    """Return the notice senders in order."""
    return [item['event']['alias'] for item in notices]


def check_single_delivery(host, session: str, result, queue) -> None:
    """Drive one host through result, push, idle push and refused push deliveries."""
    def push() -> dict:
        """Read pending notices as the mod's push does."""
        return host.context({'operation': 'notices', 'session': session})

    # A tool result takes an earlier notice; the push then finds nothing to repeat.
    queue('a@1')
    assert aliases(result()['main_notices']) == ['a@1']
    assert push()['notices'] == []

    # Main is idle afterwards: a later completion is pushed, once.
    queue('b@2')
    claimed = push()
    assert aliases(claimed['notices']) == ['b@2']
    assert 'main_notices' not in result()
    assert push()['notices'] == []

    # A submission still pending never holds back the next completion.
    queue('c@3')
    assert aliases(push()['notices']) == ['c@3']
    host.context({'operation': 'acknowledge', 'session': session, 'position': claimed['position']})

    # A refused submission hands its notices back, delivered once afterwards.
    queue('d@4')
    refused = push()
    host.context({'operation': 'release', 'session': session, 'position': refused['position']})
    assert aliases(result()['main_notices']) == ['d@4']
    assert push()['notices'] == []
    assert 'main_notices' not in result()


def test_graphtraj_host_delivers_each_notice_once(tmp_path: Path) -> None:
    """The project host gives every completion to exactly one channel."""
    check_single_delivery(*graphtraj_host(tmp_path))


def test_independent_host_delivers_each_notice_once(tmp_path: Path) -> None:
    """The standalone host applies the same single delivery to its own queue."""
    check_single_delivery(*independent_host(tmp_path))


def run_mod(tmp_path: Path, program: str) -> None:
    """Run ``program`` against the shipped mod with a scripted Claude host."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/agent_swarm/claude/host_context.mjs').read_text())
    prelude = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const operations = [], timers = [], submitted = [];
let batches = [], submit = async (input) => { submitted.push(input.text); };
const host = {
 session: {id: async () => 'main-session'},
 command: {register: async () => {}},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   const document = JSON.parse(options.stdin);
   operations.push(document);
   const reply = document.operation === 'notices' ? (batches.shift() ?? {notices: [], position: 0}) : {};
   return {exitCode: 0, stdout: JSON.stringify(reply), stderr: ''};
 }},
 prompt: {submit: (input) => submit(input)},
 clock: {setTimeout: (fn) => timers.push(fn)},
 ui: {log: () => {}},
};
const tick = async () => { for (const fn of timers.splice(0)) await fn(); };
const batch = (alias, position) => ({notices: [{at: 1, event: {alias, event: 'completed', message: alias}}], position});
await handlers.get('session.start')(host, {}, async () => 'started');
'''
    result = subprocess.run(['node', '--input-type=module', '-e', prelude + program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_mod_releases_notices_when_submission_fails(tmp_path: Path) -> None:
    """The mod hands claimed notices back when Claude refused its prompt submission."""
    run_mod(tmp_path, r'''
batches = [batch('a@1', 1)];
submit = async () => { const error = new Error('busy'); error.name = 'HooksError'; throw error; };
await tick();
assert.deepEqual(operations.map(item => item.operation), ['notices', 'release']);
assert.equal(operations[1].position, 1);
assert.ok(timers.length >= 1);
''')


def test_mod_keeps_waking_the_idle_main_after_a_held_submission(tmp_path: Path) -> None:
    """A submission Claude holds does not stop the next completion from being pushed."""
    run_mod(tmp_path, r'''
let settle;
batches = [batch('a@1', 1)];
submit = (input) => { submitted.push(input.text); return new Promise((resolve) => { settle = resolve; }); };
const first = timers.splice(0).map((fn) => fn());   // claims a@1; its submission stays pending
await new Promise((resolve) => setImmediate(resolve));
await tick();          // the bounded wait ends
await Promise.all(first);                           // and the next push is scheduled
batches = [batch('b@2', 2)];
submit = async (input) => { submitted.push(input.text); };
await tick();          // the idle Main still receives b@2
assert.equal(submitted.length, 2);
assert.ok(submitted[1].includes('b@2'));
settle();
await new Promise((resolve) => setImmediate(resolve));
await new Promise((resolve) => setImmediate(resolve));
const reports = operations.filter(item => item.operation === 'acknowledge').map(item => item.position).sort();
assert.deepEqual(reports, [1, 2]);
assert.ok(!operations.some(item => item.operation === 'release'));
''')
