import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';

test('actual Electron window uses native graph, safe preload, refresh and persisted projects', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-window-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const first = await fixtures.makeProject(path.join(root, 'first'), 'first-project');
  const second = await fixtures.makeProject(path.join(root, 'second'), 'second-project');
  const desktop = fileURLToPath(new URL('..', import.meta.url));
  const args = [desktop, `--user-data-dir=${path.join(root, 'userData')}`];
  let app = await electron.launch({ args });
  t.after(async () => { if (app) await app.close(); });
  let page = await app.firstWindow();

  // The native dialog's selection is controlled here; real OS-picker interaction
  // is a separate manual acceptance check, never claimed by this test.
  async function pick(folder) {
    await app.evaluate(({ dialog }, selected) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [selected] });
    }, folder);
    await page.getByRole('button', { name: 'Add project', exact: true }).click();
    await page.getByRole('button', { name: 'Add project', exact: true }).waitFor({ state: 'visible' });
  }
  await pick(first);
  await page.getByText('first project', { exact: true }).waitFor();
  await pick(second);
  await page.getByText('second project', { exact: true }).waitFor();
  assert.equal(await page.getByText('first project', { exact: true }).count(), 0);
  const boundary = await page.evaluate(() => ({
    require: typeof window.require, process: typeof window.process,
    methods: Object.keys(window.graphtraj).sort(),
  }));
  assert.equal(boundary.require, 'undefined');
  assert.equal(boundary.process, 'undefined');
  assert.deepEqual(boundary.methods, ['addProject', 'graph', 'projects', 'removeProject', 'selectProject']);
  assert.match(await page.evaluate(async () => {
    try { await window.graphtraj.graph('/'); return 'unexpected'; }
    catch (error) { return String(error); }
  }), /Choose an added project/);
  await page.locator('.react-flow__node').first().click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  await page.getByRole('slider', { name: 'Detail width' }).focus();
  await page.getByRole('slider', { name: 'Detail width' }).press('End');
  await page.getByRole('button', { name: 'Close details' }).click();
  await page.getByRole('searchbox').fill('dependent');
  await page.getByRole('button', { name: '#2 dependent', exact: true }).click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  await page.getByRole('searchbox').fill('');
  const nativeBeforeClose = fixtures.operate(second, 'ticket_graph');
  await app.close();
  app = await electron.launch({ args });
  page = await app.firstWindow();
  await page.getByText('second project', { exact: true }).waitFor();
  assert.deepEqual(fixtures.operate(second, 'ticket_graph'), nativeBeforeClose);
  fixtures.operate(second, 'ticket_register', fixtures.ticket('3', 'newly-observed', ['2']));
  await page.getByText('newly observed', { exact: true }).waitFor({ timeout: 15000 });
  const moved = second + '-moved';
  await fs.rename(second, moved);
  await page.getByText('Offline / query error', { exact: false }).waitFor({ timeout: 15000 });
  await fs.rename(moved, second);
  await page.getByText('Connected', { exact: false }).waitFor({ timeout: 15000 });
  await page.getByRole('button', { name: `Remove ${second}`, exact: true }).click();
  await page.getByText('first project', { exact: true }).waitFor();
  assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
  await app.close();
  app = null;
});
