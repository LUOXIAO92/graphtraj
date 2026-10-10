const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

test('Dashboard filters persisted usage by local dates and keeps global comparison at project scope', async t => {
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
  const fact = (id, model) => ({ id, kind: 'usage', model, time: new Date().toISOString(),
    source: { runtime: 'pi', offset: Number(id) }, usage: { identity: 's:' + id, session: 's',
      agent: 'child', ticket_id: '263', attributable: true, phase: 'final',
      tokens: { input: 1000000, cache_read: 600000, output: 100000 } } });
  const events = [fact('1', 'gpt-5.3-codex'), fact('2', 'unknown-model')];
  const requests = [];
  const { collect, localDate, defaultDates } = require('../src/usage.ts');
  const calls = new Map();
  collect(calls, 'p', events);
  collect(calls, 'q', [{ ...fact('1', 'gpt-5.3-codex'), usage: {
    ...fact('1', '').usage, tokens: { input: 123, cache_read: 0, output: 1 }, agent: 'other-project-agent',
  } }]);
  globalThis.window = { graphtraj: {
    usage: async projectId => {
      requests.push(projectId);
      return { calls: [...calls.values()].filter(call => call.project === projectId),
        pending: false, notices: [], updatedAt: new Date().toISOString() };
    },
  } };
  let tree;
  await act(async () => { tree = create(React.createElement(UsageView, { projectId: 'p' })); });
  t.after(async () => { await act(async () => tree.unmount()); });
  const text = () => JSON.stringify(tree.toJSON());
  assert.match(text(), /Observation active/);
  assert.match(text(), /\$2.205000/);
  assert.match(text(), /Main calls are not covered/);
  assert.match(text(), /unknown-model/);
  assert.match(text(), /No verified model price/);
  const selects = tree.root.findAllByType('select');
  await act(async () => { selects[2].props.onChange({ target: { value: 'unknown-model' } }); });
  assert.doesNotMatch(text(), /\$2.205000/);
  await act(async () => { selects[2].props.onChange({ target: { value: '' } }); });
  const inputs = tree.root.findAllByType('input');
  assert.equal(inputs[0].props.type, 'date');
  assert.equal(inputs[0].props.value, defaultDates().from);
  assert.equal(inputs[1].props.value, localDate(new Date()));
  await act(async () => { inputs[0].props.onChange({ target: { value: localDate(new Date()) } }); });
  assert.match(text(), /\$2.205000/);
  await act(async () => { inputs[0].props.onChange({ target: { value: '2099-01-01' } }); });
  assert.match(text(), /start on or before the end/);
  assert.doesNotMatch(text(), /\$2.205000/);
  await act(async () => { inputs[1].props.onChange({ target: { value: '2099-01-01' } }); });
  assert.match(text(), /No usage records match/);
  await act(async () => { inputs[0].props.onChange({ target: { value: '' } }); });
  assert.match(text(), /Choose both dates/);
  assert.ok(requests.every(id => id === 'p'));
  await act(async () => { tree.update(React.createElement(UsageView, { key: 'global', projects: [
    { id: 'p', root: '/projects/first' }, { id: 'q', root: '/projects/second' },
  ] })); });
  assert.equal(tree.root.findAllByType('select').length, 0);
  assert.match(text(), /Project comparison/);
  assert.match(text(), /projects\/first/);
  assert.match(text(), /projects\/second/);
  assert.doesNotMatch(text(), /unknown-model|other-project-agent|Model breakdown|Call arithmetic/);
  assert.match(text(), /123/);
  const globalInputs = tree.root.findAllByType('input');
  await act(async () => {
    globalInputs[0].props.onChange({ target: { value: '2099-01-01' } });
    globalInputs[1].props.onChange({ target: { value: '2099-01-01' } });
  });
  assert.match(text(), /No usage records match/);
  assert.doesNotMatch(text(), /\$2.205000/);
});
