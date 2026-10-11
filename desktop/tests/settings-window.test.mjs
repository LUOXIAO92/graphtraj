import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';

// Leader acceptance entry: optional GRAPHTRAJ_APP is the packaged executable.
// Uses isolated user configuration and no Runtime/Agent launches or model calls.
test('desktop Save, Cancel, reopen and conflicts in both settings pages', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-settings-window-'));
  const evidence = path.resolve(process.env.GRAPHTRAJ_SETTINGS_EVIDENCE || 'test-results/settings-window');
  await fs.mkdir(evidence, { recursive: true });
  const home = path.join(root, 'home');
  await fs.mkdir(home);
  const project = await fs.realpath(await fixtures.makeProject(path.join(root, 'project'), 'settings-window'));
  const rolesFile = path.join(project, '.graphtraj', 'roles.yml');
  await fs.writeFile(rolesFile, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      api_key_env: SETTINGS_TEST_KEY\n      reports: [report.md]\nrole_tree: {}\n');
  const desktop = fileURLToPath(new URL('..', import.meta.url));
  const executablePath = process.env.GRAPHTRAJ_APP;
  const require = createRequire(import.meta.url);
  const loader = path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/server/electron/loader.js');
  const facts = { executablePath, steps: [], passed: false, nativeDialogs: 0 };
  let app, page, projectId;
  t.after(async () => {
    if (app) await app.close();
    await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2) + '\n');
    await fs.rm(root, { recursive: true, force: true });
  });
  const button = name => page.getByRole('button', { name, exact: true }).filter({ visible: true });
  const field = name => page.getByLabel(name, { exact: true }).filter({ visible: true });
  const dialogButton = name => page.getByRole('dialog').getByRole('button', { name, exact: true });
  const readRoles = () => page.evaluate(id => window.graphtraj.settings(id), projectId);
  const readCatalog = () => page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), projectId);
  async function shot(name) { await page.screenshot({ path: path.join(evidence, `${name}.png`) }); }
  async function launch() {
    app = await electron.launch({ ...(executablePath ? { executablePath } : {}),
      args: [ ...(executablePath ? (process.platform === 'darwin' ? ['-r', loader] : []) : [desktop]),
        `--user-data-dir=${path.join(root, 'preferences')}`, `--project=${project}` ],
      env: { ...process.env, HOME: home, USERPROFILE: home }, timeout: 30000 });
    page = await app.firstWindow(); page.setDefaultTimeout(15000);
    // A second approval fails the save rather than silently accepting a dialog.
    await app.evaluate(({ dialog }) => {
      globalThis.settingsDialogs = 0;
      dialog.showMessageBox = async () => { globalThis.settingsDialogs++; throw new Error('Unexpected second approval'); };
    });
    await button('Teams & roles').waitFor();
    const preferences = await page.evaluate(() => window.graphtraj.projects());
    projectId = preferences.projects.find(item => item.root === project)?.id;
    assert.ok(projectId);
  }
  async function globalPage() {
    if (!await button('Agents & models').isVisible()) await button('Settings').click();
    await button('Agents & models').click();
    await page.locator('.d-library-tree').waitFor();
  }
  try {
    await launch();
    await button('Teams & roles').click();
    await page.getByText('Saved project model settings', { exact: true }).click();
    const original = await fs.readFile(rolesFile);
    await field('Model').fill('cancelled-model'); await button('Cancel').click();
    assert.equal(await field('Model').inputValue(), 'original-model');
    assert.deepEqual(await fs.readFile(rolesFile), original);
    await field('Model').fill('saved-model');
    await field("This agent's effort").selectOption('high');
    await button('Save').click();
    await page.getByRole('status').filter({ hasText: 'Settings saved.' }).waitFor();
    assert.equal((await readRoles()).roles['custom_group.observer'].model, 'saved-model');
    assert.equal((await readRoles()).roles['custom_group.observer'].reasoning_effort, 'high');
    await shot('roles-saved'); facts.steps.push('Role edit, Cancel without write, one Save persisted.');

    await field('Model').fill('stale-model');
    await page.evaluate(async id => {
      const state = await window.graphtraj.settings(id);
      await window.graphtraj.saveSettings(id, { revision: state.revision, edits: { 'custom_group.observer': { model: 'external-model' } } });
    }, projectId);
    await button('Save').click();
    await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
    assert.equal(await field('Model').inputValue(), 'stale-model');
    assert.equal((await readRoles()).roles['custom_group.observer'].model, 'external-model');
    await shot('roles-conflict'); await button('Reload').click();
    await page.getByRole('status').filter({ hasText: 'Loaded current configuration.' }).waitFor();
    facts.steps.push('Role conflict retains unsaved input and external configuration.');

    await globalPage();
    await button('Add Runtime').click(); await field('Runtime entry name').fill('shared'); await dialogButton('Add runtime').click();
    await field('Runtime Home').fill(path.join(root, 'runtime-home'));
    await page.locator('.d-library-detail-heading').getByRole('button', { name: 'Add provider', exact: true }).click();
    await field('Provider name').fill('custom'); await dialogButton('Add provider').click();
    await field('Base URL').fill('https://provider.invalid/v1'); await field('API key environment variable').fill('SETTINGS_TEST_KEY');
    await page.locator('.d-library-detail-heading').getByRole('button', { name: 'Add model', exact: true }).click();
    await field('Model entry name').fill('model'); await field('Model identifier').fill('actual-model'); await dialogButton('Add model').click();
    await button('Save').click(); await page.getByRole('status').filter({ hasText: 'Connections saved.' }).waitFor();
    const catalog = await readCatalog();
    assert.equal(catalog.catalog.runtimes.shared.providers.custom.api_key_env, 'SETTINGS_TEST_KEY');
    await page.locator('.library-select').filter({ hasText: 'custom' }).click();
    await field('Base URL').fill('https://cancelled.invalid/v1'); await button('Cancel').click();
    assert.deepEqual((await readCatalog()).catalog, catalog.catalog);
    await page.locator('.library-select').filter({ hasText: 'custom' }).click();
    assert.equal(await field('Base URL').inputValue(), 'https://provider.invalid/v1');
    await field('API key environment variable').fill('not-a-variable!'); await button('Save').click();
    await page.getByRole('alert').waitFor();
    assert.deepEqual((await readCatalog()).catalog, catalog.catalog);
    await field('API key environment variable').fill('SETTINGS_TEST_KEY');
    await field('Base URL').fill('https://stale.invalid/v1');
    await page.evaluate(async id => {
      const state = await window.graphtraj.connections(id, { action: 'read' });
      state.catalog.runtimes.shared.providers.custom.base_url = 'https://external.invalid/v1';
      await window.graphtraj.connections(id, { action: 'save', catalog: state.catalog, expected_revision: state.revision });
    }, projectId);
    await button('Save').click(); await page.getByRole('alert').filter({ hasText: 'changed' }).waitFor();
    assert.equal(await field('Base URL').inputValue(), 'https://stale.invalid/v1');
    assert.equal((await readCatalog()).catalog.runtimes.shared.providers.custom.base_url, 'https://external.invalid/v1');
    await shot('global-conflict'); facts.steps.push('Global Runtime/provider/model Save, Cancel, invalid input and conflict.');
    await button('Teams & roles').click();
    await field('Agent Runtime').selectOption('shared');
    assert.equal(await field("This agent's effort").inputValue(), 'high');
    await field('Agent model').selectOption('shared/custom/model');
    assert.equal(await field("This agent's effort").inputValue(), 'high');
    await field("This agent's effort").selectOption('max');
    await page.getByText('Codex approval route', { exact: true }).click();
    await field('Codex approval model').fill('review-model');
    await field('Codex approval Base URL').fill('https://review.invalid/v1');
    await field('Codex approval api_key_env name').fill('REVIEW_TEST_KEY');
    await button('Save').click(); await page.getByRole('status').filter({ hasText: 'Settings saved.' }).waitFor();
    assert.equal((await readRoles()).roles['custom_group.observer'].reasoning_effort, 'max');
    await shot('effort-saved'); facts.steps.push('Inline high effort retained on switching to a manual connection and reselecting it; max saved once.');
    assert.equal(await app.evaluate(() => globalThis.settingsDialogs), 0);
    await app.close(); app = null;

    await launch(); await globalPage();
    await page.locator('.library-select').filter({ hasText: 'custom' }).click();
    assert.equal(await field('Base URL').inputValue(), 'https://external.invalid/v1');
    await shot('global-reopened');
    await button('Teams & roles').click();
    assert.equal(await field('Agent model').inputValue(), 'shared/custom/model');
    assert.equal(await field("This agent's effort").inputValue(), 'max');
    assert.match(await fs.readFile(rolesFile, 'utf8'), /reports:\s*- report.md/);
    assert.equal(await app.evaluate(() => globalThis.settingsDialogs), 0);
    await shot('roles-reopened'); facts.steps.push('Actual window close/reopen reads both saved configurations; zero approval dialogs.');
    facts.passed = true;
  } catch (error) {
    facts.error = String(error.stack || error);
    if (page) await shot('failure').catch(() => {});
    throw error;
  }
});
