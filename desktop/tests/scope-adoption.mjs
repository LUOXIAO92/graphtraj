/** Task 336: screenshot-driven real-window check of member scope, archive settings and lifecycle display.
 *
 * Launches this Worktree's built Electron App and operates it only with page.mouse /
 * page.keyboard. The script never sends, interrupts, resumes or retires an Agent and writes
 * no GraphTraj state; the only file it changes is the chosen project's swarm/config.yml,
 * through the App's Settings page, and it restores the original values.
 *
 *   node tests/scope-adoption.mjs [--project <root>] [--out <dir>] --summary <task-id>
 *     Default current scope, one historical summary and back; edit, reload and restore
 *     both archive switches.
 *   node tests/scope-adoption.mjs --project <root> [--out <dir>] --lifecycle <alias>
 *     Select that member in the current scope with the mouse, then only watch its
 *     displayed state for about 8 minutes while the operator stops and continues it.
 *
 * The backend tool is GRAPHTRAJ_TOOL, or graphtraj-tool beside GRAPHTRAJ_PYTHON.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const { values: options } = parseArgs({ options: {
  project: { type: 'string', default: path.join(desktop, 'dist-package', 'scope-project') },
  out: { type: 'string' }, summary: { type: 'string' }, lifecycle: { type: 'string' },
} });
const project = path.resolve(options.project);
const alias = options.lifecycle;
assert.ok(alias || options.summary, 'Give --summary <task-id> or --lifecycle <alias>');
const tool = process.env.GRAPHTRAJ_TOOL
  || (process.env.GRAPHTRAJ_PYTHON && path.join(path.dirname(process.env.GRAPHTRAJ_PYTHON), 'graphtraj-tool'));
assert.ok(tool, 'Set GRAPHTRAJ_PYTHON (or GRAPHTRAJ_TOOL) to the candidate backend');
const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: desktop, encoding: 'utf8' }).trim();
const dirty = execFileSync('git', ['status', '--porcelain', '--', '.'], { cwd: desktop, encoding: 'utf8' }).trim();
const evidence = path.resolve(options.out || path.join(desktop, 'dist-package', 'adoption-evidence',
  `336-${commit.slice(0, 12)}${alias ? '-lifecycle' : ''}`));
const profile = alias ? await fs.mkdtemp(path.join(os.tmpdir(), 'graphtraj-336-profile-')) : path.join(evidence, 'profile');
const config = path.join(project, '.graphtraj', 'swarm', 'config.yml');
const facts = { commit, dirty: Boolean(dirty), project, mode: alias ? 'lifecycle' : 'scope', summary: options.summary ?? null,
  alias: alias ?? null, tool, electron: electronExecutable, profile, launches: 0, steps: [], screenshots: [], passed: false };
await fs.mkdir(evidence, { recursive: true });

let app;
let page;
const step = text => { facts.steps.push({ at: new Date().toISOString(), text }); console.log(text); };
const shot = async name => { const file = path.join(evidence, name); await page.screenshot({ path: file }); facts.screenshots.push(file); };
/** Click the visible centre of a control with the real mouse. */
const click = async locator => {
  await locator.waitFor({ state: 'visible' });
  const box = await locator.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
};
/** Choose a select option with mouse focus and keyboard type-ahead only. */
const choose = async (locator, label) => {
  await click(locator);
  await page.keyboard.press('Escape');
  await page.keyboard.type(label);
  await page.keyboard.press('Enter');
};
const rows = () => page.locator('.member-tree-rows > button').allInnerTexts();
const notice = () => page.locator('.member-tree .native-notice').first().innerText();
// A scope without members shows the empty state; rows are listed otherwise.
const listed = () => page.locator('.member-tree-rows > button, .member-tree p[role="status"]:has-text("No members in this scope.")').first().waitFor();

/** Default scope, one historical summary and back; reading must change no member. */
async function scope() {
  await page.getByText('Members of current summaries', { exact: false }).waitFor();
  await listed();
  facts.currentNotice = await notice();
  const current = await rows();
  facts.current = current;
  assert.ok(current.every(text => !text.includes('Retired')), 'Retired members never appear in the current list');
  step(`current scope: ${facts.currentNotice} · ${current.length} members`);
  await shot('01-members-current.png');

  await choose(page.getByLabel('Member scope'), `History · #${options.summary}`);
  await page.getByText('History of one summary', { exact: false }).waitFor();
  await listed();
  facts.historyNotice = await notice();
  facts.history = await rows();
  step(`history of #${options.summary}: ${facts.history.length} members`);
  await shot('02-members-history.png');

  await choose(page.getByLabel('Member scope'), 'Current summaries');
  await page.getByText('Members of current summaries', { exact: false }).waitFor();
  await page.waitForTimeout(3500);
  await listed();
  assert.deepEqual(await rows(), current, 'Switching scope left members, parents and states unchanged');
  step('returned to current scope; members, parents and states unchanged');
  await shot('03-members-current-again.png');
}

