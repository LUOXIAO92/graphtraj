const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const React = require('react');
const { create, act } = require('react-test-renderer');
const { build } = require('esbuild');

/** Exercise real form state with a component shell; no window or native authority is simulated. */
async function form(t, file, component, api, props) {
  const folder = await fs.mkdtemp(path.join(__dirname, '../node_modules/.settings-check-'));
  t.after(() => fs.rm(folder, { recursive: true, force: true }));
  const output = path.join(folder, 'view.cjs');
  await build({ entryPoints: [path.join(__dirname, '../src', file)], outfile: output,
    bundle: true, platform: 'node', format: 'cjs', external: ['react'], loader: { '.css': 'empty' },
    plugins: [{ name: 'ui-shell', setup(builder) {
      builder.onResolve({ filter: /^@heroui\/react$/ }, () => ({ path: 'shell', namespace: 'ui-shell' }));
      builder.onLoad({ filter: /.*/, namespace: 'ui-shell' }, () => ({ contents: `
        import React from 'react';
        export const Button = ({onPress, children, ...props}) => React.createElement('button', {...props, onClick:onPress}, children);
        export const Card = props => React.createElement('article', props);
        for (const key of ['Header','Title','Description','Content']) Card[key] = props => React.createElement('div', props);
        export const Form = props => React.createElement('form', props);
        export const TextField = props => React.createElement('field', props);
        export const Label = props => React.createElement('label', props);
        export const Description = props => React.createElement('span', props);
        export const Input = props => React.createElement('input', props);
        export const TextArea = props => React.createElement('textarea', props);
      `, resolveDir: path.join(__dirname, '..') }));
    }}] });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const previous = globalThis.window;
  globalThis.window = { graphtraj: api };
  let tree;
  await act(async () => { tree = create(React.createElement(require(output)[component], props)); });
  t.after(async () => { await act(async () => tree.unmount()); globalThis.window = previous; });
  return { tree,
    fill: async (label, value) => act(async () => tree.root.findAllByType('field').find(node => node.findByType('label').children.join('') === label).props.onChange(value)),
    click: async label => act(async () => tree.root.findAllByType('button').find(node => node.children.join('') === label).props.onClick()),
    select: async (label, value) => act(async () => tree.root.findAllByType('select').find(node => node.parent.children[0] === label).props.onChange({ target: { value } })),
    submit: async () => act(async () => tree.root.findByType('form').props.onSubmit({ preventDefault() {} })),
  };
}
const connections = { revision: 'catalog-revision', catalog: { version: 1, runtimes: {
  shared: { runtime: 'codex', providers: { openai: { models: { model: { id: 'native-model', source: 'native', supported_efforts: ['low'] } } } } },
} }, account_access: 'unknown', capabilities: { model_discovery: { codex: 'native' }, custom_api: { codex: ['responses'] } } };

test('team draft creates, reparents, renames and references a model while preserving other roles', async t => {
  const saved = { revision: 'roles-revision', roles: { 'existing.root': { runtime: 'codex', model: 'existing' } }, role_tree: { 'existing.root': {} }, edges: [], effect: 'Later dispatches only.' };
  let submitted;
  const ui = await form(t, 'Settings.tsx', 'SettingsView', {
    settings: async () => saved, connections: async () => connections,
    saveSettings: async (_id, value) => { submitted = value; throw new Error('Controlled refusal; retain draft.'); },
  }, { projectId: 'project' });
  await ui.fill('Team name for new team', 'research');
  await ui.fill('New Agent name', 'root'); await ui.fill('New Agent model', 'draft-model');
  await ui.click('Add team with root'); await ui.select('Global connection', 'shared/openai/model');
  await ui.fill('Reasoning effort', 'low');
  await ui.fill('New Agent name', 'child'); await ui.click('Add child Agent');
  assert.equal(ui.tree.root.findAllByType('select').find(node => node.parent.children[0] === 'Agent parent').props.value, 'research.root');
  await ui.fill('New Agent name', 'leaf'); await ui.click('Add child Agent');
  await ui.select('Agent parent', 'research.root');
  await ui.fill('New team name', 'final'); await ui.click('Rename team'); await ui.submit();
  assert.deepEqual(submitted.edits['research.root'], { connection: 'shared/openai/model', reasoning_effort: 'low' });
  assert.deepEqual(JSON.parse(JSON.stringify(submitted.role_tree['research.root'])), { 'research.child': {}, 'research.leaf': {} });
  assert.equal(submitted.renames['research.leaf'], 'final.leaf');
  assert.equal(submitted.edits['existing.root'], undefined);
  assert.deepEqual(submitted.remove_presets, []); assert.equal(submitted.decision, undefined);
  assert.match(JSON.stringify(ui.tree.toJSON()), /Controlled refusal/);
  await ui.click('Cancel draft'); assert.doesNotMatch(JSON.stringify(ui.tree.toJSON()), /research.root/);
});

for (const name of ['ordinary', '__proto__']) test(`global form preserves ${name} catalog keys and sends only native save fields`, async t => {
  const original = { ...connections, catalog: { version: 1, runtimes: {} } };
  const calls = [];
  const ui = await form(t, 'Connections.tsx', 'ConnectionsView', {
    connections: async (id, request) => {
      calls.push({ id, request });
      return request.action === 'read' ? original : { ...original, catalog: request.catalog, applied: request.action === 'save' };
    },
  }, {});
  await ui.fill('Runtime entry name', name); await ui.click('Add Runtime');
  await ui.fill('Shared Runtime Home', '/isolated/native');
  await ui.fill('Provider name', name); await ui.click('Add Provider');
  await ui.fill('Provider Base URL', 'https://provider.invalid/v1');
  await ui.fill('Provider api_key_env name', 'CUSTOM_KEY');
  await ui.fill('Model entry name', name); await ui.fill('Model identifier', 'actual-model');
  await ui.fill('Model alias', 'Display name'); await ui.click('Add Model');
  await ui.click('Preview connections'); await ui.click('Save connections');
  const { id, request } = calls.at(-1);
  assert.equal(id, null);
  assert.deepEqual(Object.keys(request).sort(), ['action', 'catalog', 'expected_revision']);
  assert.equal(request.expected_revision, 'catalog-revision');
  assert.deepEqual(JSON.parse(JSON.stringify(request.catalog.runtimes[name])), {
    runtime: 'codex', home: '/isolated/native', providers: { [name]: {
      base_url: 'https://provider.invalid/v1', api_key_env: 'CUSTOM_KEY',
      models: { [name]: { id: 'actual-model', alias: 'Display name', source: 'manual' } },
    } },
  });
  assert.match(JSON.stringify(ui.tree.toJSON()), /Connections saved/);
});
