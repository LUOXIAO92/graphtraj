const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

/** Compile the real component, replacing only the already-tested UI library shell. */
async function components(t) {
  const folder = await fs.mkdtemp(path.join(__dirname, '../node_modules/.activity-check-'));
  t.after(() => fs.rm(folder, { recursive: true, force: true }));
  const output = path.join(folder, 'activity.cjs');
  await build({
    entryPoints: [path.join(__dirname, '../src/Activity.tsx')], outfile: output,
    bundle: true, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' },
    plugins: [{ name: 'ui-shell', setup(builder) {
      builder.onResolve({ filter: /^@heroui\/react$/ }, () => ({ path: 'shell', namespace: 'ui-shell' }));
      builder.onLoad({ filter: /.*/, namespace: 'ui-shell' }, () => ({ contents: `
        import React from 'react';
        export const Button = ({ onPress, children, ...props }) => React.createElement('button', { ...props, onClick: onPress }, children);
        export const Card = ({ children, ...props }) => React.createElement('article', props, children);
        for (const name of ['Header','Title','Description','Content']) Card[name] = ({children, ...props}) => React.createElement('div', props, children);
      `, resolveDir: path.join(__dirname, '..') }));
    }}],
  });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const oldWindow = globalThis.window;
  t.after(() => { globalThis.window = oldWindow; });
  return require(output);
}

const event = (id, extra = {}) => ({ id: String(id), kind: 'message', role: 'assistant', text: `record ${id}`,
  time: null, source: { runtime: 'codex', offset: id }, ...extra });
const text = tree => JSON.stringify(tree.toJSON());
const button = (tree, label) => tree.root.findAllByType('button').find(node =>
  typeof node.props.children === 'string' && node.props.children.startsWith(label));

for (const runtime of ['codex', 'dsh']) {
  test(`${runtime} work diagnostics are visible and copied with their label`, async t => {
    const { EventCard } = await components(t);
    let copied;
    globalThis.window = { graphtraj: { copyText: async value => { copied = value; } } };
    const details = { type: 'error', message: 'Permission denied at src/main.py:14', code: 'EACCES' };
    let tree;
    await act(async () => { tree = create(React.createElement(EventCard, { event: event(1, {
      kind: 'work', text: 'error', details, source: { runtime, offset: 1 },
    }) })); });
    t.after(async () => { await act(async () => tree.unmount()); });
    assert.match(text(tree), /Permission denied at src\/main.py:14/);
    assert.match(text(tree), /EACCES/);
    await act(async () => { button(tree, 'Copy').props.onClick(); });
    assert.equal(copied, 'error\n\n' + JSON.stringify(details, null, 2));
  });
}

test('Follow drains long pages and reconnect replay; pause preserves the older view', async t => {
  const { ActivityView } = await components(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const member = { alias: 'worker', historical: false, runtime: 'codex', state: 'running' };
  const base = { ticket_id: '1', agents: [member], updated_at: '2026-10-06T00:00:00Z' };
  const records = Array.from({ length: 405 }, (_, i) => event(i));
  let reconnect = false;
  const requests = [];
  globalThis.window = { graphtraj: { activity: async (_project, request) => {
    requests.push(request);
    if (!request.alias) return base;
    if (reconnect && request.cursor) {
      reconnect = false;
      return { ...base, availability: 'cursor-expired', events: [], cursor: null };
    }
    const start = Number(request.cursor || 0);
    const end = Math.min(start + 200, records.length);
    return { ...base, availability: 'available', events: records.slice(start, end), cursor: String(end), has_more: end < records.length };
  } } };
  let tree;
  await act(async () => { tree = create(React.createElement(ActivityView, { projectId: 'p', ticketId: '1' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const advance = async (ms = 1) => { await act(async () => t.mock.timers.tick(ms)); };
  await act(async () => button(tree, 'worker').props.onClick());
  await act(async () => button(tree, 'Pause following').props.onClick());
  await advance();
  assert.equal(requests.filter(request => request.alias).length, 1);
  assert.doesNotMatch(text(tree), /record 404/);
  await act(async () => button(tree, 'Follow new').props.onClick());
  await advance(3000); await advance(); await advance();
  assert.match(text(tree), /record 404/);
  assert.deepEqual(requests.filter(request => request.alias).slice(0, 3).map(request => request.cursor), [undefined, '200', '400']);

  await act(async () => button(tree, 'Pause following').props.onClick());
  records.push(event(405));
  await advance(3000);
  assert.doesNotMatch(text(tree), /record 405/);
  assert.match(text(tree), /Follow new messages \(1\)/);
  await act(async () => button(tree, 'Follow new').props.onClick());
  assert.match(text(tree), /record 405/);

  reconnect = true;
  records.push(event(406));
  await advance(3000); await advance(3000); await advance(); await advance();
  assert.match(text(tree), /record 406/);
  assert.equal(tree.root.findAllByType('article').length, 100);
  assert.match(text(tree), /407/);
});
