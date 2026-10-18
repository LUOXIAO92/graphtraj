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
 *     [--part scope --summary <task-id>] [--timeout-seconds 600]
 *     Optionally run the scope part first in the same window. Then select that member in the
 *     current scope with the mouse and only watch its displayed state while the operator stops
 *     and continues it. When watching starts it prints 'WATCHER READY <state>' and writes
 *     <out>/ready.json. Each change is screenshotted and appended to <out>/states.jsonl.
 *     Exit 0 after active, standby, active, standby; exit 2 on timeout with a final
 *     screenshot; exit 1 on any other failure.
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
assert.ok(!alias || part === 'scope' || (part === 'both' && !options.summary), 'Combine --lifecycle only with --part scope --summary <task-id>');
assert.ok(part !== 'scope' || options.summary, 'Give --summary <task-id> with --part scope');
// With --lifecycle, the scope part runs first only when it is asked for explicitly.
const runScope = alias ? part === 'scope' : part !== 'archive';
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
const facts = { commit, dirty: Boolean(dirty), project, mode: alias ? (runScope ? 'scope+lifecycle' : 'lifecycle') : part, summary: options.summary ?? null,
  alias: alias ?? null, tool, electron: electronExecutable, profile, launches: 0, steps: [], screenshots: [], passed: false };
await fs.mkdir(evidence, { recursive: true });

let app;
let page;
let finished = false;
class Timeout extends Error {}
const step = text => { facts.steps.push({ at: new Date().toISOString(), text }); console.log(text); };
const shot = async name => { const file = path.join(evidence, name); await page.screenshot({ path: file }); facts.screenshots.push(file); };
/** Bring a control fully into the window with the real mouse wheel, then click its centre.
 * Visible in the DOM is not inside the window, so the box is checked against the window. */
const click = async locator => {
  await locator.waitFor({ state: 'visible' });
  const window = page.viewportSize() ?? await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  let box;
  for (let attempt = 0; ; attempt += 1) {
    box = await locator.boundingBox();
    if (box && box.y >= 0 && box.x >= 0 && box.y + box.height <= window.height && box.x + box.width <= window.width) break;
    if (attempt >= 40) throw new Error(`Control never came fully into the ${window.width}x${window.height} window; last box ${JSON.stringify(box)}`);
    // Wheel over the visible part of the nearest scrolling container.
    const area = await locator.evaluate(element => {
      let node = element.parentElement;
      while (node && !(node.scrollHeight > node.clientHeight && /auto|scroll/.test(getComputedStyle(node).overflowY))) node = node.parentElement;
      const rect = (node ?? document.scrollingElement).getBoundingClientRect();
      const top = Math.max(rect.top, 0), bottom = Math.min(rect.bottom, innerHeight);
      return { x: Math.max(rect.left, 0) + Math.min(rect.width, innerWidth) / 2, y: (top + bottom) / 2 };
    });
    await page.mouse.move(area.x, area.y);
    const offset = box.y + box.height / 2 - window.height / 2;
    await page.mouse.wheel(0, Math.sign(offset) * Math.min(Math.abs(offset), window.height * 0.8));
    await page.waitForTimeout(150);
  }
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
};
/** Focus a select with the mouse and step to the option value with arrow keys only. */
const choose = async (locator, value, prefix) => {
  await click(locator);
  await page.keyboard.press('Escape');
  const values = await locator.evaluate(select => [...select.options].map(option => option.value));
  const target = values.indexOf(value);
  assert.ok(target >= 0, `Option ${JSON.stringify(value)} is not offered`);
  const current = () => locator.evaluate(select => select.value);
  for (let presses = 0; await current() !== value; presses += 1) {
    assert.ok(presses < 2 * values.length + 4, `Arrow keys did not reach option ${JSON.stringify(value)}`);
    const key = values.indexOf(await current()) < target ? 'ArrowDown' : 'ArrowUp';
    const before = await current();
    await page.keyboard.press(key);
    await page.waitForTimeout(100);
    // Where an arrow key opens the popup instead, move inside it and commit with Enter.
    if (await current() === before) {
      await page.keyboard.press(key);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(100);
    }
  }
  const text = await locator.evaluate(select => select.selectedOptions[0]?.textContent ?? '');
  assert.equal(await current(), value);
  assert.ok(text.startsWith(prefix), `Selected ${JSON.stringify(text)}, expected ${JSON.stringify(prefix)}`);
  return text;
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

  facts.historySelected = await choose(page.getByLabel('Member scope'), options.summary, `History · #${options.summary} `);
  await page.getByText('History of one summary', { exact: false }).waitFor();
  await listed();
  facts.historyNotice = await notice();
  facts.history = await rows();
  step(`history of #${options.summary}: ${facts.history.length} members`);
  await shot('02-members-history.png');

  facts.currentSelected = await choose(page.getByLabel('Member scope'), '', 'Current summaries');
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
  const ready = { at: new Date().toISOString(), alias: await heading.locator('h2').getAttribute('title'),
    state: (await heading.locator('span').first().innerText()).split('·').at(-1).trim() };
  facts.ready = ready;
  await fs.writeFile(path.join(evidence, 'ready.json'), JSON.stringify(ready, null, 2));
  console.log(`WATCHER READY ${ready.state}`);
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
  if (alias || runScope) await click(page.getByRole('button', { name: 'Members', exact: true }));
  if (runScope) await scope();
  if (alias) await lifecycle();
  else if (part !== 'scope') await archive();
  facts.passed = true;
  await finish();
} catch (error) {
  await finish(error);
}
