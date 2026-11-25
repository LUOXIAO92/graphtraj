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
  // U2 (Task 627), both states. The window's CSS width depends on the runner's screen (1024 px on the macOS runner,
  // run 45600065327), so the test asserts the state for the width it actually has, then forces the other.
  const slider = () => page.getByRole('slider', { name: 'Detail width' });
  const layout = () => monitor().evaluate(scope => {
    const box = element => { const r = element.getBoundingClientRect(); return { x: r.left, y: r.top, right: r.right, bottom: r.bottom, width: r.width }; };
    return { viewport: innerWidth, canvas: box(scope.querySelector('[aria-label="Native task canvas"]')),
      details: box(scope.querySelector('aside[aria-label="Task details"]')) };
  });
  const atStart = await layout();
  if (atStart.viewport < 1100) {
    // (a) Below ~1100 CSS px the inspector falls back to a full-width bottom shelf with no width to adjust.
    assert.ok(atStart.details.y >= atStart.canvas.bottom - 1, `Task details is below the canvas: ${JSON.stringify(atStart)}`);
    assert.equal(await slider().count(), 0, 'no visible Detail width slider in the bottom shelf');
  }
  // (b) The inspector state, independent of the screen: zoom out so the CSS viewport is 1400 px wide
  // (CSS width = window width / zoom factor; the factor is computed from the measured width, 1 when already wide).
  const zoom = Math.min(1, atStart.viewport / 1400);
  await app.evaluate(({ BrowserWindow }, factor) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(factor), zoom);
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.monitor-page:not(.concealed) [aria-label="Native task canvas"]')?.getBoundingClientRect();
    const aside = document.querySelector('.monitor-page:not(.concealed) aside[aria-label="Task details"]')?.getBoundingClientRect();
    return innerWidth >= 1100 && canvas && aside && aside.left >= canvas.right - 1;
  });
  const wide = await layout();
  assert.ok(wide.details.x >= wide.canvas.right - 1, `Task details is a right-side inspector: ${JSON.stringify(wide)}`);
  await slider().focus();
  await slider().press('End');
  await page.waitForFunction(before => document.querySelector('.monitor-page:not(.concealed) aside[aria-label="Task details"]')
    .getBoundingClientRect().width > before, wide.details.width);
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  await page.waitForFunction(width => innerWidth === width, atStart.viewport);
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
