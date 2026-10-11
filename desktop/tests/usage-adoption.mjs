/** Installed #293 Usage UI against disposable native member data; no live Main claim. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { _electron as electron } from 'playwright';
import { expect as baseExpect } from 'playwright/test';
const expect = baseExpect.configure({ timeout: 15000 });
import fixtures from './fixtures.cjs';

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Disposable CI only');
assert.equal(process.platform, 'darwin');
const require = createRequire(import.meta.url);
const evidence = path.resolve('dist-package/adoption-evidence/usage');
const work = await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-293-usage-'));
const gate = path.join(work, 'pause-observer');
const entered = gate + '.entered';
const facts = { source: process.env.GITHUB_SHA, platform: process.platform, launches: 0,
  scope: 'Installed Usage UI and real persistence with controlled native member records; not genuine Main adoption',
  steps: [], passed: false, pageErrors: [] };
let app;
let page;
await fs.mkdir(evidence, { recursive: true });
const original = process.env.GRAPHTRAJ_TOOL || execFileSync('which', ['graphtraj-tool'], { encoding: 'utf8' }).trim();
const python = execFileSync('which', ['python'], { encoding: 'utf8' }).trim();
const wrapper = path.join(work, 'delayed-observer');
// Hold only the observer transport, not its response or identity. Release explicitly.
await fs.writeFile(wrapper, `#!${python}\nimport os,sys,time\nfrom pathlib import Path\ngate=Path(${JSON.stringify(gate)})\nif '--desktop-observer' in sys.argv:\n    if gate.exists():\n        Path(${JSON.stringify(entered)}).touch()\n    while gate.exists():\n        time.sleep(0.05)\nos.execv(${JSON.stringify(original)}, [${JSON.stringify(original)}, *sys.argv[1:]])\n`, { mode: 0o700 });
const count = total => ({ type: 'event_msg', timestamp: new Date().toISOString(), payload: {
  type: 'token_count', info: { last_token_usage: { input_tokens: 100, output_tokens: 10 },
    total_token_usage: { input_tokens: total, output_tokens: total / 10 } } } });
const loader = path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/server/electron/loader.js');
async function launch(project) {
  facts.launches++;
  app = await electron.launch({ executablePath: '/Applications/GraphTraj.app/Contents/MacOS/GraphTraj',
    env: { ...process.env, GRAPHTRAJ_TOOL: wrapper },
    args: ['-r', loader, `--user-data-dir=${path.join(work, 'preferences')}`, ...(project ? [`--project=${project}`] : [])], timeout: 30000 });
  page = await app.firstWindow();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => facts.pageErrors.push(String(error)));
  assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
  await page.getByRole('button', { name: 'Project usage', exact: true }).click();
  await page.getByRole('heading', { name: 'Project usage', exact: true }).waitFor();
}
const input = () => page.locator('.usage-dashboard .new-usage-totals strong').first();
async function reconnect() {
  const about = page.locator('.d-usage-history-note > details');
  if (await about.getAttribute('open') === null) await about.locator(':scope > summary').click();
  await page.getByRole('button', { name: 'Reconnect usage', exact: true }).click();
  await expect(page.locator('.usage-dashboard [role="status"]')).toContainText('Observation active');
}
try {
  // Never replace an existing human index, even on a misconfigured runner.
  await assert.rejects(fs.access(path.join(os.homedir(), '.graphtraj/projects.json')), { code: 'ENOENT' });
  const project = await fs.realpath(await fixtures.makeProject(path.join(work, 'usage-project'), 'usage-project'));
  const trace = await fixtures.recordActivity(project, { ticketId: '1', ticketName: 'usage-project',
    alias: 'usage293-handover0-engineer@engineer', records: [
      { type: 'turn_context', payload: { model: 'gpt-5.3-codex', turn_id: 'controlled-usage' } }, count(100),
    ] });
  await launch(project);
  await expect(input()).toHaveText('100');
  await reconnect();
  await expect(input()).toHaveText('100');
  facts.steps.push('Installed project Usage renders native persisted input=100; reconnect does not add a charge.');
  await page.screenshot({ path: path.join(evidence, 'usage-initial.png') });
  await app.close(); app = null;
  await fs.appendFile(trace, JSON.stringify(count(200)) + '\n');
  await fs.writeFile(gate, 'hold native observer until saved UI is observed\n');
  await launch();
  await expect(input()).toHaveText('100');
  await expect.poll(async () => fs.access(entered).then(() => true, () => false)).toBe(true);
  await fs.access(gate);
  facts.steps.push('Second real application launch renders saved input=100 while native observer is held and unread append exists.');
  await page.screenshot({ path: path.join(evidence, 'usage-reopened-saved-first.png') });
  await fs.unlink(gate);
  await expect(input()).toHaveText('200');
  await reconnect();
  await expect(input()).toHaveText('200');
  facts.steps.push('Releasing native observer updates the same actual Usage page to 200; reconnect preserves 200.');
  await page.getByRole('button', { name: /All project usage/ }).click();
  await expect(page.getByRole('heading', { name: 'Usage across projects', exact: true })).toBeVisible();
  await expect(input()).toHaveText('200');
  await expect(page.getByRole('table', { name: 'Project comparison' }).locator('tbody tr')).toHaveCount(1);
  await page.screenshot({ path: path.join(evidence, 'usage-updated-global.png') });
  assert.deepEqual(facts.pageErrors, []);
  facts.passed = true;
} catch (error) {
  facts.error = String(error.stack || error);
  if (page) await page.screenshot({ path: path.join(evidence, 'usage-failure.png') }).catch(() => {});
  throw error;
} finally {
  await fs.unlink(gate).catch(() => {});
  if (app) await app.close().catch(error => { facts.cleanupError = String(error); });
  await fs.writeFile(path.join(evidence, 'usage-adoption.json'), JSON.stringify(facts, null, 2) + '\n');
}
