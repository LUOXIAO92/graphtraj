"""Native mod contract checks; actual load and screen evidence stay separate."""
from pathlib import Path
import subprocess


def test_native_context_is_per_call_and_permissions_are_unchanged(tmp_path: Path) -> None:
    """Current host facts bind each MCP call; rendering never adds model input."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/graphtraj/runtimes/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(name, fn ?? matcher); return {catch() {}};});
let session = 'first', fail = false;
const contexts = [], log = [], registrations = [];
const host = {
 session: {id: async () => session, cwd: async () => '/native/current'},
 command: {register: async entry => registrations.push(entry)},
 tool: {list: async () => [{name: 'mcp__agents__agents'}]},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   assert.deepEqual(argv, ['/venv/python', '-m', 'graphtraj.runtimes.claude.host', 'context', '--config', '/host/config']);
   contexts.push(JSON.parse(options.stdin));
   return {exitCode: fail ? 1 : 0, stdout: '{}', stderr: fail ? 'native owner unavailable' : ''};
 }},
 ui: {log: value => log.push(value)},
};
await handlers.get('session.start')(host, {}, async () => 'started');
assert.equal(registrations[0].name, 'agents-context');
assert.deepEqual(await handlers.get('command.run')(host), {});
assert.ok(log.at(-1).includes('MCP agents registered'));
const input = {action: 'execute', feature: 'send', arguments: {agent: 'agent-child', message: 'hello child\nsecond line'}};
for (session of ['first', 'after-clear', 'resumed']) {
 for (const decision of ['allow', 'ask', 'deny']) {
  const native = {decision, reason: 'native reason', ceiling: 'ask'};
  const before = contexts.length;
  const result = await handlers.get('tool.check')(host, {tool: 'mcp__agents__agents', input}, async () => native);
  assert.equal(result, native);
  if (decision === 'deny') assert.equal(contexts.length, before);
  else assert.deepEqual(contexts.at(-1), {operation: 'prepare', session, cwd: '/native/current', agent: null, request: input});
 }
}
const count = contexts.length;
const child = await handlers.get('tool.check')(host, {agentId: 'native-child', input}, async () => ({decision: 'allow'}));
assert.equal(child.decision, 'deny');
assert.equal(contexts.length, count);
fail = true;
const broken = await handlers.get('tool.check')(host, {input}, async () => ({decision: 'ask'}));
assert.equal(broken.decision, 'deny');
fail = false;
const event = {tool: 'mcp__agents__agents', ...input};
const document = {agent: 'agent-child', execution: 'execution-one', result: {last_result: {id: 'execution-one', last_message: 'hello parent'}}};
const native = {result: [{type: 'text', text: JSON.stringify(document)}]};
// A resumed plugin has no in-memory display receipts. A new execution's
// status includes the previous last_result, which is not its new reply.
const stale = {result: [{type: 'text', text: JSON.stringify({...document, execution: 'execution-two'})}]};
await handlers.get('tool.call')(host, {...event, feature: 'status', arguments: {}}, async () => stale);
assert.equal(log.filter(line => line.includes('hello parent')).length, 0);
const returned = await handlers.get('tool.call')(host, event, async received => {
 assert.equal(received, event);
 const concurrent = await handlers.get('tool.call')(host, event, async () => assert.fail('overlap'));
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
await handlers.get('tool.call')(host, {...event, feature: 'status', arguments: {}}, async () => native);
assert.equal(log.filter(line => line.includes('│ hello parent')).length, replies);
let ended = false;
await handlers.get('session.end')(host, {reason: 'clear'}, async () => {ended = true;});
assert.equal(ended, true);
assert.deepEqual(contexts.at(-1), {operation: 'end'});
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
