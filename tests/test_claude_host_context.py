"""Native mod contract checks; actual load and screen evidence stay separate."""
from pathlib import Path
import subprocess


def test_native_context_is_per_call_and_permissions_are_unchanged(tmp_path: Path) -> None:
    """Current host facts bind each MCP call; rendering never adds model input."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/agent_swarm/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {
 const key = fn && matcher.tool ? `${name}:${matcher.tool}` : name;
 handlers.set(key, fn ?? matcher); return {catch() {}};
});
let session = 'first', fail = false;
const contexts = [], log = [], registrations = [];
const host = {
 session: {id: async () => session, cwd: async () => '/native/current'},
 command: {register: async entry => registrations.push(entry)},
 tool: {list: async () => [{name: 'mcp__agents__agents'}]},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   assert.deepEqual(argv, ['/venv/python', '-m', 'agent_swarm.claude.host', 'context', '--config', '/host/config']);
   contexts.push(JSON.parse(options.stdin));
   return {exitCode: fail ? 1 : 0, stdout: '{}', stderr: fail ? 'native owner unavailable' : ''};
 }},
 clock: {setTimeout: () => {}},
 ui: {log: value => log.push(value)},
};
await handlers.get('session.start')(host, {}, async () => 'started');
assert.equal(registrations[0].name, 'agents-context');
assert.deepEqual(await handlers.get('command.run')(host), {});
assert.ok(log.includes('MCP agents registered') && log.includes('MCP tasks missing'));
assert.ok(log.at(-1).includes('notice push: waiting'));
const input = {action: 'execute', feature: 'send', arguments: {agent: 'agent-child', message: 'hello child\nsecond line'}};
for (session of ['first', 'after-clear', 'resumed']) {
 for (const decision of ['allow', 'ask', 'deny']) {
  const native = {decision, reason: 'native reason', ceiling: 'ask'};
  const before = contexts.length;
  const result = await handlers.get('tool.check:mcp__agents__agents')(host, {tool: 'mcp__agents__agents', input}, async () => native);
  assert.equal(result, native);
  if (decision === 'deny') assert.equal(contexts.length, before);
  else assert.deepEqual(contexts.at(-1), {operation: 'prepare', tool: 'agents', session, cwd: '/native/current', agent: null, request: input});
 }
}
// tasks uses the same per-call association, naming its own entry.
const task = {action: 'execute', feature: 'task_graph', arguments: {}};
await handlers.get('tool.check:mcp__agents__tasks')(host, {tool: 'mcp__agents__tasks', input: task}, async () => ({decision: 'allow'}));
assert.deepEqual(contexts.at(-1), {operation: 'prepare', tool: 'tasks', session, cwd: '/native/current', agent: null, request: task});
const taskChild = await handlers.get('tool.check:mcp__agents__tasks')(host, {agentId: 'native-child', input: task}, async () => ({decision: 'allow'}));
assert.equal(taskChild.decision, 'deny');
const count = contexts.length;
const child = await handlers.get('tool.check:mcp__agents__agents')(host, {agentId: 'native-child', input}, async () => ({decision: 'allow'}));
assert.equal(child.decision, 'deny');
assert.equal(contexts.length, count);
fail = true;
const broken = await handlers.get('tool.check:mcp__agents__agents')(host, {input}, async () => ({decision: 'ask'}));
assert.equal(broken.decision, 'deny');
fail = false;
const event = {tool: 'mcp__agents__agents', ...input};
const document = {agent: 'agent-child', execution: 'execution-one', result: {last_result: {id: 'execution-one', last_message: 'hello parent'}}};
const native = {result: [{type: 'text', text: JSON.stringify(document)}]};
// A resumed plugin has no in-memory display receipts. A new execution's
// status includes the previous last_result, which is not its new reply.
const stale = {result: [{type: 'text', text: JSON.stringify({...document, execution: 'execution-two'})}]};
await handlers.get('tool.call:mcp__agents__agents')(host, {...event, feature: 'status', arguments: {}}, async () => stale);
assert.equal(log.filter(line => line.includes('hello parent')).length, 0);
const returned = await handlers.get('tool.call:mcp__agents__agents')(host, event, async received => {
 assert.equal(received, event);
 const concurrent = await handlers.get('tool.call:mcp__agents__agents')(host, event, async () => assert.fail('overlap'));
 assert.ok(concurrent.deny);
 return native;
});
assert.equal(returned, native);
assert.ok(log.some(line => line.includes('resumed → agent-child')));
assert.ok(log.some(line => line.includes('agent-child → resumed')));
assert.ok(log.includes('│ hello child'));
assert.ok(log.includes('│ second line'));
assert.equal(event.arguments.message, 'hello child\nsecond line');
assert.ok(log.includes('│ hello parent'));
assert.ok(log.every(line => !line.includes('\n') && !line.includes('\r')));
assert.deepEqual(contexts.at(-1), {operation: 'end'});
const replies = log.filter(line => line.includes('│ hello parent')).length;
await handlers.get('tool.call:mcp__agents__agents')(host, {...event, feature: 'status', arguments: {}}, async () => native);
assert.equal(log.filter(line => line.includes('│ hello parent')).length, replies);
// A queued member notice arrives with the next tasks result and is shown once.
const queued = {main_notices: [{at: 1, event: {source: 'graphtraj', alias: 'leader@l1', event: 'completed', message: 'Session execution ended'}}]};
await handlers.get('tool.call:mcp__agents__tasks')(host, {tool: 'mcp__agents__tasks', ...task}, async () => ({result: [{type: 'text', text: JSON.stringify(queued)}]}));
assert.ok(log.includes('┌ agents · leader@l1 → resumed'));
assert.ok(log.includes('│ Session execution ended'));
let ended = false;
await handlers.get('session.end')(host, {reason: 'clear'}, async () => {ended = true;});
assert.equal(ended, true);
assert.deepEqual(contexts.at(-1), {operation: 'end'});
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_queued_notices_are_pushed_into_main_then_acknowledged(tmp_path: Path) -> None:
    """The mod claims pending notices, submits them once and returns them on a failed submit."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/agent_swarm/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const operations = [], submitted = [], timers = [];
