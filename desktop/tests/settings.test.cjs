const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { SettingsClient, reviewText } = require('../dist-electron/settings.js');
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

test('desktop main-process settings pipe saves, denies, detects conflict and restores through native entry', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-settings-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const project = await fixtures.makeProject(path.join(root, 'project'), 'settings-project');
  const file = path.join(project, '.graphtraj', 'roles.yml');
  // Initial isolated configuration only. Every subsequent change and restoration
  // exercises the native save operation, with controlled host replies in this test.
  await fs.writeFile(file, roles);
  let approved = true;
  const reviews = [];
  const client = new SettingsClient(async proposal => { reviews.push(proposal); return approved; });
  t.after(() => client.close());
  const before = await client.request(project);
  const graph = fixtures.operate(project, 'ticket_graph');
  const draft = { revision: before.revision, edits: { 'custom_group.observer': { model: 'saved-model' } },
    renames: {}, add_edges: [], remove_edges: [] };
  const saved = await client.request(project, draft);
  assert.equal(saved.roles['custom_group.observer'].model, 'saved-model');
  assert.match(reviewText(reviews[0]), /original-model → saved-model/);
  assert.equal(JSON.stringify(saved).includes('unknown_future_field'), false);
  assert.match(await fs.readFile(file, 'utf8'), /unknown_future_field: preserved/);
  const savedBytes = await fs.readFile(file);
  await assert.rejects(client.request(project, draft), /changed while editing/);
  assert.deepEqual(await fs.readFile(file), savedBytes);
  approved = false;
  assert.equal((await client.request(project, { ...draft, revision: saved.revision })).applied, false);
  // Same content is a no-op, so make a concrete denied change as well.
  await assert.rejects(client.request(project, { ...draft, revision: saved.revision,
    edits: { 'custom_group.observer': { model: 'denied-model' } } }), /did not approve/);
  assert.deepEqual(await fs.readFile(file), savedBytes);
  approved = true;
  const restored = await client.request(project, { ...draft, revision: saved.revision,
    edits: { 'custom_group.observer': { model: before.roles['custom_group.observer'].model } } });
  assert.deepEqual(restored.roles, before.roles);
  assert.deepEqual(restored.edges, before.edges);
  assert.deepEqual(fixtures.operate(project, 'ticket_graph'), graph);
  assert.match(await fs.readFile(file, 'utf8'), /unknown_future_field: preserved/);
});
