import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';
import settingsModule from '../dist-electron/settings.js';

test('Electron settings draft, diff, native save, denial, conflict and restoration', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-settings-window-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const project = await fixtures.makeProject(path.join(root, 'project'), 'settings-window');
  const rolesFile = path.join(project, '.graphtraj', 'roles.yml');
  await fs.writeFile(rolesFile, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      api_key_env: SETTINGS_TEST_KEY\n      reports: [report.md]\nrole_tree: {}\n');
  const desktop = fileURLToPath(new URL('..', import.meta.url));
  const app = await electron.launch({ args: [desktop, `--user-data-dir=${path.join(root, 'userData')}`] });
  t.after(() => app.close());
  const page = await app.firstWindow();
  await app.evaluate(({ dialog }, folder) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] });
  }, project);
  await page.getByRole('button', { name: 'Add project', exact: true }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Model', { exact: true }).waitFor();
  const original = await fs.readFile(rolesFile);
  await page.getByLabel('Model', { exact: true }).fill('cancelled-model');
  await page.getByRole('button', { name: 'Cancel draft', exact: true }).click();
  assert.equal(await page.getByLabel('Model', { exact: true }).inputValue(), 'original-model');
  assert.deepEqual(await fs.readFile(rolesFile), original);

  // This development test controls the host dialog return. It proves the actual
  // Electron -> Python -> shared writer path, NOT human native-dialog acceptance.
  await app.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 0, checkboxChecked: false }); });
  await page.getByLabel('Model', { exact: true }).fill('denied-model');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
  assert.deepEqual(await fs.readFile(rolesFile), original);

  await app.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false }); });
  await page.getByLabel('Model', { exact: true }).fill('saved-model');
  await page.getByRole('table').getByText('saved-model', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  assert.match(await fs.readFile(rolesFile, 'utf8'), /model: saved-model/);

  const native = new settingsModule.SettingsClient(async () => true);
  t.after(() => native.close());
  const snapshot = await native.request(project);
  await native.request(project, { revision: snapshot.revision, edits: { 'custom_group.observer': { model: 'external-change' } },
    renames: {}, add_edges: [], remove_edges: [] });
  await page.getByLabel('Model', { exact: true }).fill('stale-draft');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  assert.match(await fs.readFile(rolesFile, 'utf8'), /model: external-change/);
  await page.getByRole('button', { name: 'Reload and discard draft', exact: true }).click();
  await page.getByRole('status').getByText('Loaded current configuration. Draft discarded.', { exact: true }).waitFor();
  await page.getByLabel('Model', { exact: true }).fill('original-model');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  assert.equal((await native.request(project)).roles['custom_group.observer'].model, 'original-model');
  assert.match(await fs.readFile(rolesFile, 'utf8'), /reports:\s*- report.md/);
});
