"""Native mod callback semantics without claiming an actual interactive load."""
from pathlib import Path
import subprocess


def test_native_context_is_per_call_and_permissions_are_unchanged(tmp_path: Path) -> None:
    """Exercise the source module with the documented host API and no Runtime."""
    # Node resolves ancestor metadata before loading; package the authorized
    # source as a test plugin under pytest's own directory.
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/graphtraj/runtimes/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => handlers.set(name, fn ?? matcher));
let session = 'first';
let registrations = [];
let log = [];
const host = {
 session: {id: async () => session, cwd: async () => '/native/current'},
 command: {register: async entry => registrations.push(entry)},
 tool: {list: async () => [{name: 'mcp__agents__agents'}]},
 ui: {log: value => log.push(value)},
};
let started = 0;
await handlers.get('session.start')(host, {}, async () => {started++; return 'native-start';});
assert.equal(started, 1);
assert.equal(registrations[0].name, 'agents-context');
assert.deepEqual(await handlers.get('command.run')(host), {});
assert.equal(JSON.parse(log.at(-1)).registered, true);
for (const decision of ['allow', 'ask', 'deny']) {
 const native = {decision, reason: 'native reason', ceiling: 'ask'};
 const event = {tool: 'mcp__agents__agents', agentId: 'native-child', ceiling: 'ask'};
 const returned = await handlers.get('tool.check')(host, event, async received => {
   assert.equal(received, event); return native;
 });
 assert.equal(returned, native);
 assert.equal(JSON.parse(log.at(-1)).agentId, 'native-child');
}
for (session of ['first', 'after-clear', 'resumed']) {
 const event = {tool: 'mcp__agents__agents', action: 'status', session_id: 'model-spoof'};
 const native = {deny: 'native refused', isError: true};
 let called = 0;
 const returned = await handlers.get('tool.call')(host, event, async received => {
   called++; assert.equal(received, event); return native;
 });
 assert.equal(called, 1);
 assert.equal(returned, native);
 assert.equal(JSON.parse(log.at(-1)).session, session);
 assert.equal(JSON.parse(log.at(-1)).denied, true);
}
const event = {tool: 'mcp__agents__agents', action: 'send', message: 'hello child'};
const document = {agent: 'agent-child', result: {last_result: {id: 'execution-one', last_message: 'hello parent'}}};
const native = {result: [{type: 'text', text: JSON.stringify(document)}]};
const returned = await handlers.get('tool.call')(host, event, async () => native);
assert.equal(returned, native);
assert.ok(log.at(-2).includes('resumed → agent-child\n│ hello child'));
assert.ok(log.at(-1).includes('agent-child → resumed\n│ hello parent'));
const previousReplies = log.filter(line => line.includes('│ hello parent')).length;
await handlers.get('tool.call')(host, {tool: event.tool, action: 'status'}, async () => native);
assert.equal(log.filter(line => line.includes('│ hello parent')).length, previousReplies);
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
