const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { SettingsClient } = require('../dist-electron/settings.js');
const fixtures = require('./fixtures.cjs');

const roles = `roles:
  custom_group:
    observer:
      runtime: codex
      model: original-model
      api_key_env: SETTINGS_TEST_KEY
      reports: [report.md]
      codex:
        unknown_future_field: preserved
  worker:
    runtime: codex
    model: worker-model
role_tree:
  custom_group.observer:
    worker: {}
`;

test('desktop main-process settings pipe saves directly, detects conflict and restores through native entry', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-settings-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const previousHome = process.env.HOME;
  const previousProfile = process.env.USERPROFILE;
  process.env.HOME = root; process.env.USERPROFILE = root;
  t.after(() => {
    if (previousHome === undefined) delete process.env.HOME; else process.env.HOME = previousHome;
    if (previousProfile === undefined) delete process.env.USERPROFILE; else process.env.USERPROFILE = previousProfile;
  });
  const project = await fixtures.makeProject(path.join(root, 'project'), 'settings-project');
  const file = path.join(project, '.graphtraj', 'roles.yml');
  // Initial isolated configuration only. Every subsequent change and restoration
  // exercises the native save operation without an approval reply.
  await fs.writeFile(file, roles);
  const client = new SettingsClient();
  t.after(() => client.close());
  const before = await client.request(project);
  const catalog = await client.connections(project, { action: 'read' });
  assert.ok(catalog.capabilities.reasoning_efforts.codex.includes('max'));
  const graph = fixtures.operate(project, 'ticket_graph');
  const draft = { revision: before.revision, edits: { 'custom_group.observer': { model: 'saved-model', reasoning_effort: 'max' } },
    renames: {}, add_edges: [], remove_edges: [] };
  const saved = await client.request(project, draft);
  assert.equal(saved.roles['custom_group.observer'].model, 'saved-model');
  assert.equal((await client.request(project)).roles['custom_group.observer'].reasoning_effort, 'max');
  assert.equal(JSON.stringify(saved).includes('unknown_future_field'), false);
  assert.match(await fs.readFile(file, 'utf8'), /unknown_future_field: preserved/);
  const savedBytes = await fs.readFile(file);
  await assert.rejects(client.request(project, draft), /changed while editing/);
  assert.deepEqual(await fs.readFile(file), savedBytes);
  assert.equal((await client.request(project, { ...draft, revision: saved.revision })).applied, false);
  const restored = await client.request(project, { ...draft, revision: saved.revision,
    edits: { 'custom_group.observer': { model: before.roles['custom_group.observer'].model, reasoning_effort: null } } });
  assert.deepEqual(restored.roles, before.roles);
  assert.deepEqual(restored.edges, before.edges);
  assert.deepEqual(fixtures.operate(project, 'ticket_graph'), graph);
  assert.match(await fs.readFile(file, 'utf8'), /unknown_future_field: preserved/);
});