let fail = true;
const pending = {notices: [{at: 1, id: 'e1:completed', event: {source: 'graphtraj', alias: 'leader@l1', event: 'completed', message: 'done'}}], position: 0};
const host = {
 session: {id: async () => 'main-session', cwd: async () => '/p'},
 command: {register: async () => {}},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   const document = JSON.parse(options.stdin);
   operations.push(document);
   const reply = document.operation === 'notices' ? pending : {requeued: 1};
   return {exitCode: 0, stdout: JSON.stringify(reply), stderr: ''};
 }},
 prompt: {submit: async input => {
   if (fail) { const error = new Error('takes { text } (a string)'); error.name = 'HooksError'; throw error; }
   assert.deepEqual(Object.keys(input), ['text']);
   assert.equal(typeof input.text, 'string');
   submitted.push(input.text);
 }},
 clock: {setTimeout: (fn) => timers.push(fn)},
 ui: {log: () => {}},
};
await handlers.get('session.start')(host, {}, async () => 'started');
await timers.shift()();
assert.equal(submitted.length, 0);
// A failed submission returns the claimed notices; the loop keeps running.
assert.deepEqual(operations.at(-1), {operation: 'requeue', session: 'main-session', ids: ['e1:completed']});
assert.equal(timers.length, 1);
fail = false;
await timers.shift()();
assert.equal(submitted.length, 1);
assert.ok(submitted[0].includes('leader@l1') && submitted[0].includes('done'));
assert.deepEqual(operations.at(-1), {operation: 'notices', session: 'main-session'});
assert.equal(timers.length, 1);
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
