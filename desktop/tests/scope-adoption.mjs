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
 *     Select that member in the current scope with the mouse and only watch its displayed
 *     state while the operator stops and continues it. With --part scope, the scope part runs
 *     afterwards in the same window, so its failure (facts.scopeFailure, exit 1) keeps the
 *     lifecycle evidence. When watching starts it prints 'WATCHER READY <state>' and writes
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
  for (let attempt = 0; ; attempt += 1) {
    // The window intersected with every clipping ancestor (for member rows: .member-tree,
    // overflow auto), and the nearest scrolling ancestor to turn the wheel over.
    const place = await locator.evaluate(element => {
      const box = element.getBoundingClientRect();
      let clip = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
      let scroller = null;
      for (let node = element.parentElement; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.overflowY !== 'visible' || style.overflowX !== 'visible') {
          const rect = node.getBoundingClientRect();
          clip = { left: Math.max(clip.left, rect.left), top: Math.max(clip.top, rect.top),
            right: Math.min(clip.right, rect.right), bottom: Math.min(clip.bottom, rect.bottom) };
        }
        if (!scroller && /auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight) scroller = node.className;
      }
      return { box: { x: box.left, y: box.top, width: box.width, height: box.height }, clip, scroller,
        inside: box.left >= clip.left && box.top >= clip.top && box.right <= clip.right && box.bottom <= clip.bottom };
    });
    const { box, clip } = place;
    if (place.inside) {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      return;
    }
    if (attempt >= 40 || !place.scroller || clip.bottom <= clip.top) {
      throw new Error(`Control never came fully into view; box ${JSON.stringify(box)}, visible area ${JSON.stringify(clip)}, scroller ${place.scroller}`);
    }
    // Real wheel over the centre of the visible area, toward the control.
    const middle = (clip.top + clip.bottom) / 2;
    const offset = box.y + box.height / 2 - middle;
    await page.mouse.move((clip.left + clip.right) / 2, middle);
    await page.mouse.wheel(0, Math.sign(offset) * Math.max(40, Math.min(Math.abs(offset), (clip.bottom - clip.top) * 0.8)));
    await page.waitForTimeout(150);
  }
};
/** Focus a select with the mouse, then reach the option value with the keyboard.
 * Options (Activity.tsx:128) are '' -> 'Current summaries' and <id> -> 'History · #<id> <title>'.
 * On a closed select, repeating an option's first letter cycles through the options starting
 * with it (host run on 7d45c57 showed type-ahead changes the value). The previous whole-label
 * type-ahead failed at the space and '·'. Arrow keys remain a fallback if a letter does nothing. */
const choose = async (locator, value, prefix) => {
  await click(locator);
  await page.keyboard.press('Escape');
  const options = await locator.evaluate(select => [...select.options].map(option => [option.value, option.textContent]));
  const target = options.findIndex(([option]) => option === value);
  assert.ok(target >= 0, `Option ${JSON.stringify(value)} is not offered: ${JSON.stringify(options)}`);
  const letter = options[target][1][0].toLowerCase();
  const current = () => locator.evaluate(select => select.value);
  for (let presses = 0; await current() !== value; presses += 1) {
    assert.ok(presses < 2 * options.length + 4, `Keyboard did not reach option ${JSON.stringify(value)}; at ${JSON.stringify(await current())}`);
    const before = await current();
    await page.keyboard.press(letter);
    await page.waitForTimeout(150);
    if (await current() !== before) continue;
    const key = options.findIndex(([option]) => option === before) < target ? 'ArrowDown' : 'ArrowUp';
    await page.keyboard.press(key);
    await page.waitForTimeout(150);
    // Where an arrow key opens the popup instead, move inside it and commit with Enter.
    if (await current() === before) {
      await page.keyboard.press(key);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(150);
    }
  }
  const text = await locator.evaluate(select => select.selectedOptions[0]?.textContent ?? '');
  assert.equal(await current(), value);
  assert.ok(text.startsWith(prefix), `Selected ${JSON.stringify(text)}, expected ${JSON.stringify(prefix)}`);
  return text;
};
// Visible member view only (Activity.tsx:126); concealed views of other projects are hidden.
const tree = () => page.locator('section.member-tree:visible');
// Each row button (Activity.tsx:132) has title = alias, an indentation of depth * 24px and
// the text '<avatar letter> <alias> Active|Standby|Retired · history · #<task> · <role> · <runtime>'.
const rows = () => tree().locator('.member-tree-rows > button').evaluateAll(buttons => buttons.map(button => ({
  alias: button.title, indent: button.style.marginLeft, text: button.innerText })));
