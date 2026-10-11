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
    click: async label => act(async () => tree.root.findAllByType('button').findLast(node => node.children.filter(child => typeof child === 'string').join('') === label || node.props['aria-label'] === label).props.onClick()),
    select: async (label, value) => act(async () => tree.root.findAllByType('select').find(node => node.props['aria-label'] === label).props.onChange({ target: { value } })),
    input: async (label, value) => act(async () => tree.root.findAllByType('input').find(node => node.props['aria-label'] === label).props.onChange({target:{value}})),
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
  await ui.click('Add team');
  await ui.select('New Agent Runtime', 'codex');
  await ui.fill('Team name for new team', 'research');
  await ui.fill('New Agent name', 'root'); await ui.fill('New Agent model', 'draft-model');
  await ui.click('Add team with root'); await ui.select('Agent Runtime', 'shared');
  await ui.fill('Reasoning effort', 'low');
  await ui.click('Add child agent'); await ui.fill('New Agent name', 'child'); await ui.click('Add Agent');
  assert.equal(ui.tree.root.findAllByType('select').find(node => node.props['aria-label'] === 'Agent parent').props.value, 'research.root');
  await ui.click('Add child agent'); await ui.fill('New Agent name', 'leaf'); await ui.click('Add Agent');
  await ui.select('Agent parent', 'research.root');
  await ui.input('Team name', 'final'); await ui.click('Review changes'); await ui.click('Save changes');
  assert.deepEqual(submitted.edits['research.root'], { connection: 'shared/openai/model', reasoning_effort: 'low' });
  assert.deepEqual(JSON.parse(JSON.stringify(submitted.role_tree['research.root'])), { 'research.child': {}, 'research.leaf': {} });
  assert.equal(submitted.renames['research.leaf'], 'final.leaf');
  assert.equal(submitted.edits['existing.root'], undefined);
  assert.deepEqual(submitted.remove_presets, []); assert.equal(submitted.decision, undefined);
  assert.match(JSON.stringify(ui.tree.toJSON()), /Controlled refusal/);
  await ui.click('Keep editing'); await ui.click('Cancel changes'); assert.doesNotMatch(JSON.stringify(ui.tree.toJSON()), /research.root/);
});