/** Edit both archive switches, confirm the tool's own file, reload and restore. */
async function archive() {
  facts.configBefore = await fs.readFile(config, 'utf8').catch(() => null);
  await click(page.getByRole('button', { name: 'Teams & roles', exact: true }));
  const switches = { save_normalized_sessions: 'Save normalized Sessions',
    backfill_history: 'Backfill history of associated Sessions' };
  const original = {};
  for (const [name, label] of Object.entries(switches)) {
    const box = page.getByLabel(label);
    original[name] = await box.isChecked();
    await click(box);
    await page.getByText('Saved Session archive settings.').waitFor();
    await page.getByText('Saved Session archive settings.').waitFor({ state: 'hidden', timeout: 8000 });
  }
  facts.configEdited = await fs.readFile(config, 'utf8');
  for (const name of Object.keys(switches)) assert.ok(facts.configEdited.includes(`${name}: ${!original[name]}`), facts.configEdited);
  await click(page.getByRole('button', { name: 'Reload', exact: true }));
  await page.getByText('Loaded current configuration.').waitFor();
  for (const [name, label] of Object.entries(switches)) assert.equal(await page.getByLabel(label).isChecked(), !original[name]);
  step(`saved ${JSON.stringify(facts.configEdited)} in swarm/config.yml and reloaded`);
  await shot('04-settings-archive-edited.png');
  for (const [name, label] of Object.entries(switches)) {
    await click(page.getByLabel(label));
    await page.getByText('Saved Session archive settings.').waitFor();
    await page.getByText('Saved Session archive settings.').waitFor({ state: 'hidden', timeout: 8000 });
  }
  facts.configAfter = await fs.readFile(config, 'utf8');
  for (const name of Object.keys(switches)) assert.ok(facts.configAfter.includes(`${name}: ${original[name]}`), facts.configAfter);
  step('both switches restored to their original values');
  await shot('05-settings-archive-restored.png');
}

/** Only watch the selected member's displayed state; the operator drives the Agent. */
async function lifecycle() {
  await page.getByText('Members of current summaries', { exact: false }).waitFor();
  const member = page.locator('.member-tree-rows > button', { hasText: alias }).first();
  await click(member);
  const heading = page.locator(`[data-agent-id="${alias}"] .agent-column-heading span`).first();
  await heading.waitFor();
  const wanted = ['active', 'standby', 'active', 'standby'];
  const seen = [];
  const deadline = Date.now() + 8 * 60 * 1000;
  let matched = 0;
  while (matched < wanted.length) {
    if (Date.now() > deadline) throw new Error(`Timed out; displayed states ${JSON.stringify(seen)}`);
    const state = (await heading.innerText()).split('·').at(-1).trim();
    if (state !== seen.at(-1)?.state) {
      const at = new Date().toISOString();
      seen.push({ at, state });
      step(`${alias} displayed ${state}`);
      await shot(`lifecycle-${at.replace(/[:.]/g, '-')}-${state}.png`);
      if (state === wanted[matched]) matched += 1;
    }
    await page.waitForTimeout(500);
  }
  facts.lifecycle = seen;
}

try {
  app = await electron.launch({ executablePath: electronExecutable, timeout: 20000,
    args: [desktop, `--project=${project}`, `--user-data-dir=${profile}`],
    env: { ...process.env, GRAPHTRAJ_TOOL: tool, MAC_CHROMIUM_TMPDIR: alias ? os.tmpdir() : evidence } });
  facts.launches += 1;
  page = await app.firstWindow();
  page.setDefaultTimeout(20000);
  await click(page.getByRole('button', { name: 'Members', exact: true }));
  if (alias) await lifecycle();
  else { await scope(); await archive(); }
  facts.passed = true;
} catch (error) {
  facts.failure = String(error);
  if (page) await shot(`failure-${new Date().toISOString().replace(/[:.]/g, '-')}.png`).catch(() => {});
  process.exitCode = 1;
} finally {
  if (app) await app.close().catch(() => { facts.closeError = 'Owned app close rejected'; });
  await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
  console.log(JSON.stringify({ phase: 'CLOSED', evidence, passed: facts.passed }));
}