const row = name => tree().locator(`.member-tree-rows > button[title="${name}"]`);
// The scope notice is the section's direct <p class="native-notice"> (Activity.tsx:129).
const notice = () => tree().locator(':scope > p.native-notice');
const waitNotice = text => notice().filter({ hasText: text }).waitFor();
// Loaded: a row, or the 'No members in this scope.' status (Activity.tsx:131), never 'Loading members…'.
const listed = () => tree().locator('.member-tree-rows > button, :scope > p[role="status"]:text-is("No members in this scope.")').first().waitFor();
const select = () => tree().getByLabel('Member scope', { exact: true });
// The scope change re-queries on its next render; wait past that render so old rows are not read.
const settle = () => page.waitForTimeout(3500);

/** Default scope, one historical summary and back; reading must change no member. */
async function scope() {
  await waitNotice('Members of current summaries');
  await settle();
  await listed();
  facts.currentNotice = await notice().innerText();
  const current = await rows();
  facts.current = current;
  assert.ok(current.every(item => !item.text.includes('Retired')), 'Retired members never appear in the current list');
  step(`current scope: ${facts.currentNotice} · ${current.length} members`);
  await shot('01-members-current.png');

  facts.historySelected = await choose(select(), options.summary, `History · #${options.summary} `);
  await waitNotice('History of one summary');
  await settle();
  await listed();
  facts.historyNotice = await notice().innerText();
  facts.history = await rows();
  step(`history of #${options.summary}: ${facts.history.length} members`);
  await shot('02-members-history.png');

  facts.currentSelected = await choose(select(), '', 'Current summaries');
  await waitNotice('Members of current summaries');
  await settle();
  await listed();
  const again = await rows();
  facts.currentAgain = again;
  // Members, tree position and parents must be identical. A state word may change only through
  // a live execution of that Agent, which the window cannot tell apart, so it is recorded.
  const state = text => text.match(/\b(Active|Standby)\b/)?.[1] ?? null;
  const strip = list => list.map(item => ({ ...item, text: item.text.replace(/\b(Active|Standby)\b/, '<state>') }));
  assert.deepEqual(strip(again), strip(current), 'Switching scope left members, tree positions and parents unchanged');
  facts.stateChanges = current.filter((item, index) => state(item.text) !== state(again[index].text))
    .map((item, index) => ({ alias: item.alias, before: state(item.text), after: state(again[index].text) }));
  step(`returned to current scope; members, tree and parents unchanged; state changes ${JSON.stringify(facts.stateChanges)}`);
  await shot('03-members-current-again.png');
}

