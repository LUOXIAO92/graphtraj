/** Pure browser-view projection: no host/model calls and no UI acceptance claim. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [clientPath, nativePackage] = process.argv.slice(2);
const require = createRequire(nativePackage);
const { SlotCore } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-client-ui-slots')));
let module;
vm.runInNewContext(readFileSync(clientPath, 'utf8'), { window: { __ModuleLoader__: {
  load(definition) { module = definition; },
} } });
assert.equal(module.id, 'agents-dsh');
const views = module.factory(name => {
  assert.equal(name, 'react');
  return { createElement: (tag, props, ...children) => ({ tag, props, children }) };
});
const slots = new SlotCore();
slots.register({ name: 'root', children: {
  'tool.call.toolview': { kind: 'keyed', scope: 'session' },
  'conversation.chat.node': { kind: 'keyed', scope: 'session' },
} }, () => null);
function NativeTrigger(props) { return props.node.data.content; }
const registerNative = () => slots.register({ name: 'conversation.chat.node', key: 'turn-trigger', locale: 'chat' }, NativeTrigger);
const delayedNative = process.argv[4] === 'delayed';
if (!delayedNative) registerNative();
views.apply({ slots: {
  inject(name, callback) { callback(); },
  entriesOfSlot: name => slots.entriesOfSlot(name),
  subscribe: (name, callback) => slots.subscribe(name, callback),
  register: (options, component) => slots.register(options, component),
} });
if (delayedNative) {
  registerNative();
  await new Promise(resolve => queueMicrotask(resolve));
}
const registered = slots.entriesOfSlot('tool.call.toolview')[0];
assert.equal(registered.options.key, 'mcp__agents__agents');
const block = { kind: 'tool-result', call: { argsRaw: JSON.stringify({
  action: 'execute', feature: 'send', arguments: { agent: 'actual-child', message: 'outbound body' },
}) }, content: [{ type: 'text', text: JSON.stringify({ agent: 'actual-child', result: {
  state: 'standby', last_result: { last_message: 'relay owns this incoming body' },
} }) }] };
const before = JSON.stringify(block);
const first = registered.component({ block, sessionId: 'actual-parent-session', phase: 'result' });
const replay = registered.component({ block, sessionId: 'actual-parent-session', phase: 'result' });
assert.equal(JSON.stringify(first), JSON.stringify(replay));
assert.equal(JSON.stringify(block), before);
const rendered = JSON.stringify(first);
assert.match(rendered, /actual-parent-session → actual-child/);
assert.match(rendered, /outbound body/);
assert.doesNotMatch(rendered, /relay owns this incoming body/);
console.log('Pure native Tool view: outbound source/body; incoming relay not duplicated');

// Real native slot selection keeps the original renderer under our attribution.
const incoming = slots.entriesOfSlot('conversation.chat.node')
  .find(entry => entry.options.key === 'turn-trigger');
assert.notEqual(incoming.component, NativeTrigger);
assert.equal(incoming.locale, 'chat');
const source = Object.freeze({ kind: 'agent-message', form: 'relay',
  senderSessionId: 'actual-pi-session', senderAgentId: 'actual-pi-agent',
  recipientAgentId: 'actual-parent-agent', communicationId: 'actual-child-execution' });
const node = Object.freeze({ kind: 'turn-trigger', data: Object.freeze({
  source, seq: 47, time: 12345,
  content: Object.freeze([{ type: 'text', text: 'native reply body' }]),
}) });
const props = Object.freeze({ node, sessionId: 'actual-parent-session' });
const retained = JSON.stringify(props);
const received = incoming.component(props);
assert.equal(received.props['data-agent-incoming'], source.communicationId);
assert.equal(received.children.at(-1).tag, NativeTrigger);
assert.equal(received.children.at(-1).props, props);
const presentation = JSON.stringify(received);
for (const value of [source.senderSessionId, source.senderAgentId,
  source.recipientAgentId, props.sessionId]) assert.ok(presentation.includes(value));
assert.equal(presentation.match(/native reply body/g).length, 1);
assert.equal(JSON.stringify(incoming.component(props)), presentation);
assert.equal(JSON.stringify(props), retained);
for (const other of [{ kind: 'goal' }, { kind: 'agent-message', senderSessionId: 'runtime-only' }]) {
  const unchanged = { ...props, node: { ...node, data: { ...node.data, source: other } } };
  const original = incoming.component(unchanged);
  assert.equal(original.tag, NativeTrigger);
  assert.equal(original.props, unchanged);
}
console.log('Native keyed slot: true sender/recipient, one unchanged body, other triggers delegated');
