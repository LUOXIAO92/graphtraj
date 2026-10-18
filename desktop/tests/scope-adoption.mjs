/** Task 336: screenshot-driven real-window check of member scope, archive settings and lifecycle display.
 *
 * Launches this Worktree's built Electron App and operates it only with page.mouse /
 * page.keyboard. The script never sends, interrupts, resumes or retires an Agent and writes
 * no GraphTraj state; the only file it changes is the chosen project's swarm/config.yml,
 * through the App's Settings page, and it restores the original values.
 *
 *   node tests/scope-adoption.mjs [--project <root>] [--out <dir>] --user-data-dir <dir> [--part scope|archive|both]
 *     [--summary <task-id>]
 *     scope (needs --summary): default current scope, one historical summary and back; read-only,
 *     Settings is never opened. archive: edit, reload and restore both archive switches of that
 *     project's swarm/config.yml. both (default): scope, then archive.
 *   node tests/scope-adoption.mjs --project <root> --out <dir> --user-data-dir <dir> --lifecycle <alias>
 *     [--timeout-seconds 600]
 *     Select that member in the current scope with the mouse, then only watch its displayed
 *     state while the operator stops and continues it. Each change is screenshotted and
 *     appended to <out>/states.jsonl. Exit 0 after active, standby, active, standby; exit 2
 *     on timeout with a final screenshot; exit 1 on any other failure.
 *
 * The backend tool is GRAPHTRAJ_TOOL, or graphtraj-tool beside GRAPHTRAJ_PYTHON.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import electronExecutable from 'electron';

const desktop = fileURLToPath(new URL('..', import.meta.url));
const { values: options } = parseArgs({ options: {
  project: { type: 'string', default: path.join(desktop, 'dist-package', 'scope-project') },
  out: { type: 'string' }, summary: { type: 'string' }, lifecycle: { type: 'string' },
  'user-data-dir': { type: 'string' }, 'timeout-seconds': { type: 'string', default: '600' },
  part: { type: 'string', default: 'both' },
} });
const project = path.resolve(options.project);
const alias = options.lifecycle;
const part = options.part;
assert.ok(['scope', 'archive', 'both'].includes(part), 'Give --part scope, archive or both');
assert.ok(alias || part === 'archive' || options.summary, 'Give --summary <task-id>, --part archive or --lifecycle <alias>');
assert.ok(options['user-data-dir'], 'Give --user-data-dir <dir> for the Electron profile');
const tool = process.env.GRAPHTRAJ_TOOL
  || (process.env.GRAPHTRAJ_PYTHON && path.join(path.dirname(process.env.GRAPHTRAJ_PYTHON), 'graphtraj-tool'));
assert.ok(tool, 'Set GRAPHTRAJ_PYTHON (or GRAPHTRAJ_TOOL) to the candidate backend');
const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: desktop, encoding: 'utf8' }).trim();
const dirty = execFileSync('git', ['status', '--porcelain', '--', '.'], { cwd: desktop, encoding: 'utf8' }).trim();
const evidence = path.resolve(options.out || path.join(desktop, 'dist-package', 'adoption-evidence',
  `336-${commit.slice(0, 12)}${alias ? '-lifecycle' : ''}`));
const profile = path.resolve(options['user-data-dir']);
const timeout = Number(options['timeout-seconds']) * 1000;
const config = path.join(project, '.graphtraj', 'swarm', 'config.yml');
const facts = { commit, dirty: Boolean(dirty), project, mode: alias ? 'lifecycle' : part, summary: options.summary ?? null,
  alias: alias ?? null, tool, electron: electronExecutable, profile, launches: 0, steps: [], screenshots: [], passed: false };
await fs.mkdir(evidence, { recursive: true });

let app;
let page;
let finished = false;
class Timeout extends Error {}
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
  const column = page.locator(`[data-agent-id="${alias}"]`).first();
  const heading = column.locator('.agent-column-heading');
  await heading.waitFor();
  const wanted = ['active', 'standby', 'active', 'standby'];
  const seen = [];
  facts.lifecycle = seen;
  const deadline = Date.now() + timeout;
  let matched = 0;
  while (matched < wanted.length) {
    if (Date.now() > deadline) throw new Timeout(`Timed out; displayed states ${JSON.stringify(seen.map(item => item.state))}`);
    const shown = await heading.locator('h2').getAttribute('title');
    const state = (await heading.locator('span').first().innerText()).split('·').at(-1).trim();
    const parent = (await column.locator('.agent-column-parent span').innerText()).replace(/^Parent: /, '');
    if (state !== seen.at(-1)?.state) {
      const at = new Date().toISOString();
      const screenshot = `lifecycle-${at.replace(/[:.]/g, '-')}-${state}.png`;
      await shot(screenshot);
      seen.push({ at, alias: shown, state, parent, screenshot });
      await fs.appendFile(path.join(evidence, 'states.jsonl'), JSON.stringify(seen.at(-1)) + '\n');
      step(`${shown} displayed ${state} · parent ${parent}`);
      if (state === wanted[matched]) matched += 1;
    }
    await page.waitForTimeout(500);
  }
}

/** Record the outcome and always close the owned Electron window. */
async function finish(error) {
  if (finished) return;
  finished = true;
  if (error) {
    facts.failure = String(error);
    if (page) await shot(`failure-${new Date().toISOString().replace(/[:.]/g, '-')}.png`).catch(() => {});
    process.exitCode = error instanceof Timeout ? 2 : 1;
  }
  if (app) await app.close().catch(() => { facts.closeError = 'Owned app close rejected'; });
  await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
  console.log(JSON.stringify({ phase: 'CLOSED', evidence, passed: facts.passed }));
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => void finish(new Error(`Stopped by ${signal}`)).then(() => process.exit(1)));
// Playwright can report a failed Electron start outside the awaited call.
process.once('uncaughtException', error => void finish(error).then(() => process.exit(1)));

try {
  app = await electron.launch({ executablePath: electronExecutable, timeout: 20000,
    args: [desktop, `--project=${project}`, `--user-data-dir=${profile}`],
    env: { ...process.env, GRAPHTRAJ_TOOL: tool, MAC_CHROMIUM_TMPDIR: profile } });
  facts.launches += 1;
  page = await app.firstWindow();
  page.setDefaultTimeout(20000);
  if (alias || part !== 'archive') await click(page.getByRole('button', { name: 'Members', exact: true }));
  if (alias) await lifecycle();
  else {
    if (part !== 'archive') await scope();
    if (part !== 'scope') await archive();
  }
  facts.passed = true;
  await finish();
} catch (error) {
  await finish(error);
}
