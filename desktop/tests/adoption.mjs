/**
 * Installed macOS adoption check for the packaged desktop app.
 *
 * This is not a unit test: it starts the `.app` that was actually installed on
 * this operating system, drives its real user interface, and records the
 * observed facts, commands and screenshots as evidence.
 *
 * Usage: GRAPHTRAJ_APP=/Applications/GraphTraj.app node tests/adoption.mjs
 *
 * Environment:
 *   GRAPHTRAJ_APP       installed `.app` bundle (required)
 *   GRAPHTRAJ_EVIDENCE  evidence output directory (default: dist-package/adoption-evidence)
 *   GRAPHTRAJ_ADOPTION_SECRET random marker used to check for credential leakage
 *   GRAPHTRAJ_WORK      fixture working directory (default: dist-package/adoption-work)
 *
 * The native tool is resolved from PATH or GRAPHTRAJ_TOOL, the same mechanism
 * the app uses in production. No project, session or credential is uploaded.
 * Fixtures live outside the evidence directory, so nothing uploaded can contain
 * a test project, user data or credential.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';
import { settingsAdoption } from './settings-adoption.mjs';
import { approvalDialogs, guardApprovals, openTask, projectsView, removeIndexEntry, selectedTask, taskCard,
  visibleState } from './adoption-shared.mjs';

const desktop = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const require = createRequire(import.meta.url);
const app = process.env.GRAPHTRAJ_APP && path.resolve(process.env.GRAPHTRAJ_APP);
const evidence = path.resolve(process.env.GRAPHTRAJ_EVIDENCE || path.join(desktop, 'dist-package', 'adoption-evidence'));
const screens = path.join(evidence, 'screens');
// Fixtures are working data, never uploaded: keep them beside the evidence.
const work = path.resolve(process.env.GRAPHTRAJ_WORK || path.join(desktop, 'dist-package', 'adoption-work'));
const isolatedHome = path.join(work, 'home');
const userData = path.join(work, 'user-data');
const secret = process.env.GRAPHTRAJ_ADOPTION_SECRET || `adoption-${randomUUID()}`;
const facts = { app: app ?? null, evidence, work, steps: [], screenshots: [], nativeDialogs: [], passed: false };

/** Record one observed step so the evidence states what was actually exercised. */
function step(text) {
  facts.steps.push(text);
  console.log(`- ${text}`);
}

/** Run a command and return its trimmed output; used for environment facts. */
function capture(command, args) {
  try { return execFileSync(command, args, { encoding: 'utf8' }).trim(); }
  catch (error) { return `unavailable: ${error.message}`; }
}

/** Write the evidence file; safe to call repeatedly and before cleanup. */
async function persist() {
  await fs.mkdir(evidence, { recursive: true });
  await fs.writeFile(path.join(evidence, 'evidence.json'), JSON.stringify(facts, null, 2) + '\n');
}

/**
 * Bound one asynchronous step so a stuck renderer or helper reports a recorded
 * failure instead of hanging the whole run.
 */
