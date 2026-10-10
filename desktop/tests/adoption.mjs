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

const desktop = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const require = createRequire(import.meta.url);
const app = process.env.GRAPHTRAJ_APP && path.resolve(process.env.GRAPHTRAJ_APP);
const evidence = path.resolve(process.env.GRAPHTRAJ_EVIDENCE || path.join(desktop, 'dist-package', 'adoption-evidence'));
const screens = path.join(evidence, 'screens');
// Fixtures are working data, never uploaded: keep them beside the evidence.
const work = path.resolve(process.env.GRAPHTRAJ_WORK || path.join(desktop, 'dist-package', 'adoption-work'));
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
function queryActivity(root, ticketId, alias) {
  const reply = JSON.parse(execFileSync(process.env.GRAPHTRAJ_TOOL || 'graphtraj-tool',
    ['--desktop-observer', '--allowed-features', 'desktop_activity'], {
      cwd: root, encoding: 'utf8',
      input: JSON.stringify({ action: 'execute', feature: 'desktop_activity',
        arguments: { ticket_id: ticketId, ...(alias ? { alias } : {}) } }) + '\n',
    }));
  if (reply.failed) throw new Error(JSON.stringify(reply));
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
    args: ['-r', electronLoader(), ...extraArgs],
    env: { ...process.env, ...extraEnvironment },
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
 * Attempt to drive the app's real native dialogs through OS automation.
 *
 * The main flow substitutes Electron's dialog API so the surrounding checks stay
 * deterministic. This phase instead asks the operating system (System Events) to
 * operate the real folder open panel and the real approval sheet, and records the
 * exact command and output of every attempt. When a host blocks assistive control,
 * the recorded failure is the evidence rather than a silent fallback.
 */
async function nativeDialogAttempt(first) {
  const attempts = [];
  // `required` marks the three adoption operations the result depends on;
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
  const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
  const original = await fs.readFile(rolesFile, 'utf8');
  let native = null;
  try {
    native = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret },
      [`--project=${first}`, `--user-data-dir=${path.join(work, 'native-user-data')}`]);
    const page = await native.firstWindow();
    page.setDefaultTimeout(20000);
    await projectEntry(page, 'first-project').waitFor();

    // The real open panel raised by the native "Add project" entry.
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

    // The real approval sheet raised by the native "Save changes" entry.
    await projectEntry(page, 'first-project').click();
    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await page.getByLabel('Model', { exact: true }).waitFor();
    await page.getByLabel('Model', { exact: true }).fill('native-approved-model');
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await page.waitForTimeout(3000);
    attempt('approval sheet: click Save settings', [
      'tell application "System Events"',
      'tell process "GraphTraj"',
      'click button "Save settings" of sheet 1 of window 1',
      'end tell',
      'end tell',
    ]);
    await page.waitForTimeout(2000);
    const approved = await fs.readFile(rolesFile, 'utf8');
    attempts.push({ name: 'approval sheet: the approved change was written',
      required: true,
      ok: approved.includes('model: native-approved-model'),
      command: `read ${path.relative(work, rolesFile)}`,
      output: approved.split('\n').filter(line => line.includes('model:')).join('; ') });

    await page.getByLabel('Model', { exact: true }).fill('native-cancelled-model');
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await page.waitForTimeout(3000);
    attempt('approval sheet: click Cancel', [
      'tell application "System Events"',
      'tell process "GraphTraj"',
      'click button "Cancel" of sheet 1 of window 1',
      'end tell',
      'end tell',
    ]);
    await page.waitForTimeout(2000);
    const cancelled = await fs.readFile(rolesFile, 'utf8');
    attempts.push({ name: 'approval sheet: the cancelled change was not written',
      required: true,
      ok: !cancelled.includes('model: native-cancelled-model'),
      command: `read ${path.relative(work, rolesFile)}`,
      output: cancelled.split('\n').filter(line => line.includes('model:')).join('; ') });
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

async function main() {
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
    codesign: capture('codesign', ['-dv', app]),
  });
  step(`installed bundle launched from ${app}; native tool resolved from PATH at ${tool}`);

  const root = path.join(work, 'fixtures');
  await fs.rm(root, { recursive: true, force: true });
  await fs.mkdir(root, { recursive: true });
  const second = await fixtures.makeProject(path.join(root, 'second-project'), 'second-project');
  const first = await fixtures.makeProject(path.join(root, 'first-project'), 'first-project');
  // A clearly labeled controlled record set for the selected project. These are
  // hand-written native rollout records, not a model run: no model is invoked.
  await fixtures.recordActivity(first, {
    ticketId: '1', ticketName: 'first-project', alias: 'research@x1',
    records: [
      { type: 'turn_context', payload: { model: 'actual-model', turn_id: 'turn-1' } },
      { type: 'response_item', payload: { type: 'message', role: 'assistant',
        content: [{ type: 'output_text', text: 'Controlled record: adoption-node-chat-verified.' }] } },
      { type: 'response_item', payload: { type: 'function_call', call_id: 'adoption-call-1',
        name: 'adoption_probe_tool', arguments: '{"command":"adoption-tool-verified"}' } },
      { type: 'response_item', payload: { type: 'function_call_output', call_id: 'adoption-call-1',
        output: 'adoption-tool-result' } },
      { type: 'event_msg', payload: { type: 'token_count', info: {
        last_token_usage: { input_tokens: 4321, cached_input_tokens: 1234, output_tokens: 567 },
        total_token_usage: { input_tokens: 4321, output_tokens: 567 } } } },
    ],
  });
  const rolesFile = path.join(first, '.graphtraj', 'roles.yml');
  const originalRoles = 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n'
    + '      model: original-model\n      api_key_env: GRAPHTRAJ_ADOPTION_SECRET\n      reports: [report.md]\nrole_tree: {}\n';
  await fs.writeFile(rolesFile, originalRoles);

  const consoleMessages = [];
  let appHandle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
  let page = await appHandle.firstWindow();
  page.setDefaultTimeout(30000);
  appHandle.on('console', message => consoleMessages.push(message.text()));

  try {
    // The packaged window navigates to the renderer just after it is created.
    // Wait for the real application markup before the first evaluate, or the
    // evaluate can run against the replaced, destroyed context.
    await page.getByRole('button', { name: 'Add project', exact: true }).waitFor();
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
      await page.getByRole('button', { name: 'Add project', exact: true }).click();
      await page.getByRole('button', { name: 'Add project', exact: true }).waitFor({ state: 'visible' });
    }
    await pick(first);
    await page.getByText('first project', { exact: true }).waitFor();
    await pick(second);
    await page.getByText('second project', { exact: true }).waitFor();
    facts.screenshots.push(await shot(page, '01-two-projects-added.png'));
    step('added two isolated fixture projects and selected the second one');

    await page.locator('.react-flow__node[data-id="2"]').click();
    await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
    await page.getByText('No participating Agents recorded.').waitFor();
    facts.screenshots.push(await shot(page, '02-node-detail-chat-empty.png'));
    step('opened a node without records: the Chat surface rendered its empty state (not adoption evidence)');

    await projectEntry(page, 'first-project').click();
    await page.getByText('first project', { exact: true }).waitFor();
    assert.equal(await page.getByText('second project', { exact: true }).count(), 0);
    facts.screenshots.push(await shot(page, '03-project-switched.png'));
    step('switched the selected project: the graph shows only the selected project');

    // Chat adoption evidence: the controlled records must render as message and
    // tool content through the same public boundary the desktop reads. Expected
    // text comes from that boundary, never from the interface under test.
    const chatBoundary = queryActivity(first, '1', 'research@x1');
    const chatEvents = chatBoundary.events ?? [];
    const message = chatEvents.find(event => event.kind === 'message' && event.role === 'assistant');
    const toolCall = chatEvents.find(event => event.kind === 'tool' && event.phase === 'call');
    assert.ok(message && message.text && toolCall && toolCall.name,
      'the public boundary must return the controlled message and tool call');
    await page.locator('.react-flow__node[data-id="1"]').click();
    await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
    await page.getByRole('button', { name: 'research@x1', exact: true }).click();
    await page.getByText(message.text).first().waitFor();
    await page.getByText(toolCall.name, { exact: true }).first().waitFor();
    await page.getByText(String(toolCall.arguments)).first().waitFor();
    facts.screenshots.push(await shot(page, '03b-node-chat-records.png'));
    step('the controlled records rendered in Chat: the recorded message and tool call are visible');

    await page.getByRole('button', { name: 'Project usage', exact: true }).click();
    await page.locator('section.usage-dashboard').waitFor();
    await page.locator('section.usage-dashboard').getByRole('status').waitFor();
    // The hidden `<option>` in the Model filter carries the same model name, so
    // wait on the visible Model breakdown row instead of the first text match.
    const modelRow = page.getByRole('table', { name: 'Model breakdown', exact: true })
      .getByRole('row').filter({ hasText: 'actual-model' });
    await modelRow.waitFor();
    const usage = (chatEvents.find(event => event.kind === 'usage') ?? {}).usage;
    assert.ok(usage && usage.tokens, 'the public boundary must return the controlled usage record');
    const dashboard = (await page.locator('section.usage-dashboard').innerText()).replaceAll(/[.,\s]/g, '');
    for (const [metric, value] of Object.entries(usage.tokens)) {
      assert.ok(dashboard.includes(String(value)),
        `usage dashboard must show the boundary value ${metric}=${value}`);
    }
    facts.screenshots.push(await shot(page, '04-usage-dashboard.png'));
    facts.controlledRecords = {
      origin: 'Hand-written native rollout records retained in the fixture project; no model invoked, no cost.',
      ticket: '1', alias: 'research@x1',
      chat: { message: message.text, tool: toolCall.name, arguments: toolCall.arguments },
      usage: usage.tokens,
    };
    step(`opened the Usage dashboard: rendered counts match the public boundary (${JSON.stringify(usage.tokens)})`);

    await page.getByRole('button', { name: 'Teams & roles', exact: true }).click();
    await page.getByLabel('Model', { exact: true }).waitFor();
    facts.screenshots.push(await shot(page, '05-settings-form.png'));
    step('opened the Settings form for the selected project');

    // The approval text is produced by the native save entry; capture it to
    // check both the human-review wording and that no credential value appears.
    await appHandle.evaluate(({ dialog }) => {
      globalThis.__gtAdoption = { response: 0, message: '', detail: '' };
      dialog.showMessageBox = async (win, options) => {
        const chosen = options && options.detail !== undefined ? options : win;
        globalThis.__gtAdoption.message = String(chosen?.message ?? '');
        globalThis.__gtAdoption.detail = String(chosen?.detail ?? '');
        return { response: globalThis.__gtAdoption.response, checkboxChecked: false };
      };
    });
    const approval = async () => appHandle.evaluate(() => ({
      message: globalThis.__gtAdoption.message, detail: globalThis.__gtAdoption.detail,
    }));
    const decide = async response => appHandle.evaluate((_electron, value) => {
      globalThis.__gtAdoption.response = value;
    }, response);

    const before = await snapshot(second);
    const firstBefore = await snapshot(first);

    await decide(0);
    await page.getByLabel('Model', { exact: true }).fill('denied-model');
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
    assert.match(await fs.readFile(rolesFile, 'utf8'), /model: original-model/);
    const deniedReview = await approval();
    assert.ok(deniedReview.detail.includes('denied-model'), 'approval text must show the proposed change');
    assert.ok(!deniedReview.detail.includes(secret) && !deniedReview.message.includes(secret),
      'approval text must not contain the credential value');
    step('native save requires approval: a declined change reported the refusal and wrote nothing');

    await decide(1);
    await page.getByLabel('Model', { exact: true }).fill('approved-model');
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
    assert.match(await fs.readFile(rolesFile, 'utf8'), /model: approved-model/);
    facts.screenshots.push(await shot(page, '06-settings-saved.png'));
    step('approved change was written by the native entry into the selected project only');

    // A real native failure: the project's configuration directory is not
    // writable, so an approved save must report the error and keep the file.
    const state = path.join(first, '.graphtraj');
    const saved = await fs.readFile(rolesFile, 'utf8');
    await fs.chmod(state, 0o500);
    try {
      await page.getByLabel('Model', { exact: true }).fill('unwritable-model');
      await page.getByRole('button', { name: 'Save changes', exact: true }).click();
      await page.getByRole('alert').waitFor();
      facts.screenshots.push(await shot(page, '07-settings-save-error.png'));
      assert.equal(await fs.readFile(rolesFile, 'utf8'), saved, 'failed save must not change the file');
      step('an approved save that failed in the native entry reported an error and left the file unchanged');
    } finally { await fs.chmod(state, 0o700); }

    const after = await snapshot(second);
    const firstAfter = await snapshot(first);
    assert.deepEqual(changed(before, after), [], 'saving settings for one project must not write another');
    const firstChanged = changed(firstBefore, firstAfter);
    assert.ok(firstChanged.every(name => name === path.join('.graphtraj', 'roles.yml')),
      `only the selected project's roles file may change, saw ${JSON.stringify(firstChanged)}`);
    const projectsFile = path.join(os.homedir(), 'Library', 'Application Support', 'GraphTraj', 'projects.json');
    const stored = JSON.parse(await fs.readFile(projectsFile, 'utf8'));
    assert.ok(stored.projects.some(project => project.root === first)
      && stored.projects.some(project => project.root === second),
    'desktop preferences must persist in the standard macOS user data directory');
    step(`settings - one project changed (${firstChanged.join(', ')}); the other stayed byte-identical`);

    // Restart the installed app without any user-data override: the standard
    // persistent location must restore the project list.
    await bounded('close installed app before restart', appHandle.close(), 15000);
    appHandle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
    page = await appHandle.firstWindow();
    page.setDefaultTimeout(30000);
    appHandle.on('console', message => consoleMessages.push(message.text()));
    await projectEntry(page, 'first-project').waitFor();
    await projectEntry(page, 'second-project').waitFor();
    facts.screenshots.push(await shot(page, '08-restarted-persisted.png'));
    step('restarting the installed app restored the project list from the standard user data path');

    const rendered = await bounded('read window text', page.evaluate(() => document.body.innerText));
    for (const text of [rendered, ...consoleMessages]) {
      assert.ok(!text.includes(secret), 'the credential value must not appear in the window or its logs');
    }
    facts.consoleMessages = consoleMessages.length;

    // Optionality: the GUI is gone, the native operations are not.
    await bounded('close installed app before optionality check', appHandle.close(), 15000);
    appHandle = null;
    const leftovers = await waitForNoDesktopProcesses();
    assert.equal(leftovers, '', `the desktop must leave no process behind: ${leftovers}`);
    fixtures.operate(second, 'ticket_register', fixtures.ticket('3', 'after-gui-exit', ['2']));
    assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
    step('native operations still worked after the window closed and no desktop process remained');
    facts.optionality = { leftoverProcesses: leftovers, ticketsAfterExit: 3 };

    // Evidence split: what the controlled entry covered, and the real native
    // dialog attempts recorded with their exact commands and outcomes.
    facts.controlledEntry = [
      'folder open panel: Electron dialog.showOpenDialog substituted',
      'approval sheet: Electron dialog.showMessageBox substituted (deny, approve, save error)',
    ];

    // The overall marker reflects the required native operations, not the
    // controlled entry. A diagnostic failure only explains a blocker; a
    // required native failure keeps the result failed and the process red.
    const native = await nativeDialogAttempt(first);
    facts.nativeDialogs = native;
    const required = native.filter(entry => entry.required);
    const failedNative = required.filter(entry => !entry.ok);
    facts.requiredNativeOk = required.length === 3 && failedNative.length === 0;
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
