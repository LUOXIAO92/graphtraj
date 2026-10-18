/** Pure browser-view projection: no host/model calls and no UI acceptance claim. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [clientPath] = process.argv.slice(2);
let module;
vm.runInNewContext(readFileSync(clientPath, 'utf8'), { window: { __ModuleLoader__: {
  load(definition) { module = definition; },
} } });
assert.equal(module.id, 'agents-dsh');
const views = module.factory(name => {
  assert.equal(name, 'react');
  return { createElement: (tag, props, ...children) => ({ tag, props, children }) };
});
let registered;
views.apply({ slots: {
  inject(name, callback) { assert.equal(name, 'tool.call.toolview'); callback(); },
  register(options, component) { registered = { options, component }; },
} });
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
