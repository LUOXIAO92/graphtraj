const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

test('Dashboard consumes native pages, drains history, replays and filters the same arithmetic', async t => {
  const folder = await fs.mkdtemp(path.join(__dirname, '../node_modules/.usage-check-'));
  t.after(() => fs.rm(folder, { recursive: true, force: true }));
  const output = path.join(folder, 'usage.cjs');
  await build({ entryPoints: [path.join(__dirname, '../src/UsageDashboard.tsx')], outfile: output,
    bundle: true, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' },
    plugins: [{ name: 'ui-shell', setup(builder) {
      builder.onResolve({ filter: /^@heroui\/react$/ }, () => ({ path: 'shell', namespace: 'ui-shell' }));
      builder.onLoad({ filter: /.*/, namespace: 'ui-shell' }, () => ({ contents: `
        import React from 'react';
        export const Button = ({ onPress, children, ...props }) => React.createElement('button', { ...props, onClick: onPress }, children);
        export const Card = ({ children, ...props }) => React.createElement('article', props, children);
        for (const name of ['Header','Title','Description','Content']) Card[name] = ({children, ...props}) => React.createElement('div', props, children);
      `, resolveDir: path.join(__dirname, '..') }));
    }}] });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const oldWindow = globalThis.window;
  t.after(() => { globalThis.window = oldWindow; });
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { UsageView } = require(output);
  const fact = (id, model) => ({ id, kind: 'usage', model, time: '2026-10-10T12:00:00Z',
    source: { runtime: 'pi', offset: Number(id) }, usage: { identity: 's:' + id, session: 's',
      agent: 'child', ticket_id: '263', attributable: true, phase: 'final',
      tokens: { input: 1000000, cache_read: 600000, output: 100000 } } });
  const events = [fact('1', 'gpt-5.3-codex'), fact('2', 'unknown-model')];
  const requests = [];
  let replay = false;
  globalThis.window = { graphtraj: {
    graph: async () => ({ graph: { tickets: [{ ticket_id: '263', title: 'Usage' }] } }),
    activity: async (projectId, request) => {
      requests.push({ projectId, ...request });
      const base = { scope: 'self', agents: [{ alias: 'child' }] };
      if (!request.alias) return base;
      if (replay && request.cursor) { replay = false; return { ...base, availability: 'cursor-expired' }; }
      const index = Number(request.cursor || 0);
      return { ...base, availability: 'available', cursor: String(Math.min(index + 1, 2)),
        events: events.slice(index, index + 1), has_more: index < 1 };
    },
  } };
  let tree;
  await act(async () => { tree = create(React.createElement(UsageView, { projectId: 'p' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const text = () => JSON.stringify(tree.toJSON());
  assert.match(text(), /Loading history/);
  await act(async () => { t.mock.timers.tick(250); });
  assert.match(text(), /\$2.205000/);
  assert.match(text(), /Main calls are not covered/);
  assert.match(text(), /unknown-model/);
  assert.match(text(), /No verified model price/);
  const selects = tree.root.findAllByType('select');
  await act(async () => { selects[2].props.onChange({ target: { value: 'unknown-model' } }); });
  assert.doesNotMatch(text(), /\$2.205000/);
  await act(async () => { selects[2].props.onChange({ target: { value: '' } }); });
  replay = true;
  await act(async () => { t.mock.timers.tick(3000); });
  assert.match(text(), /replaying native history/);
  await act(async () => { t.mock.timers.tick(250); });
  await act(async () => { t.mock.timers.tick(250); });
  assert.match(text(), /\$2.205000/);
  assert.ok(requests.every(request => request.projectId === 'p'));
});