async function bounded(label, operation, milliseconds = 30000) {
  let timer;
  try {
    return await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out after ${milliseconds}ms`)), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}

/** Snapshot every regular file below a root as `relative path -> sha256`. */
async function snapshot(root) {
  const found = new Map();
  async function walk(directory) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile()) {
        found.set(path.relative(root, full),
          createHash('sha256').update(await fs.readFile(full)).digest('hex'));
      }
    }
  }
  await walk(root);
  return found;
}

/** List the files whose content or presence changed between two snapshots. */
function changed(before, after) {
  const names = new Set([...before.keys(), ...after.keys()]);
  return [...names].filter(name => before.get(name) !== after.get(name)).sort();
}

/** Locate the loader Playwright needs to drive a packaged Electron app. */
function electronLoader() {
  return path.join(path.dirname(require.resolve('playwright-core/package.json')),
    'lib', 'server', 'electron', 'loader.js');
}

/** Return any remaining desktop process ('' when the app really exited). */
function desktopProcesses() {
  try {
    return execFileSync('pgrep', ['-fl', `${app}/Contents`], { encoding: 'utf8' }).trim();
  } catch (error) {
    return error.status === 1 ? '' : `unavailable: ${error.message}`;
  }
}

/** Wait briefly for a killed app's helper processes to be reaped. */
async function waitForNoDesktopProcesses(timeout = 15000) {
  const deadline = Date.now() + timeout;
  let last = '';
  do {
    last = desktopProcesses();
    if (last === '') return '';
    await new Promise(resolve => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  return last;
}

/**
 * Ask the operating system to drive a real native dialog through System Events.
 *
 * Returns the attempt outcome instead of throwing, so a blocked automation
 * becomes recorded evidence rather than a silent fallback.
 */
function uiAutomation(lines) {
  const args = lines.flatMap(line => ['-e', line]);
  try {
    const output = execFileSync('osascript', args, { encoding: 'utf8', timeout: 30000 }).trim();
    return { ok: true, command: `osascript ${args.map(a => JSON.stringify(a)).join(' ')}`, output };
  } catch (error) {
    const detail = `${error.stderr ?? ''}${error.stdout ?? ''}`.trim() || error.message;
    return { ok: false, command: `osascript ${args.map(a => JSON.stringify(a)).join(' ')}`,
      output: `exit ${error.status ?? 'timeout'}: ${detail}` };
  }
}

/**
 * Read one Session through the public desktop-activity boundary, exactly as the
 * installed app's observer process does. The expected UI content is taken from
 * this boundary so the assertion is not invented at the interface.
 */
function queryActivity(root, taskId, alias) {
  const reply = JSON.parse(execFileSync(process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool',
    ['--desktop-observer', '--allowed-features', 'desktop_activity'], {
      cwd: root, encoding: 'utf8',
      input: JSON.stringify({ action: 'execute', feature: 'desktop_activity',
        arguments: { task_id: taskId, ...(alias ? { alias } : {}) } }) + '\n',
    }));
  if (reply.failed) throw new Error(JSON.stringify(reply));
  assert.equal(reply.result.scope, 'human', 'CI must be an unbound desktop host; never strip Agent identity to obtain access');
  return reply.result;
}

/**
 * Launch the installed bundle with Playwright's Electron driver.
 *
 * A packaged app cannot be started through the `electron` npm module, so the
 * driver's loader is passed explicitly; everything else is the app's own start.
 */
async function launch(extraEnvironment = {}, extraArgs = []) {
  const binary = path.join(app, 'Contents', 'MacOS', path.basename(app, '.app'));
  return electron.launch({
    executablePath: binary,
    args: ['-r', electronLoader(), ...(process.env.GRAPHTRAJ_ADOPTION_USAGE_ONLY === '1' ? [] : [`--user-data-dir=${userData}`]), ...extraArgs],
    env: { ...process.env, ...(process.env.GRAPHTRAJ_ADOPTION_USAGE_ONLY === '1' ? {} : { HOME: isolatedHome }), ...extraEnvironment },
    timeout: 60000,
  });
}

/** Capture one window screenshot inside the evidence folder. */
async function shot(page, name) {
  const file = path.join(screens, name);
  await page.screenshot({ path: file });
  return path.relative(evidence, file);
}

/** Locate a project entry in the sidebar by its directory name. */
function projectEntry(page, name) {
  return page.locator('.project-button').filter({ hasText: name });
}

/**
 * Read only the selected project's visible monitor, including paused offsets.
 * D: X6 canvas viewport transform, the pressed task title, and the task's
 * "Expanded agent conversations" reader (main.tsx GraphView, Activity.tsx).
 */
async function monitorPosition(page) {
  return page.locator('.monitor-page:visible').evaluate(element => {
    const reader = element.querySelector('section[aria-label="Expanded agent conversations"]');
    return {
      query: element.querySelector('input[aria-label="Search tasks"]').value,
      filter: element.querySelector('select[aria-label="Task status"]').value,
      selected: element.querySelector('.native-task-card .native-task-title[aria-pressed="true"]')
        ?.closest('.native-task-card').getAttribute('data-task-id'),
      viewport: element.querySelector('.x6-graph-svg-viewport').getAttribute('transform'),
      horizontal: reader?.querySelector('.agent-columns')?.scrollLeft ?? null,
      vertical: [...(reader?.querySelectorAll('.activity-history') ?? [])].map(column => column.scrollTop),
      following: [...(reader?.querySelectorAll('.reading-toolbar') ?? [])].map(controls => controls.querySelector('button').textContent),
    };
  });
}

/**
 * D usage totals format, restated from desktop/src/UsageDashboard.tsx:78 compactNumber
 * (used for the totals through `display`, UsageDashboard.tsx:64). Below 1000 it is the
 * renderer's toLocaleString, so callers format those values in the page.
 */
const compactNumber = value => value >= 1000000 ? `${(value / 1000000).toFixed(2)}M`
  : value >= 1000 ? `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}k` : value.toLocaleString();
/** The card status of a task, restated from desktop/src/monitor-graph.ts taskStatus. */
const cardStatus = task => task.disposition && task.disposition !== 'active' ? task.disposition
  : !task.active ? 'inactive' : task.status;

/**
 * The selected project's Model field. D keeps each visited project's Teams page
 * mounted while concealed, so label lookups keep only the visible match.
 */
const visibleModel = page => page.getByLabel('Model', { exact: true }).filter({ visible: true });

/** Show a legacy role's saved Model field (Settings.tsx 'Saved project model settings'). */
async function openSavedModel(page) {
  const summary = page.locator('summary').filter({ hasText: /^Saved project model settings$/ }).filter({ visible: true });
  if (await summary.locator('..').getAttribute('open') === null) await summary.click();
  await visibleModel(page).waitFor();
}

/** Generate long, visibly controlled native message records without model calls. */
function longRecords(member) {
  return Array.from({ length: 70 }, (_, index) => ({ type: 'response_item', payload: {
    type: 'message', role: 'assistant', content: [{ type: 'output_text',
      text: `Controlled retained ${member} message ${index}.\n` + 'Long native record for independent scrolling. '.repeat(18) }],
  } }));
}

/**
 * Attempt to drive the app's real native dialogs through OS automation.
 *
 * The main flow substitutes Electron's dialog API so the surrounding checks stay
 * deterministic. This phase instead asks the operating system (System Events) to
 * operate the real folder open panels (Add project and Relocate), and records the
 * exact command and output of every attempt. When a host blocks assistive control,
 * the recorded failure is the evidence rather than a silent fallback. D saves
 * settings directly (no approval sheet since 045ef3a4), so this real window also
 * checks direct Save/Cancel with a stub that counts any approval dialog.
 */
async function nativeDialogAttempt(first) {
  const attempts = [];
  // `required` marks the adoption operations the result depends on;
  // diagnostic attempts only explain a blocker and never gate the result.
  const attempt = (name, lines, required = false) => {
    const outcome = uiAutomation(lines);
    attempts.push({ name, required, ok: outcome.ok, command: outcome.command, output: outcome.output });
    return outcome.ok;
  };

  // Establish whether this session may automate another process at all.
  attempt('system events can list processes', ['tell application "System Events" to return name of first process']);

  // This directory is not preloaded, so it only appears when the real panel
  // actually returns it; a substituted answer could not add it.
  const added = path.join(work, 'native-project');
  await fixtures.makeProject(added, 'native-project');
  const addedRoot = await fs.realpath(added);
  // Likewise only the real Relocate panel can point the entry at this directory.
  const relocatedTarget = path.join(work, 'native-relocated');
  await fixtures.makeProject(relocatedTarget, 'native-relocated');
  const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
  const original = await fs.readFile(rolesFile, 'utf8');
  let native = null;
  try {
    native = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret },
      [`--project=${first}`, `--user-data-dir=${path.join(work, 'native-user-data')}`]);
    const page = await native.firstWindow();
    page.setDefaultTimeout(20000);
    await guardApprovals(native);
    await projectEntry(page, 'first-project').waitFor();

    // The real open panel raised by the native "Add project" entry (D: Projects view).
    await projectsView(page);
    await page.getByRole('button', { name: 'Add project', exact: true }).click();
    await page.waitForTimeout(3000);
    attempt('open panel: go to folder, type the path, open it', [
      'tell application "System Events"',
      'tell process "GraphTraj"',
      'set frontmost to true',
      'keystroke "g" using {command down, shift down}',
      'delay 1',
      `keystroke "${added}"`,
      'delay 1',
      'key code 36',
      'delay 1',
      'key code 36',
      'end tell',
      'end tell',
    ]);
    await page.waitForTimeout(2000);
    const picked = await projectEntry(page, 'native-project').count();
    attempts.push({ name: 'open panel: the typed directory became a project', required: true, ok: picked > 0,
      command: "page.locator('.project-button') text match count",
      output: `${picked} entry matching native-project` });

    // The real open panel raised by the native "Relocate <root>" entry. D removed the
    // approval sheet (045ef3a4), so the second real OS dialog is this panel.
    const pickedEntry = (await page.evaluate(() => window.graphtraj.projects())).projects
      .find(project => project.root === addedRoot);
    if (pickedEntry) {
      await page.getByRole('button', { name: `Relocate ${pickedEntry.root}`, exact: true }).click();
      await page.waitForTimeout(3000);
      attempt('relocate panel: go to folder, type the path, open it', [
        'tell application "System Events"',
        'tell process "GraphTraj"',
        'set frontmost to true',
        'keystroke "g" using {command down, shift down}',
        'delay 1',
        `keystroke "${relocatedTarget}"`,
        'delay 1',
        'key code 36',
        'delay 1',
        'key code 36',
        'end tell',
        'end tell',
      ]);
      await page.waitForTimeout(2000);
    }
    const relocatedRoot = await fs.realpath(relocatedTarget);
    const afterRelocate = (await page.evaluate(() => window.graphtraj.projects())).projects;
    const moved = afterRelocate.find(project => project.id === pickedEntry?.id);
    attempts.push({ name: 'relocate panel: the typed directory became the indexed path', required: true,
      ok: !!moved && moved.root === relocatedRoot,
      command: 'window.graphtraj.projects() root of the entry added through the open panel',
      output: pickedEntry ? `${pickedEntry.root} -> ${moved?.root ?? 'entry missing'}` : 'no open-panel entry to relocate' });

    // Direct Save and Cancel in this same real window: no approval dialog may appear.
    await projectEntry(page, 'first-project').click();
    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await openSavedModel(page);
    await visibleModel(page).fill('native-approved-model');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Settings saved.' }).waitFor();
    const approved = await fs.readFile(rolesFile, 'utf8');
    attempts.push({ name: 'direct Save: the saved change was written without an approval dialog',
      required: true,
      ok: approved.includes('model: native-approved-model') && await approvalDialogs(native) === 0,
      command: `read ${path.relative(work, rolesFile)}; count dialog.showMessageBox`,
      output: `${approved.split('\n').filter(line => line.includes('model:')).join('; ')}; approval dialogs ${await approvalDialogs(native)}` });

    await visibleModel(page).fill('native-cancelled-model');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    const cancelled = await fs.readFile(rolesFile, 'utf8');
    attempts.push({ name: 'Cancel: the discarded change was not written',
      required: true,
      ok: cancelled === approved && await visibleModel(page).inputValue() === 'native-approved-model',
      command: `read ${path.relative(work, rolesFile)}`,
      output: cancelled.split('\n').filter(line => line.includes('model:')).join('; ') });

    // Cover the global write boundary in this same real OS window too.
    if (!await page.getByRole('button', { name: 'Agents & models', exact: true }).isVisible()) {
      await page.getByRole('button', { name: 'Settings', exact: true }).click();
    }
    await page.getByRole('button', { name: 'Agents & models', exact: true }).click();
    await page.getByRole('navigation', { name: 'Runtime provider model hierarchy', exact: true }).waitFor();
    const { selected } = await page.evaluate(() => window.graphtraj.projects());
    for (const [provider, answer] of [['native-approved', 'Save'], ['native-declined', 'Cancel']]) {
      const before = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), selected);
      await page.locator('.library-select').filter({ hasText: 'shared' }).first().click();
      await page.locator('.d-library-detail-heading').getByRole('button', { name: 'Add provider', exact: true }).click();
      await page.getByRole('dialog').getByLabel('Provider name', { exact: true }).fill(provider);
      await page.getByRole('dialog').getByRole('button', { name: 'Add provider', exact: true }).click();
      await page.getByRole('button', { name: answer, exact: true }).click();
      if (answer === 'Save') {
        await page.getByRole('status').filter({ hasText: 'Connections saved.' }).waitFor();
        const saved = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), selected);
        assert.ok(Object.hasOwn(saved.catalog.runtimes.shared.providers, provider));
      } else {
        await page.getByText('All changes saved', { exact: true }).filter({ visible: true }).waitFor();
        assert.equal((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), selected)).revision, before.revision);
      }
      assert.equal(await approvalDialogs(native), 0, 'D saves directly; no approval dialog may appear');
      assert.ok(!(await page.evaluate(() => document.body.innerText)).includes(secret));
      attempts.push({ name: `global native ${answer}: readback verified`, required: true, ok: true });
    }
    facts.screenshots.push(await shot(page, '12-native-global-refusal.png'));
  } catch (error) {
    attempts.push({ name: 'native dialog attempt', required: true, ok: false, command: 'tests/adoption.mjs',
      output: String((error && error.message) || error) });
  } finally {
    if (native) {
      native.process().kill('SIGKILL');
      await native.close().catch(() => {});
    }
    await fs.writeFile(rolesFile, original);
  }
  return attempts;
}

/** Focused #286 installed-app check; prior native dialogs/settings evidence is reused. */
async function usageHistoryAdoption() {
  const root = await fs.mkdtemp(path.join(work, 'usage-'));
  const first = await fixtures.makeProject(path.join(root, 'usage-first'), 'usage-first');
  const second = await fixtures.makeProject(path.join(root, 'usage-second'), 'usage-second');
  const { localDate, defaultDates } = await import('../src/usage.ts');
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const count = (time, input, cache, output, totalInput = input, totalOutput = output) => ({
    ...(time ? { timestamp: time.toISOString() } : {}), type: 'event_msg',
    payload: { type: 'token_count', info: {
      last_token_usage: { input_tokens: input, cached_input_tokens: cache, output_tokens: output,
        reasoning_output_tokens: 20 },
      total_token_usage: { input_tokens: totalInput, output_tokens: totalOutput },
    } },
  });
  const trace = await fixtures.recordActivity(first, { taskId: '1', taskName: 'usage-first', alias: 'research@x1',
    records: [
      { type: 'turn_context', payload: { model: 'gpt-5.3-codex' } },
      ...longRecords('usage-first'), count(yesterday, 2000, 1000, 160), count(today, 1000, 600, 80, 3000, 240),
    ], additionalMembers: [{ alias: 'undated@x2', historical: true, records: [count(null, 11, 1, 2)] }],
  });
  await fixtures.recordActivity(second, { taskId: '1', taskName: 'usage-second', alias: 'second-only@x1',
    records: [{ type: 'turn_context', payload: { model: 'unpriced-controlled-model' } }, count(today, 500, 50, 40)] });
  const native = queryActivity(first, '1', 'research@x1');
  assert.equal(native.events.filter(event => event.kind === 'usage').length, 2);
  assert.equal(queryActivity(first, '1', 'undated@x2').events.find(event => event.kind === 'usage').time, null);
  facts.nativeEvidence = {
    controlled: 'Disposable retained usage over public desktop_activity; no model execution or new real-cost evidence.',
    reused: ['#285 installed macOS run38082337444: native directory/index and D monitor', '#262/#263 real ownership, pricing and Runtime evidence'],
  };
  await assert.rejects(fs.access(path.join(os.homedir(), '.graphtraj/projects.json')), { code: 'ENOENT' });
  let handle;
  let page;
  const selectDates = async (from, to) => {
    await page.getByLabel('Start date', { exact: true }).fill(from);
    await page.getByLabel('End date', { exact: true }).fill(to);
  };
  const table = caption => page.getByRole('table', { name: caption, exact: true });
  const inputValue = async (caption, name) => table(caption).getByRole('row').filter({ hasText: name })
    .locator('td').nth(1).evaluate(cell => cell.firstChild.textContent.replaceAll(',', ''));
  const waitInput = async (caption, name, value) => {
    const until = Date.now() + 30000;
    while (Date.now() < until) {
      if (await inputValue(caption, name).catch(() => '') === String(value)) return;
      await page.waitForTimeout(250);
    }
    assert.equal(await inputValue(caption, name), String(value));
  };
  try {
    handle = await launch({}, [`--project=${first}`]);
    page = await handle.firstWindow();
    page.setDefaultTimeout(30000);
    await projectEntry(page, 'usage-first').waitFor();
    // Reuse established native-picker evidence; only its controlled answer is needed here.
    await handle.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] });
    }, second);
    await page.getByRole('button', { name: 'Add project', exact: true }).click();
    await projectEntry(page, 'usage-second').waitFor();
    await projectEntry(page, 'usage-first').click();
    // Selection saves asynchronously; both retained project monitors have a Task 1.
    // Require this project's title so click cannot latch onto the outgoing monitor.
    const firstNode = page.locator('.monitor-page:visible .react-flow__node[data-id="1"]')
      .filter({ has: page.getByText('usage first', { exact: true }) });
    await firstNode.click();
    // The collapsed Task detail shows the roster; chat readers activate on expansion.
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    const column = page.locator('.monitor-page:visible')
      .getByRole('article', { name: 'research@x1', exact: true }).locator('.activity-history');
    const lastMessage = native.events.filter(event => event.kind === 'message').at(-1);
    assert.ok(lastMessage?.text);
    await column.getByText(lastMessage.text, { exact: true }).waitFor();
    await column.evaluate(element => { element.scrollTop = 200; element.dispatchEvent(new Event('scroll')); });
    const position = await monitorPosition(page);
    await page.getByRole('button', { name: 'Project usage', exact: true }).click();
    assert.equal(await page.getByLabel('Start date').inputValue(), defaultDates().from);
    assert.equal(await page.getByLabel('End date').inputValue(), localDate(today));
    await waitInput('Model breakdown', 'gpt-5.3-codex', 3000);
    await page.locator('.usage-filters select').nth(1).selectOption('undated@x2');
    assert.equal(await table('Model breakdown').locator('tbody tr').count(), 0);
    await page.locator('.usage-filters select').nth(1).selectOption('');
    await selectDates(localDate(today), localDate(today));
    await waitInput('Model breakdown', 'gpt-5.3-codex', 1000);
    assert.match(await table('Model breakdown').innerText(), /0\.001925/);
    await page.locator('.usage-filters').getByLabel('Task', { exact: false }).selectOption('1');
    await page.locator('.usage-filters select').nth(1).selectOption('research@x1');
    await page.locator('.usage-filters select').nth(2).selectOption('gpt-5.3-codex');
    await waitInput('Daily trend (local dates)', localDate(today), 1000);
    assert.doesNotMatch(await page.locator('.usage-dashboard').innerText(), /second-only|unpriced-controlled-model/);
    facts.screenshots.push(await shot(page, 'usage-project-today.png'));
    await selectDates(localDate(today), localDate(yesterday));
    const invalidAlert = page.locator('.usage-dashboard').getByRole('alert');
    await invalidAlert.waitFor({ state: 'visible' });
    assert.ok((await invalidAlert.innerText()).trim());
    assert.equal(await table('Model breakdown').locator('tbody tr').count(), 0);
    assert.equal(await table('Daily trend (local dates)').locator('tbody tr').count(), 0);
    await selectDates('2099-01-01', '2099-01-01');
    assert.equal(await table('Model breakdown').locator('tbody tr').count(), 0);
    assert.equal(await table('Daily trend (local dates)').locator('tbody tr').count(), 0);
    facts.screenshots.push(await shot(page, 'usage-no-records.png'));
    await page.getByRole('button', { name: 'Global usage', exact: true }).click();
    await waitInput('Project comparison', first, 3000);
    await waitInput('Project comparison', second, 500);
    assert.equal(await page.locator('.usage-filters select').count(), 0);
    assert.equal(await table('Model breakdown').count(), 0);
    assert.doesNotMatch(await page.locator('.usage-dashboard').innerText(), /research@x1|second-only|unpriced-controlled-model/);
    await selectDates(localDate(today), localDate(today));
    await waitInput('Project comparison', first, 1000);
    await waitInput('Project comparison', second, 500);
    await waitInput('Daily trend (local dates)', localDate(today), 1500);
    facts.screenshots.push(await shot(page, 'usage-global-today.png'));
    await selectDates(localDate(yesterday), localDate(yesterday));
    await waitInput('Project comparison', first, 2000);
    assert.equal(await inputValue('Project comparison', second), 'Unknown');
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    assert.deepEqual(await monitorPosition(page), position);
    step('Installed project/global date totals, daily trends, internal isolation, unknown-time and empty/reversed ranges; Monitor reading position preserved.');
    // Remove only the controlled Trace after closing, proving persisted history rather than re-reading it.
    await bounded('close before history reopen', handle.close(), 15000);
    handle = null;
    await fs.rename(trace, trace + '.retained-for-test');
    handle = await launch();
    page = await handle.firstWindow();
    page.setDefaultTimeout(30000);
    await page.getByRole('button', { name: 'Global usage', exact: true }).click();
    await selectDates(localDate(today), localDate(today));
    await waitInput('Project comparison', first, 1000);
    await waitInput('Project comparison', second, 500);
    const gap = page.locator('.usage-dashboard details[open] li').first();
    await gap.waitFor({ state: 'visible' });
    assert.ok((await gap.innerText()).trim());
    const history = path.join(os.homedir(), '.graphtraj/usage-history');
    for (const file of await fs.readdir(history)) {
      assert.doesNotMatch(await fs.readFile(path.join(history, file), 'utf8'), /Controlled retained|Long native record|provider_usage/);
    }
    facts.screenshots.push(await shot(page, 'usage-reopened-without-source.png'));
    await fs.rename(trace + '.retained-for-test', trace);
    await page.getByRole('button', { name: 'Reconnect usage', exact: true }).click();
    await waitInput('Project comparison', first, 1000);
    await page.waitForTimeout(3500);
    assert.equal(await inputValue('Project comparison', first), '1000');
    step('Reopened installed app retained dated history without the original Trace; restoring/replaying it did not duplicate totals. Saved files contain normalized usage only.');
    facts.usageHistory = { firstToday: 1000, firstYesterday: 2000, secondToday: 500,
      officialEquivalentTodayUSD: 0.001925, history, unknownTimeExcluded: true };
    await bounded('close usage adoption', handle.close(), 15000);
    handle = null;
    assert.equal(await waitForNoDesktopProcesses(), '');
    assert.equal(fixtures.operate(first, 'task_graph').tasks.length, 2);
    facts.passed = true;
  } finally {
    if (!facts.passed && page && handle) facts.screenshots.push(await shot(page, 'usage-failure.png').catch(() => 'screenshot unavailable'));
    if (handle) await bounded('close usage check', handle.close(), 15000);
    await persist();
  }
}

/** Validate only the new Settings path, reusing accepted monitor/usage evidence. */
async function settingsOnlyAdoption() {
  const root = path.join(work, 'settings-fixtures');
  await fs.mkdir(root, { recursive: true });
  await fs.mkdir(isolatedHome, { recursive: true });
  const first = await fixtures.makeProject(path.join(root, 'settings-first'), 'settings-first');
  const second = await fixtures.makeProject(path.join(root, 'settings-second'), 'settings-second');
  await fixtures.recordActivity(first, { taskId: '1', taskName: 'settings-first', alias: 'research@x1',
    records: longRecords('settings-monitor'),
  });
  const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
  await fs.writeFile(rolesFile, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      reports: [report.md]\n      codex:\n        retained_custom_field: preserved\nrole_tree: {}\n');
  const secondBefore = await snapshot(second);
  let handle;
  let page;
  try {
    handle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret }, [`--project=${first}`]);
    page = await handle.firstWindow();
    page.setDefaultTimeout(30000);
    await projectEntry(page, 'settings-first').waitFor();
    await handle.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] });
      globalThis.__gtRealMessageBox = dialog.showMessageBox;
    }, second);
    await page.getByRole('button', { name: 'Add project', exact: true }).click();
    await projectEntry(page, 'settings-second').waitFor();
    await projectEntry(page, 'settings-first').click();
    await page.locator('.monitor-page:visible .react-flow__node[data-id="1"]')
      .filter({ has: page.getByText('settings first', { exact: true }) }).click();
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    const column = page.locator('.monitor-page:visible').getByRole('article', { name: 'research@x1', exact: true }).locator('.activity-history');
    await column.getByText(/Controlled retained settings-monitor message 69/).waitFor();
    await column.evaluate(element => { element.scrollTop = 200; element.dispatchEvent(new Event('scroll')); });
    const position = await monitorPosition(page);
    const projects = await page.evaluate(() => window.graphtraj.projects());
    const firstId = projects.projects.find(project => project.root === first).id;
    const secondId = projects.projects.find(project => project.root === second).id;
    const decide = async response => handle.evaluate(({ dialog }, response) => {
      dialog.showMessageBox = async () => ({ response, checkboxChecked: false });
    }, response);
    facts.settings = await settingsAdoption({ page, decide, firstId, secondId,
      runtimeHome: path.join(isolatedHome, 'codex'), step,
      shot: async name => { facts.screenshots.push(await shot(page, name)); },
    });
    assert.match(await fs.readFile(rolesFile, 'utf8'), /retained_custom_field: preserved/);
    assert.match(await fs.readFile(rolesFile, 'utf8'), /report.md/);
    assert.deepEqual(changed(secondBefore, await snapshot(second)), []);

    // Restore the actual host dialog and exercise the global review path in
    // this same installed window. Failure is retained, never retried in a new window.
    await handle.evaluate(({ dialog }) => { dialog.showMessageBox = globalThis.__gtRealMessageBox; });
    await page.getByRole('button', { name: 'Agents & models', exact: true }).click();
    await page.getByRole('button', { name: 'Reload connections', exact: true }).waitFor();
    for (const [provider, answer] of [['native-approved', 'Save settings'], ['native-declined', 'Cancel']]) {
      const before = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId);
      await page.getByLabel('Provider name', { exact: true }).fill(provider);
      await page.getByRole('button', { name: 'Add Provider', exact: true }).click();
      await page.getByRole('button', { name: 'Preview connections', exact: true }).click();
      await page.getByRole('button', { name: 'Save connections', exact: true }).click();
      await page.waitForTimeout(2500);
      const outcome = uiAutomation(['tell application "System Events"', 'tell process "GraphTraj"',
        `click button "${answer}" of sheet 1 of window 1`, 'end tell', 'end tell']);
      facts.nativeDialogs.push({ name: `Global approval: ${answer}`, required: true, ...outcome });
      assert.ok(outcome.ok, outcome.output);
      if (answer === 'Save settings') {
        await page.getByRole('status').getByText('Connections saved.', { exact: true }).waitFor();
        const saved = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId);
        assert.ok(Object.hasOwn(saved.catalog.runtimes.shared.providers, provider));
      } else {
        await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
        assert.equal((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId)).revision, before.revision);
      }
    }
    facts.settings.global = await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId);
    facts.screenshots.push(await shot(page, '11-native-global-refusal.png'));
    await page.getByRole('button', { name: 'Global usage', exact: true }).click();
    await page.getByRole('heading', { name: 'Global usage', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    assert.deepEqual(await monitorPosition(page), position);
    step('Real global native dialogs approved/refused writes; merged Global usage routing is present; returning from Settings retained monitor selection, viewport and paused reading position.');

    await bounded('close before Settings readback', handle.close(), 15000);
    handle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
    page = await handle.firstWindow();
    page.setDefaultTimeout(30000);
    await projectEntry(page, 'settings-first').waitFor();
    assert.deepEqual(await page.evaluate(id => window.graphtraj.settings(id), firstId), facts.settings.roles);
    assert.deepEqual((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId)).catalog, facts.settings.global.catalog);
    const rendered = await page.evaluate(() => document.body.innerText);
    assert.ok(!JSON.stringify(facts).includes(secret) && !rendered.includes(secret));
    facts.nativeEvidence = { reused: ['#284 actual Codex/Pi/DSH Runtime evidence (parent retained)', '#286 macOS 38089086556 accepted usage/history', '#285 accepted monitor/index'],
      controlled: 'Disposable project/Trace fixtures and deterministic host replies for draft scenarios; real OS global dialogs separately verified above. No model execution.' };
    facts.passed = true;
    step('Reopened installed app read back final global connections and project roles. Predecessor execution/usage evidence is reused.');
  } finally {
    if (!facts.passed && page && handle) facts.screenshots.push(await shot(page, 'settings-failure.png').catch(() => 'screenshot unavailable'));
    if (handle) await bounded('close Settings adoption', handle.close(), 15000);
    await persist();
  }
}

async function main() {
  assert.ok(!process.env.GRAPHTRAJ_CLI_CONNECTION && !process.env.GRAPHTRAJ_PARENT_ALIAS,
    'Use the unbound CI desktop host; do not remove inherited Agent identity markers to run adoption.');
  assert.ok(app, 'Set GRAPHTRAJ_APP to the installed .app bundle.');
  await fs.access(app);
  await fs.mkdir(screens, { recursive: true });
  const tool = capture('which', ['graphtraj-tool']);
  assert.ok(/^\/.*graphtraj-tool$/.test(tool), `graphtraj-tool must resolve from PATH, saw: ${tool}`);
  assert.ok(!tool.startsWith('/private/tmp') && !tool.startsWith(desktop),
    `native tool must be a persistent install: ${tool}`);
  Object.assign(facts, {
    os: capture('sw_vers', ['-productVersion']), kernel: capture('uname', ['-r']),
    arch: capture('uname', ['-m']), node: process.version, tool,
    candidate: capture('git', ['rev-parse', 'HEAD']), ciCommit: process.env.GITHUB_SHA ?? null,
    ciRun: process.env.GITHUB_RUN_ID ?? null, entryCommand: process.argv.join(' '),
    codesign: capture('codesign', ['-dv', app]),
  });
  if (facts.ciCommit) assert.equal(facts.candidate, facts.ciCommit);
  step(`installed bundle prepared at ${app}; native tool resolved from PATH at ${tool}`);

  if (process.env.GRAPHTRAJ_ADOPTION_SETTINGS_ONLY === '1') return settingsOnlyAdoption();

  if (process.env.GRAPHTRAJ_ADOPTION_USAGE_ONLY === '1') {
    await fs.mkdir(work, { recursive: true });
    return usageHistoryAdoption();
  }

  const root = path.join(work, 'fixtures');
  await fs.rm(root, { recursive: true, force: true });
  await fs.mkdir(root, { recursive: true });
  const second = await fixtures.makeProject(path.join(root, 'second-project'), 'second-project');
  const first = await fixtures.makeProject(path.join(root, 'first-project'), 'first-project');
  // A clearly labeled controlled record set for the selected project. These are
  // hand-written native rollout records, not a model run: no model is invoked.
  const primaryTrace = await fixtures.recordActivity(first, {
    taskId: '1', taskName: 'first-project', alias: 'research@x1',
    records: [
      { type: 'turn_context', payload: { model: 'actual-model', turn_id: 'turn-1' } },
      { type: 'response_item', payload: { type: 'message', role: 'assistant',
        content: [{ type: 'output_text', text: 'Controlled record: adoption-node-chat-verified.' }] } },
      { type: 'response_item', payload: { type: 'function_call', call_id: 'adoption-call-1',
        name: 'adoption_probe_tool', arguments: '{"command":"adoption-tool-verified"}' } },
      { type: 'response_item', payload: { type: 'function_call_output', call_id: 'adoption-call-1',
        output: 'adoption-tool-result' } },
      ...longRecords('first/research'),
      { timestamp: new Date().toISOString(), type: 'event_msg', payload: { type: 'token_count', info: {
        last_token_usage: { input_tokens: 4321, cached_input_tokens: 1234, output_tokens: 567 },
        total_token_usage: { input_tokens: 4321, output_tokens: 567 } } } },
    ],
    additionalMembers: [
      { alias: 'current@x2', historical: false, records: longRecords('first/current') },
      { alias: 'current@x3', historical: false, records: longRecords('first/other') },
      { alias: 'previous@x4', historical: true, records: longRecords('first/previous') },
    ],
  });
  await fixtures.recordActivity(second, { taskId: '1', taskName: 'second-project', alias: 'research@x1',
    records: longRecords('second/research') });
  fixtures.operate(first, 'task_revise', { product_preserving: true, caused_by_event_ids: [],
    evidence_refs: ['evidence.md'], tasks: [
      { ...fixtures.task('2', 'dependent', ['1']), disposition: 'superseded', replaced_by: ['3'],
        retirement_reason: 'Replaced by successor.',
        current_definition: fixtures.operate(first, 'task_graph', { view: 'full' }).tasks
          .find(t => t.task_id === '2').current_definition },
      { ...fixtures.task('3', 'successor', ['1']), current_definition: null },
    ] });
  const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
  const originalRoles = 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n'
    + '      model: original-model\n      api_key_env: GRAPHTRAJ_ADOPTION_SECRET\n      reports: [report.md]\nrole_tree: {}\n';
  await fs.writeFile(rolesFile, originalRoles);

  // This CI runs in a fresh OS account. Refuse to overwrite any existing index.
  await fs.mkdir(isolatedHome, { recursive: true });
  const projectsFile = path.join(isolatedHome, '.graphtraj', 'projects.json');
  const legacyFile = path.join(userData, 'projects.json');
  await assert.rejects(fs.access(projectsFile), { code: 'ENOENT' });
  const firstAlias = path.join(root, 'first-alias');
  await fs.symlink(first, firstAlias);
  const missing = path.join(root, 'missing-project');
  const legacyText = JSON.stringify({ projects: [
    { id: 'first', root: first }, { id: 'alias', root: firstAlias }, { id: 'missing', root: missing },
  ], selected: 'alias' }, null, 2);
  await fs.mkdir(path.dirname(legacyFile), { recursive: true });
  await fs.writeFile(legacyFile, legacyText, { flag: 'wx' });
  facts.index = { global: projectsFile, legacy: legacyFile };
  facts.nativeEvidence = { controlled: 'Disposable native fixture memberships and retained records; no Runtime/model launched.',
    reused: ['#265 run38043523309 installed macOS/native dialogs', '#262/#263 actual dynamic-chain evidence'],
    limits: 'Reused evidence does not prove D UI; this run must produce its own installed D observations and screenshots.' };

  const consoleMessages = [];
  let appHandle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
  let page = await appHandle.firstWindow();
  page.setDefaultTimeout(30000);
  appHandle.on('console', message => consoleMessages.push(message.text()));

  try {
    // The packaged window navigates to the renderer just after it is created.
    // Wait for the real application markup before the first evaluate, or the
    // evaluate can run against the replaced, destroyed context. D's sidebar entry
    // to the Projects view is always rendered (main.tsx sidebar).
    await page.getByRole('button', { name: 'Add or manage projects', exact: true }).waitFor();
    await guardApprovals(appHandle);
    const boundary = await bounded('read renderer boundary', page.evaluate(() => ({
      require: typeof window.require, process: typeof window.process, bridge: typeof window.graphtraj,
    })));
    assert.deepEqual(boundary, { require: 'undefined', process: 'undefined', bridge: 'object' });

    // Controlled entry check: the same "add an existing directory" entry is
    // driven with a substituted Electron answer so the flow below is
    // deterministic on every host. The real native dialogs are attempted
    // separately, with OS automation, in nativeDialogAttempt().
    async function pick(folder) {
      await appHandle.evaluate(({ dialog }, selected) => {
        dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [selected] });
      }, folder);
      await projectsView(page);
      await page.getByRole('button', { name: 'Add project', exact: true }).click();
      await page.getByRole('button', { name: 'Add project', exact: true, disabled: false }).waitFor({ state: 'visible' });
      // The Projects view does not navigate; return to the selected project's monitor.
      await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    }
    const monitorTitle = title => page.locator('.monitor-page:visible').getByRole('button', { name: title, exact: true });
    await projectEntry(page, 'first-project').waitFor();
    const migrated = await page.evaluate(() => window.graphtraj.projects());
    assert.equal(migrated.selected, 'first');
    assert.equal(migrated.projects.length, 2, 'legacy symlink alias deduplicates, missing path remains');
    assert.ok(migrated.projects.find(project => project.id === 'missing').unavailable);
    await page.getByRole('complementary', { name: 'Projects', exact: true }).getByText('Path unavailable', { exact: true }).waitFor();
    assert.equal(await fs.readFile(legacyFile, 'utf8'), legacyText);
    await pick(firstAlias);
    assert.equal((await page.evaluate(() => window.graphtraj.projects())).projects.length, 2);
    step('global index imported the legacy list, selected its canonical project, deduplicated alias and marked missing path');
    await monitorTitle('first project').waitFor();
    await pick(second);
    await monitorTitle('second project').waitFor();
    facts.screenshots.push(await shot(page, '01-two-projects-added.png'));
    step('added two isolated fixture projects and selected the second one');

    await openTask(page.locator('.monitor-page:visible'), '2');
    await page.getByRole('complementary', { name: 'Task details' }).waitFor();
    // D keeps the concealed reader mounted (aria-hidden); read the shelf the check means.
    await page.getByRole('complementary', { name: 'Task details' })
      .getByText('No participating Agents recorded.', { exact: true }).waitFor();
    facts.screenshots.push(await shot(page, '02-node-detail-chat-empty.png'));
    step('opened a node without records: the Chat surface rendered its empty state (not adoption evidence)');

    await projectEntry(page, 'first-project').click();
    await monitorTitle('first project').waitFor();
    assert.equal(await monitorTitle('second project').count(), 0);
    facts.screenshots.push(await shot(page, '03-project-switched.png'));
    step('switched the selected project: the graph shows only the selected project');

    const monitor = page.locator('.monitor-page:visible');
    const nativeGraph = fixtures.operate(first, 'task_graph');
    for (const task of nativeGraph.tasks) {
      // D cards show '#id · status' (TaskCanvas.tsx card); a replaced task shows its
      // disposition there and keeps execution status and 'Replaced / inactive' in Task facts.
      const node = taskCard(monitor, task.task_id);
      await node.waitFor();
      assert.match(await node.locator('.native-task-meta').first().innerText(),
        new RegExp(`^#${task.task_id} · ${cardStatus(task)}\\b`));
      if (!task.active) {
        await openTask(monitor, task.task_id);
        const taskFacts = page.getByRole('complementary', { name: 'Task details' }).locator('details').filter({ hasText: 'Task facts' });
        await taskFacts.locator('summary').click();
        assert.match(await taskFacts.innerText(), /Replaced \/ inactive/);
        assert.match(await taskFacts.innerText(), new RegExp(`Historical execution: ${task.status}\\.`));
        await page.getByRole('button', { name: 'Close details', exact: true }).click();
      }
    }
    facts.graph = nativeGraph;
    const globalToggle = page.getByRole('button', { name: /^GLOBAL/ });
    const projectsToggle = page.getByRole('button', { name: /^PROJECTS/ });
    // Establish the exact accessible name before testing its absence.
    await page.getByRole('button', { name: 'Settings', exact: true }).waitFor({ state: 'visible' });
    await globalToggle.click();
    assert.equal(await page.getByRole('button', { name: 'Settings', exact: true }).isVisible(), false);
    assert.equal(await projectEntry(page, 'first-project').isVisible(), true);
    await globalToggle.click();
    await projectsToggle.click();
    assert.equal(await projectEntry(page, 'first-project').isVisible(), false);
    assert.equal(await page.getByRole('button', { name: 'Settings', exact: true }).isVisible(), true);
    const projectNavigation = page.getByRole('navigation', { name: 'Current project', exact: true });
    assert.equal(await projectNavigation.locator('.section-label').innerText(), 'first-project');
    assert.deepEqual(await projectNavigation.getByRole('button').allTextContents(), ['Monitor', 'Teams & roles', 'Project usage']);
    facts.screenshots.push(await shot(page, '03c-project-list-collapsed.png'));
    await projectsToggle.click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByRole('button', { name: 'Agents & models', exact: true }).click();
    await page.getByRole('heading', { name: 'Agents & models', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: 'Agents & models', exact: true }).isVisible(), false);
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    step('GLOBAL and PROJECTS independently toggle; selected project/navigation remain outside list; Settings submenu toggles itself');

    // Retain a deliberately changed viewport and filter, not merely defaults.
    const initialViewport = await monitor.locator('.x6-graph-svg-viewport').getAttribute('transform');
    await monitor.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await page.waitForFunction(before => document.querySelector('.monitor-page[aria-hidden="false"] .x6-graph-svg-viewport')?.getAttribute('transform') !== before, initialViewport);
    const status = cardStatus(nativeGraph.tasks.find(task => task.task_id === '1'));
    await monitor.getByLabel('Task status', { exact: true }).selectOption(status);
    await monitor.getByLabel('Search tasks', { exact: true }).fill('first project');

    // Chat adoption evidence: the controlled records must render as message and
    // tool content through the same public boundary the desktop reads. Expected
    // text comes from that boundary, never from the interface under test.
    const chatBoundary = queryActivity(first, '1', 'research@x1');
    const chatEvents = chatBoundary.events ?? [];
    const message = chatEvents.find(event => event.kind === 'message' && event.role === 'assistant');
    const toolCall = chatEvents.find(event => event.kind === 'tool' && event.phase === 'call');
    assert.ok(message && message.text && toolCall && toolCall.name,
      'the public boundary must return the controlled message and tool call');
    await openTask(page.locator('.monitor-page:visible'), '1');
    await page.getByRole('complementary', { name: 'Task details' }).waitFor();
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    const reader = page.getByRole('region', { name: 'Expanded agent conversations', exact: true });
    await reader.getByText(message.text).first().waitFor();
    // D titles a tool record 'Tool · <name>' (Activity.tsx EventCard).
    await reader.getByText(`Tool · ${toolCall.name}`, { exact: true }).first().waitFor();
    const primaryColumn = page.locator('.monitor-page:visible').getByRole('article', { name: 'research@x1', exact: true });
    const toolCard = primaryColumn.locator('.activity-event').filter({ hasText: `Tool · ${toolCall.name}` }).first()
      .locator('details.tool-card');
    for (const open of [true, false, true]) {
      await toolCard.locator(':scope > summary').click();
      assert.equal(await toolCard.evaluate(element => element.open), open);
    }
    assert.equal(await toolCard.locator('.tool-details > pre').first().innerText(), typeof toolCall.arguments === 'string'
      ? toolCall.arguments : JSON.stringify(toolCall.arguments, null, 2));
    facts.screenshots.push(await shot(page, '03b-node-chat-records.png'));
    step('the controlled records rendered in Chat: the recorded message and tool call are visible');

    const members = queryActivity(first, '1').agents;
    assert.equal(members.length, 4);
    assert.ok(members.some(member => member.historical) && members.some(member => !member.historical));
    // Only the task reader's columns; the concealed Main reader is mounted too.
    const columns = reader.locator('.agent-column');
    assert.equal(await columns.count(), members.length);
    for (const member of members) {
      const column = monitor.getByRole('article', { name: member.alias, exact: true });
      await column.getByText(`${member.historical ? 'Historical' : 'Current'} · ${visibleState(member.state)}`, { exact: true }).waitFor();
      const native = queryActivity(first, '1', member.alias);
      const lastMessage = native.events.filter(event => event.kind === 'message').at(-1);
      assert.ok(lastMessage?.text);
      await column.getByText(lastMessage.text, { exact: true }).waitFor();
    }
    await columns.first().getByRole('button', { name: 'Pause following', exact: true }).click();
    assert.equal(await columns.nth(1).getByRole('button', { name: 'Pause following', exact: true }).count(), 1,
      'pausing one column must not pause its neighbor');
    for (const column of await columns.all()) {
      const pause = column.getByRole('button', { name: 'Pause following', exact: true });
      if (await pause.count()) await pause.click();
    }
    await monitor.getByRole('region', { name: 'Expanded agent conversations', exact: true }).evaluate(element => {
      element.querySelector('.agent-columns').scrollLeft = 155;
      element.querySelectorAll('.activity-history').forEach((column, index) => { column.scrollTop = 200 + index * 170; });
    });
    // Let native scroll events reach the real renderer's position handlers.
    await page.waitForTimeout(100);
    const position = await monitorPosition(page);
    assert.equal(position.selected, '1');
    assert.equal(position.query, 'first project');
    assert.equal(position.filter, status);
    assert.ok(position.horizontal > 0 && position.vertical.every((top, index) => top === 200 + index * 170));
    const appended = { type: 'response_item', payload: { type: 'message', role: 'assistant',
      content: [{ type: 'output_text', text: 'Controlled appended native record: paused D columns stay put.' }] } };
    await fs.appendFile(primaryTrace, JSON.stringify(appended) + '\n');
    assert.ok(queryActivity(first, '1', 'research@x1').events.some(event => event.text === appended.payload.content[0].text));
    await primaryColumn.getByRole('button', { name: /Follow new messages \(1\)/ }).waitFor();
    const updated = await monitorPosition(page);
    assert.deepEqual(updated.vertical, position.vertical);
    assert.equal(updated.horizontal, position.horizontal);
    facts.screenshots.push(await shot(page, '03d-parallel-current-history-paused.png'));
    facts.dReading = { before: updated, members, source: 'Native public desktop_activity over controlled retained records' };
    for (const view of ['Teams & roles', 'Project usage']) {
      await page.getByRole('button', { name: view, exact: true }).click();
      await page.getByRole('button', { name: 'Monitor', exact: true }).click();
      assert.deepEqual(await monitorPosition(page), updated, `${view} return must preserve every reading position`);
    }
    await projectEntry(page, 'second-project').click();
    await page.getByRole('button', { name: 'Close details', exact: true }).click();
    await openTask(monitor, '1');
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    const secondNative = queryActivity(second, '1', 'research@x1');
    const secondMessage = secondNative.events.find(event => event.kind === 'message').text;
    await reader.getByText(secondMessage, { exact: true }).waitFor();
    assert.equal(await reader.getByText(message.text, { exact: true }).count(), 0);
    facts.screenshots.push(await shot(page, '03e-second-project-native-chat.png'));
    await projectEntry(page, 'first-project').click();
    assert.deepEqual(await monitorPosition(page), updated, 'switching projects must retain first-project state');
    facts.dReading.afterReturn = await monitorPosition(page);
    // Also test the visible graph after returning, not only its hidden DOM in chat.
    await page.getByRole('button', { name: 'Collapse chat', exact: true }).click();
    const graphFields = ({ query, filter, selected, viewport }) => ({ query, filter, selected, viewport });
    const graphReading = graphFields(await monitorPosition(page));
    await monitor.getByLabel('Native task canvas', { exact: true }).waitFor({ state: 'visible' });
    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    assert.deepEqual(graphFields(await monitorPosition(page)), graphReading);
    facts.dReading.visibleGraph = graphReading;
    facts.screenshots.push(await shot(page, '03h-restored-graph-filter-node.png'));
    await page.getByRole('button', { name: 'Expand chat', exact: true }).click();
    assert.deepEqual(await monitorPosition(page), updated, 'collapse/expand must also restore paused column positions');
    await monitor.getByRole('region', { name: 'Agent columns', exact: true }).evaluate(element => { element.scrollLeft = element.scrollWidth; });
    await page.waitForTimeout(100);
    assert.ok((await monitorPosition(page)).horizontal > updated.horizontal, 'bottom horizontal scroll reaches offscreen columns');
    facts.screenshots.push(await shot(page, '03f-rightmost-agent-column.png'));
    await page.getByRole('button', { name: 'Hide sidebar', exact: true }).click();
    // D's sidebar is the complementary landmark 'Projects', hidden and inert when collapsed (main.tsx).
    assert.equal(await page.getByRole('complementary', { name: 'Projects', exact: true }).count(), 0);
    facts.screenshots.push(await shot(page, '03g-sidebar-hidden-chat.png'));
    await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
    await primaryColumn.getByRole('button', { name: /Follow new messages/ }).click();
    await primaryColumn.getByText(appended.payload.content[0].text, { exact: true }).waitFor();
    step('parallel current/history columns, independent pause/native append, page/project reading retention and bottom horizontal access passed');

    await page.getByRole('button', { name: 'Project usage', exact: true }).click();
    const usageDashboard = page.getByRole('region', { name: 'Usage dashboard', exact: true });
    await usageDashboard.waitFor();
    // The observation status sits in the closed history disclosure (UsageDashboard.tsx footer).
    await usageDashboard.locator('[role="status"]').filter({ hasText: 'Observation active' }).waitFor({ state: 'attached' });
    // D lists the project's models as buttons (d-model-list); there is no breakdown table.
    const modelRow = usageDashboard.getByRole('button', { name: /^actual-model\b/ });
    await modelRow.waitFor();
    const usage = (chatEvents.find(event => event.kind === 'usage') ?? {}).usage;
    assert.ok(usage && usage.tokens, 'the public boundary must return the controlled usage record');
    // D totals show compact counts (compactNumber); the dated chart keeps the exact input.
    const totals = Object.fromEntries(await usageDashboard.locator('.new-usage-totals > span').evaluateAll(cells =>
      cells.map(cell => [cell.querySelector('small').textContent, cell.querySelector('strong').textContent])));
    const totalLabels = { input: 'INPUT · INCLUDES CACHE', output: 'OUTPUT', cache_read: 'CACHE READ' };
    const chartTitles = await usageDashboard.getByRole('img', { name: /^Reported input by date/ }).locator('title')
      .evaluateAll(titles => titles.map(title => title.textContent));
    for (const [metric, value] of Object.entries(usage.tokens)) {
      assert.ok(totalLabels[metric], `usage dashboard has no D total for the boundary metric ${metric} (absent?)`);
      const expected = value >= 1000 ? compactNumber(value) : await page.evaluate(count => count.toLocaleString(), value);
      assert.equal(totals[totalLabels[metric]], expected,
        `usage dashboard must show the boundary value ${metric}=${value} as ${expected}`);
    }
    const exactInput = await page.evaluate(value => value.toLocaleString(), usage.tokens.input);
    assert.ok(chartTitles.some(title => title.endsWith(`: ${exactInput} input tokens`)),
      `usage chart must show the exact boundary input ${usage.tokens.input}`);
    facts.screenshots.push(await shot(page, '04-usage-dashboard.png'));
    facts.controlledRecords = {
      origin: 'Hand-written native rollout records retained in the fixture project; no model invoked, no cost.',
      task: '1', alias: 'research@x1',
      chat: { message: message.text, tool: toolCall.name, arguments: toolCall.arguments },
      usage: usage.tokens,
    };
    step(`opened the Usage dashboard: rendered counts match the public boundary (${JSON.stringify(usage.tokens)})`);

    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await openSavedModel(page);
    facts.screenshots.push(await shot(page, '05-settings-form.png'));
    step('opened the Settings form for the selected project');

    // D saves directly (no approval dialog since 045ef3a4; user decision in
    // docs/specs/optional-desktop-gui-mvp.md). Every Save is checked for zero
    // approval dialogs and for no credential value in the window or its logs.
    const checkSave = async label => {
      assert.equal(await approvalDialogs(appHandle), 0, `${label}: D saves directly; no approval dialog may appear`);
      const text = await bounded('read window text', page.evaluate(() => document.body.innerText));
      assert.ok(!text.includes(secret) && !consoleMessages.some(entry => entry.includes(secret)),
        `${label}: the credential value must not appear in the window or its logs`);
    };
    // Concealed pages stay mounted (visibility: hidden), so text and label lookups keep only visible matches.
    const footer = name => page.getByText(name, { exact: true }).filter({ visible: true });

    const before = await snapshot(second);
    const firstBefore = await snapshot(first);

    // Declining is Cancel: the draft is shown as a pending change, then discarded.
    await visibleModel(page).fill('denied-model');
    await footer('1 unsaved changes').waitFor();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await footer('All changes saved').waitFor();
    assert.match(await fs.readFile(rolesFile, 'utf8'), /model: original-model/);
    assert.equal(await visibleModel(page).inputValue(), 'original-model');
    await checkSave('cancelled change');
    step('direct save has no approval dialog: a cancelled change was discarded and wrote nothing');

    await visibleModel(page).fill('approved-model');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Settings saved.' }).waitFor();
    assert.match(await fs.readFile(rolesFile, 'utf8'), /model: approved-model/);
    assert.equal((await page.evaluate(id => window.graphtraj.settings(id), (await page.evaluate(() => window.graphtraj.projects())).selected))
      .roles['custom_group.observer'].model, 'approved-model');
    await checkSave('saved change');
    facts.screenshots.push(await shot(page, '06-settings-saved.png'));
    step('saved change was written by the native entry into the selected project only');

    // A real native failure: the project's configuration directory is not
    // writable, so a save must report the error and keep the file.
    const state = path.join(first, '.graphtraj');
    const saved = await fs.readFile(rolesFile, 'utf8');
    await fs.chmod(state, 0o500);
    try {
      await visibleModel(page).fill('unwritable-model');
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await page.getByRole('region', { name: 'Project settings', exact: true }).getByRole('alert').waitFor();
      facts.screenshots.push(await shot(page, '07-settings-save-error.png'));
      assert.equal(await fs.readFile(rolesFile, 'utf8'), saved, 'failed save must not change the file');
      step('a save that failed in the native entry reported an error and left the file unchanged');
    } finally { await fs.chmod(state, 0o700); }
    // D retains the failed draft ('Your unsaved changes are retained'); discard it.
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await footer('All changes saved').waitFor();

    const settingsProjects = await page.evaluate(() => window.graphtraj.projects());
    const firstId = settingsProjects.projects.find(project => project.root === first).id;
    const secondId = settingsProjects.projects.find(project => project.root === second).id;
    facts.settings = await settingsAdoption({ page, firstId, secondId, checkSave,
      runtimeHome: path.join(isolatedHome, 'codex'), step,
      shot: async name => { facts.screenshots.push(await shot(page, name)); },
    });
    const after = await snapshot(second);
    const firstAfter = await snapshot(first);
    assert.deepEqual(changed(before, after), [], 'saving settings for one project must not write another');
    const firstChanged = changed(firstBefore, firstAfter);
    assert.ok(firstChanged.every(name => name === path.join('.graphtraj', 'roles.yml')),
      `only the selected project's roles file may change, saw ${JSON.stringify(firstChanged)}`);
    const stored = JSON.parse(await fs.readFile(projectsFile, 'utf8'));
    assert.ok(stored.projects.some(project => project.root === first)
      && stored.projects.some(project => project.root === second),
    'project index must persist under HOME/.graphtraj');
    step(`settings - one project changed (${firstChanged.join(', ')}); the other stayed byte-identical`);

    // Relocation changes only an indexed path. Use a separate disposable project
    // so the retained first/second activity records never need to be rewritten.
    const relocated = await fixtures.makeProject(path.join(root, 'relocated-project'), 'relocated-project');
    const relocationBefore = await snapshot(relocated);
    await page.getByRole('button', { name: 'Monitor', exact: true }).click();
    await projectEntry(page, 'missing-project').click();
    // D: Check paths, Relocate and Remove live in the Projects view (main.tsx ProjectIndexEditor).
    await projectsView(page);
    await page.getByRole('button', { name: 'Check paths', exact: true }).click();
    await page.getByRole('row').filter({ hasText: missing }).getByText('Path unavailable', { exact: true }).waitFor();
    await appHandle.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] });
    }, relocated);
    await page.getByRole('button', { name: `Relocate ${missing}`, exact: true }).click();
    const relocatedRoot = await fs.realpath(relocated);
    // Relocation keeps the Projects view; open the relocated entry's monitor from its row.
    await page.getByRole('row').filter({ hasText: relocatedRoot }).getByRole('button', { name: 'Open', exact: true }).click();
    await monitorTitle('relocated project').waitFor();
    const relocatedIndex = await page.evaluate(() => window.graphtraj.projects());
    const relocatedEntry = relocatedIndex.projects.find(project => project.id === 'missing');
    assert.equal(relocatedEntry.root, relocatedRoot);
    assert.equal(relocatedEntry.unavailable, undefined);
    assert.equal(relocatedIndex.selected, 'missing');
    facts.screenshots.push(await shot(page, '07b-relocated-index.png'));
    await removeIndexEntry(page, relocatedEntry.root);
    await projectEntry(page, 'relocated-project').waitFor({ state: 'detached' });
    assert.deepEqual(changed(relocationBefore, await snapshot(relocated)), [], 'relocate/remove must not modify project files');
    assert.equal(fixtures.operate(relocated, 'task_graph').tasks.length, 2);
    assert.equal(await fs.readFile(legacyFile, 'utf8'), legacyText, 'migration/relocation/removal must leave legacy input intact');
    facts.index.relocated = { id: relocatedEntry.id, root: relocatedEntry.root, projectFilesUnchanged: true };
    step('invalid legacy path relocated through the native dialog entry; removing its index preserved every project file');

    // Restart the installed app without any user-data override: the standard
    // persistent location must restore the project list.
    await bounded('close installed app before restart', appHandle.close(), 15000);
    appHandle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
    page = await appHandle.firstWindow();
    page.setDefaultTimeout(30000);
    appHandle.on('console', message => consoleMessages.push(message.text()));
    await projectEntry(page, 'first-project').waitFor();
    await projectEntry(page, 'second-project').waitFor();
    await guardApprovals(appHandle);
    const reopened = await page.evaluate(() => window.graphtraj.projects());
    assert.equal(reopened.projects.length, 2);
    assert.equal(reopened.selected, 'first');
    assert.ok(!reopened.projects.some(project => project.id === 'missing'), 'legacy import must not resurrect removed entries');
    assert.equal(await fs.readFile(legacyFile, 'utf8'), legacyText);
    facts.index.reopened = reopened;
    facts.screenshots.push(await shot(page, '08-restarted-persisted.png'));
    step('restarting the installed app restored the project list from HOME/.graphtraj');
    assert.deepEqual(await page.evaluate(id => window.graphtraj.settings(id), firstId), facts.settings.roles);
    assert.deepEqual((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), firstId)).catalog, facts.settings.global.catalog);
    step('Reopening read back the final team tree and global model references from native configuration.');

    const rendered = await bounded('read window text', page.evaluate(() => document.body.innerText));
    for (const text of [rendered, ...consoleMessages]) {
      assert.ok(!text.includes(secret), 'the credential value must not appear in the window or its logs');
    }
    facts.consoleMessages = consoleMessages.length;

    const removalBefore = await snapshot(second);
    const secondRoot = reopened.projects.find(project => project.root === second).root;
    await removeIndexEntry(page, secondRoot);
    await projectEntry(page, 'second-project').waitFor({ state: 'detached' });
    assert.deepEqual(changed(removalBefore, await snapshot(second)), [], 'removing second-project must only edit the global index');
    assert.equal(fixtures.operate(second, 'task_graph').tasks.length, 2);
    facts.screenshots.push(await shot(page, '08b-index-only-removal.png'));

    // Optionality: the GUI is gone, the native operations are not.
    await bounded('close installed app before optionality check', appHandle.close(), 15000);
    appHandle = null;
    const leftovers = await waitForNoDesktopProcesses();
    assert.equal(leftovers, '', `the desktop must leave no process behind: ${leftovers}`);
    fixtures.operate(second, 'task_register', fixtures.task('3', 'after-gui-exit', ['2']));
    assert.equal(fixtures.operate(second, 'task_graph').tasks.length, 3);
    step('native operations still worked after the window closed and no desktop process remained');
    facts.optionality = { leftoverProcesses: leftovers, tasksAfterExit: 3 };

    // Evidence split: what the controlled entry covered, and the real native
    // dialog attempts recorded with their exact commands and outcomes.
    facts.controlledEntry = [
      'folder open panels (Add project, Relocate): Electron dialog.showOpenDialog substituted',
      'settings saves: direct Save/Cancel with dialog.showMessageBox replaced by a counting stub that throws (zero approval dialogs), plus a save error',
    ];

    // The overall marker reflects the required native operations, not the
    // controlled entry. A diagnostic failure only explains a blocker; a
    // required native failure keeps the result failed and the process red.
    // Six required entries: the Add and Relocate open panels, direct Save and
    // Cancel for the project, and global Save and Cancel readbacks.
    const native = await nativeDialogAttempt(first);
    facts.nativeDialogs = native;
    const required = native.filter(entry => entry.required);
    const failedNative = required.filter(entry => !entry.ok);
    facts.requiredNativeOk = required.length === 6 && failedNative.length === 0;
    facts.blockedReason = facts.requiredNativeOk ? null
      : 'required native operations did not complete: '
        + (failedNative.map(entry => `${entry.name} (${entry.output})`).join('; ')
          || 'no required attempt recorded');
    facts.passed = facts.requiredNativeOk;
    if (!facts.passed) {
      console.error(facts.blockedReason);
      process.exitCode = 1;
    }
  } finally {
    // Preserve the first failing screen when available; never restart to obtain it.
    if (!facts.passed && page && appHandle) {
      try { facts.screenshots.push(await shot(page, 'failure.png')); }
      catch (error) { facts.failureScreenshotError = String(error.message || error); }
    }
    // Preserve the observed facts before shutdown so the evidence survives even
    // when the installed app cannot close cleanly.
    await persist();
    if (appHandle) {
      try { await bounded('close installed app', appHandle.close(), 15000); }
      catch (error) { facts.cleanupError = String(error && error.message ? error.message : error); }
    }
    await persist();
  }
}

try {
  await main();
} catch (error) {
  facts.failure = String(error && error.stack ? error.stack : error);
  console.error(facts.failure);
  process.exitCode = 1;
} finally {
  await persist();
  console.log(`evidence: ${path.join(evidence, 'evidence.json')}`);
}