/** Edit both archive switches, confirm the tool's own file, reload and restore. */
async function archive() {
  facts.configBefore = await fs.readFile(config, 'utf8').catch(() => null);
  await click(page.getByRole('button', { name: 'Teams & roles', exact: true }));
  const switches = { save_normalized_sessions: 'Save normalized Sessions',
    backfill_history: 'Backfill history of associated Sessions' };
  const fieldset = page.locator('fieldset.d-archive-settings:visible');
  await fieldset.waitFor();
  const checkbox = label => fieldset.getByLabel(label, { exact: true });
  // The fieldset is disabled while settings load or save (Settings.tsx:237).
  const enabled = async () => { for (let i = 0; await fieldset.evaluate(node => node.disabled); i += 1) { assert.ok(i < 100, 'Archive settings stayed disabled'); await page.waitForTimeout(100); } };
  // Settings toast: <div class=toast role=status><Icon svg/>{message}</div> (Settings.tsx:236).
  const toast = text => page.locator('div.toast[role="status"]:visible', { hasText: text });
  const original = {};
  for (const [name, label] of Object.entries(switches)) {
    await enabled();
    const box = checkbox(label);
    original[name] = await box.isChecked();
    await click(box);
    await toast('Saved Session archive settings.').waitFor();
    await toast('Saved Session archive settings.').waitFor({ state: 'hidden', timeout: 8000 });
  }
  facts.configEdited = await fs.readFile(config, 'utf8');
  for (const name of Object.keys(switches)) assert.ok(facts.configEdited.includes(`${name}: ${!original[name]}`), facts.configEdited);
  await click(page.getByRole('button', { name: 'Reload', exact: true }));
  await toast('Loaded current configuration.').waitFor();
  await enabled();
  for (const [name, label] of Object.entries(switches)) assert.equal(await checkbox(label).isChecked(), !original[name]);
  step(`saved ${JSON.stringify(facts.configEdited)} in swarm/config.yml and reloaded`);
  await shot('04-settings-archive-edited.png');
  for (const [, label] of Object.entries(switches)) {
    await enabled();
    await click(checkbox(label));
    await toast('Saved Session archive settings.').waitFor();
    await toast('Saved Session archive settings.').waitFor({ state: 'hidden', timeout: 8000 });
  }
  facts.configAfter = await fs.readFile(config, 'utf8');
  for (const name of Object.keys(switches)) assert.ok(facts.configAfter.includes(`${name}: ${original[name]}`), facts.configAfter);
  step('both switches restored to their original values');
  await shot('05-settings-archive-restored.png');
}

/** Only watch the selected member's displayed state; the operator drives the Agent. */
async function lifecycle() {
  await waitNotice('Members of current summaries');
  await listed();
  await click(row(alias));
  // AgentColumn (Activity.tsx:283-285): <article data-agent-id=alias><header class=agent-column-heading>
  // <Avatar span/><div><h2 title=alias/><span>Current|Historical · <state></span></div><Status span/></header>
  // <div class=agent-column-parent><Icon svg/><span>Parent: <alias></span></div>.
  const column = page.locator(`article[data-agent-id="${alias}"]:visible`);
  const heading = column.locator(':scope > header.agent-column-heading');
  await heading.waitFor();
  const read = async () => {
    const shown = await heading.locator('h2').getAttribute('title');
    const label = (await heading.locator('h2 + span').innerText()).trim();
    const parentText = (await column.locator(':scope > .agent-column-parent > span').innerText()).trim();
    const match = label.match(/^(Current|Historical) · (.+)$/);
    assert.equal(shown, alias, `Column shows ${JSON.stringify(shown)}, not the selected member`);
    assert.ok(match && ['active', 'standby'].includes(match[2]), `Displayed state must be active or standby, got ${JSON.stringify(label)}`);
    assert.ok(parentText.startsWith('Parent: '), `Unexpected parent text ${JSON.stringify(parentText)}`);
    return { alias: shown, state: match[2], label, parent: parentText.slice('Parent: '.length) };
  };
  const first = await read();
  const ready = { at: new Date().toISOString(), alias: first.alias, state: first.state, label: first.label, parent: first.parent };
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
    const { alias: shown, state, label, parent } = await read();
    if (state !== seen.at(-1)?.state) {
      const at = new Date().toISOString();
      const screenshot = `lifecycle-${at.replace(/[:.]/g, '-')}-${state}.png`;
      await shot(screenshot);
      seen.push({ at, alias: shown, state, label, parent, screenshot });
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
  // Header toggle in the visible project caption (main.tsx:87); present in every monitor view.
  const members = page.locator('header.d-monitor-caption:visible').getByRole('button', { name: 'Members', exact: true });
  if (alias || runScope) await click(members);
  if (alias) {
    // Lifecycle first: the scope part's untried select path must not cost this evidence.
    await lifecycle();
    if (runScope) {
      try {
        await click(members);
        await waitNotice('Members of current summaries');
        await scope();
      } catch (error) {
        facts.scopeFailure = String(error);
        await shot(`scope-failure-${new Date().toISOString().replace(/[:.]/g, '-')}.png`).catch(() => {});
        throw error;
      }
    }
  } else {
    if (runScope) await scope();
    if (part !== 'scope') await archive();
  }
  facts.passed = true;
  await finish();
} catch (error) {
  await finish(error);
}
