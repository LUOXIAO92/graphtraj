import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';
import { projectsView, removeIndexEntry, taskTitle } from './adoption-shared.mjs';

test('actual Electron window uses native graph, safe preload, refresh and persisted projects', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-window-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const first = await fixtures.makeProject(path.join(root, 'first'), 'first-project');
  const second = await fixtures.makeProject(path.join(root, 'second'), 'second-project');
  const canonicalSecond = await fs.realpath(second);
  const canonicalFirst = await fs.realpath(first);
  const desktop = fileURLToPath(new URL('..', import.meta.url));
  const args = [desktop, `--user-data-dir=${path.join(root, 'userData')}`];
  // Bounded close: a hung app.close() must not keep `node --test` waiting (CI run 45588541238 hung here).
  const bounded = (promise, ms) => Promise.race([promise.then(() => true, () => false),
    new Promise(resolve => setTimeout(() => resolve(false), ms))]);
  async function close(handle) {
    if (!handle) return;
    if (!await bounded(handle.close(), 10000)) { try { handle.process().kill('SIGKILL'); } catch {} }
  }
  // Wait until the renderer has loaded and exposed the bridge: the first evaluate right after firstWindow()
  // raced the page load ('Execution context was destroyed', CI run 45588541238).
  async function launch() {
    app = await electron.launch({ args });
    page = await app.firstWindow();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForFunction(() => !!window.graphtraj && !!document.querySelector('.desktop-d'));
  }
  let app = null;
  let page = null;
  let originalSelection = null;
  // Registered before the first launch, so a failure anywhere below still closes the window.
  t.after(async () => {
    if (!app) return;
    if (page && !page.isClosed()) await bounded(page.evaluate(async ({ roots, originalSelection }) => {
      for (const project of (await window.graphtraj.projects()).projects) {
        if (roots.includes(project.root)) await window.graphtraj.removeProject(project.id);
      }
      if (originalSelection) await window.graphtraj.selectProject(originalSelection);
    }, { roots: [canonicalFirst, canonicalSecond], originalSelection }), 10000);
    await close(app);
  });
  await launch();
  originalSelection = (await page.evaluate(() => window.graphtraj.projects())).selected;

  // The native dialog's selection is controlled here; real OS-picker interaction
  // is a separate manual acceptance check, never claimed by this test.
  async function pick(folder) {
    await app.evaluate(({ dialog }, selected) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [selected] });
    }, folder);
    // D: Add project lives on the Projects view, which does not navigate; return to the monitor.
    await projectsView(page);
    await page.getByRole('button', { name: 'Add project', exact: true }).click();
    await page.getByRole('button', { name: 'Add project', exact: true, disabled: false }).waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
  }
  const monitor = () => page.locator('.monitor-page:visible');
  await pick(first);
  await taskTitle(monitor(), 'first project').waitFor();
  await pick(second);
  await taskTitle(monitor(), 'second project').waitFor();
  assert.equal(await page.locator('.monitor-page:visible').getByText('first project', { exact: true }).count(), 0);
  const boundary = await page.evaluate(() => ({
    require: typeof window.require, process: typeof window.process,
    methods: Object.keys(window.graphtraj).sort(),
  }));
  assert.equal(boundary.require, 'undefined');
  assert.equal(boundary.process, 'undefined');
  // Exactly the preload bridge (electron/preload.ts, unchanged since base 4fa79a8d); no other method.
  assert.deepEqual(boundary.methods, ['activity', 'addProject', 'connections', 'copyText', 'graph', 'members', 'projects',
    'relocateProject', 'removeProject', 'saveArchive', 'saveSettings', 'selectProject', 'settings', 'usage']);
  assert.match(await page.evaluate(async () => {
    try { await window.graphtraj.graph('/'); return 'unexpected'; }
    catch (error) { return String(error); }
  }), /Choose an added project/);
  // The task graph is the X6 canvas (D); React Flow now draws only the team organisation tree.
  await page.locator('.monitor-page:visible [aria-label="Native task canvas"] .native-task-card .native-task-title').first().click();
  await page.getByRole('complementary', { name: 'Task details' }).waitFor();
  const details = page.getByRole('complementary', { name: 'Task details' });
  await details.getByText('No participating Agents recorded.').waitFor();
  await page.evaluate(() => window.graphtraj.copyText('Observed plain text'));
  assert.equal(await app.evaluate(({ clipboard }) => clipboard.readText()), 'Observed plain text');
  // U2 (Task 627): the right-side inspector's width is a slider; End takes its maximum.
  const width = () => details.evaluate(element => element.getBoundingClientRect().width);
  const before = await width();
  await page.getByRole('slider', { name: 'Detail width' }).focus();
  await page.getByRole('slider', { name: 'Detail width' }).press('End');
  assert.ok(await width() > before, 'Detail width widens the inspector');
  await page.getByRole('button', { name: 'Close details' }).click();
  const search = monitor().getByRole('searchbox', { name: 'Search tasks', exact: true });
  await search.fill('dependent');
  await monitor().getByLabel('Search results', { exact: true }).getByRole('button', { name: '#2 dependent', exact: true }).click();
  await details.waitFor();
  await search.fill('');
  const nativeBeforeClose = fixtures.operate(second, 'task_graph');
  await close(app);
  app = null;
  await launch();
  await taskTitle(monitor(), 'second project').waitFor();
  assert.deepEqual(fixtures.operate(second, 'task_graph'), nativeBeforeClose);
  fixtures.operate(second, 'task_register', fixtures.task('3', 'newly-observed', ['2']));
  await taskTitle(monitor(), 'newly observed').waitFor({ timeout: 15000 });
  const moved = second + '-moved';
  // The connection status is the visible monitor's top-bar role=status (V4).
  const connection = () => monitor().locator('header.d-monitor-caption [role="status"]');
  await fs.rename(second, moved);
  await connection().getByText('Offline / query error', { exact: false }).waitFor({ timeout: 15000 });
  await fs.rename(moved, second);
  await connection().getByText('Connected', { exact: false }).waitFor({ timeout: 15000 });
  await removeIndexEntry(page, canonicalSecond);
  // V11 (Task 627): the entry's subtitle is the parent directory; the full root is its title.
  await page.locator(`.project-button[title=${JSON.stringify(canonicalFirst)}]`).click();
  await taskTitle(monitor(), 'first project').waitFor();
  assert.equal(fixtures.operate(second, 'task_graph').tasks.length, 3);
  // The after hook removes the remaining fixture entry and closes this window.
});