test('native Runtime and Provider API selects keep explicit names as options change', async t => {
  let preview;
  const original = { ...connections, catalog: { version: 1, runtimes: {} },
    capabilities: { model_discovery: { pi: 'native' }, custom_api: { pi: ['openai-completions'] } } };
  const ui = await form(t, 'Connections.tsx', 'ConnectionsView', {
    connections: async (_id, request) => {
      if (request.action === 'preview') preview = request.catalog;
      return { ...original, catalog: request.catalog ?? original.catalog };
    },
  }, {});
  await ui.click('Add Runtime');
  await ui.select('Runtime type', 'pi');
  await ui.fill('Runtime entry name', 'pi'); await ui.click('Add runtime');
  await ui.click('Add provider'); await ui.fill('Provider name', 'custom'); await ui.click('Add provider');
  await ui.select('Provider API', 'openai-completions');
  await ui.click('Review changes');
  assert.equal(preview.runtimes.pi.runtime, 'pi');
  assert.equal(preview.runtimes.pi.providers.custom.api, 'openai-completions');
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
  await ui.click('Add Runtime'); await ui.fill('Runtime entry name', name); await ui.click('Add runtime');
  await ui.fill('Runtime Home', '/isolated/native');
  await ui.click('Add provider'); await ui.fill('Provider name', name); await ui.click('Add provider');
  await ui.fill('Base URL', 'https://provider.invalid/v1');
  await ui.fill('API key environment variable', 'CUSTOM_KEY');
  await ui.click('Add model'); await ui.fill('Model entry name', name); await ui.fill('Model identifier', 'actual-model');
  await ui.fill('Model alias', 'Display name'); await ui.click('Add model');
  await ui.click('Review changes'); await ui.click('Save connections');
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

test('rename team then add child saves and reloads one renamed group', async t => {
  let saved = { revision: 'before', roles: { 'a.root': { runtime: 'codex', model: 'original', instructions: 'instructions.txt' } },
    role_tree: { 'a.root': {} }, edges: [], effect: 'Later dispatches only.' };
  let submitted;
  const ui = await form(t, 'Settings.tsx', 'SettingsView', {
    settings: async () => saved, connections: async () => connections,
    saveSettings: async (_id, draft) => {
      submitted = JSON.parse(JSON.stringify(draft));
      saved = { ...saved, revision: 'after', roles: {
        'b.root': saved.roles['a.root'], 'b.worker': { runtime: 'codex', model: 'worker-model' },
      }, role_tree: { 'b.root': { 'b.worker': {} } }, edges: [['b.root', 'b.worker']] };
      return { ...saved, applied: true };
    },
  }, { projectId: 'project' });
  await ui.input('Team name', 'b'); await ui.click('Add child agent');
  await ui.fill('New Agent name', 'worker'); await ui.fill('New Agent model', 'worker-model');
  await ui.click('Add Agent'); await ui.click('Review changes'); await ui.click('Save changes');
  assert.deepEqual(submitted, {
    revision: 'before', edits: { 'a.worker': { runtime: 'codex', model: 'worker-model' } },
    renames: { 'a.root': 'b.root', 'a.worker': 'b.worker' },
    add_edges: [], remove_edges: [], remove_presets: [], role_tree: { 'a.root': { 'a.worker': {} } },
  });
  await ui.click('Reload');
  const value = ui.tree.root.findAllByType('input').find(node => node.props['aria-label'] === 'Team name');
  assert.equal(value.props.value, 'b');
  const labels = ui.tree.root.findAllByType('button').map(node => node.props['aria-label']);
  assert.ok(labels.includes('Configure agent b.worker')); assert.ok(!labels.includes('Configure agent a.worker'));
});

for (const change of ['same destination', 'existing override', 'edit identifier']) {
  test(`native model provenance in the D add dialog: ${change}`, async t => {
    const catalog = { version: 1, runtimes: { shared: { runtime: 'codex', home: '/original/home', providers: {
      openai: { models: {}, ...(change === 'existing override' ? { base_url: 'https://override.invalid/v1' } : {}) },
    } } } };
    let preview;
    const ui = await form(t, 'Connections.tsx', 'ConnectionsView', {
      connections: async (_id, request) => {
        if (request.action === 'preview') preview = request.catalog;
        return { ...connections, catalog: request.catalog ?? catalog, discovery: request.action === 'discover' ? {
          runtime_entry: 'shared', status: 'available', account_access: 'unknown', models: [
            { provider: 'openai', id: 'discovered', alias: 'Native label', source: 'native', supported_efforts: ['low'] },
          ],
        } : undefined };
      },
    }, { projectId: 'project' });
    await ui.click('Refresh native models'); await ui.click('Use discovered');
    if (change === 'edit identifier') await ui.fill('Model identifier', 'manual-id');
    await ui.click('Add model'); await ui.click('Review changes');
    const model = preview.runtimes.shared.providers.openai.models.discovered;
    assert.equal(model.id, change === 'edit identifier' ? 'manual-id' : 'discovered');
    assert.equal(model.source, change === 'same destination' ? 'native' : 'manual');
    assert.deepEqual(model.supported_efforts, change === 'same destination' ? ['low'] : undefined);
  });
}

test('changing Runtime Home clears retained discovery before it can be reused', async t => {
  const ui = await form(t, 'Connections.tsx', 'ConnectionsView', {
    connections: async (_id, request) => ({ ...connections, discovery: request.action === 'discover' ? {
      runtime_entry: 'shared', status: 'available', account_access: 'unknown', models: [
        { provider: 'openai', id: 'discovered', source: 'native', supported_efforts: ['low'] },
      ],
    } : undefined }),
  }, {});
  await ui.click('Refresh native models');
  assert.ok(ui.tree.root.findAllByType('button').some(node => node.children.join('') === 'Use discovered'));
  await ui.fill('Runtime Home', '/another/home');
  assert.ok(!ui.tree.root.findAllByType('button').some(node => node.children.join('') === 'Use discovered'));
});

test('D root deletion explicitly promotes one child and reconnects the others', async t => {
  const saved = { revision: 'root-revision', roles: {
    'team.root': { runtime: 'codex', model: 'model' },
    'team.first': { runtime: 'codex', model: 'model' },
    'team.second': { runtime: 'codex', model: 'model' },
  }, role_tree: { 'team.root': { 'team.first': {}, 'team.second': {} } }, edges: [], effect: 'Later dispatches only.' };
  let submitted;
  const ui = await form(t, 'Settings.tsx', 'SettingsView', {
    settings: async () => saved, connections: async () => connections,
    saveSettings: async (_id, draft) => { submitted = draft; return saved; },
  }, { projectId: 'project' });
  await ui.click('Delete selected agent configuration');
  await act(async () => ui.tree.root.findAllByType('input').find(node => node.props.name === 'delete-mode').props.onChange());
  await ui.select('New root', 'team.second');
  await ui.click('Remove from draft'); await ui.click('Review changes'); await ui.click('Save changes');
  assert.deepEqual(submitted.remove_presets, ['team.root']);
  assert.deepEqual(JSON.parse(JSON.stringify(submitted.role_tree)), { 'team.second': { 'team.first': {} } });
});
