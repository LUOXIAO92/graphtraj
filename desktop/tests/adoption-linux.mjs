import assert from 'node:assert/strict';
import { execFile, execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';
import { settingsAdoption } from './settings-adoption.mjs';
import { approvalDialogs, datedUsage, guardApprovals, openTask, parallelChat, projectsView,
  removeIndexEntry } from './adoption-shared.mjs';
import { localDate } from '../src/usage.ts';

// This is an installed-product check, not a mocked-dialog window test. It only
// uses disposable projects and explicitly supplied, publishable activity data.
assert.equal(process.platform, 'linux');
const root = path.resolve(process.env.ADOPTION_ROOT || 'test-results/linux-adoption');
const evidence = path.join(root, 'evidence');
const executablePath = process.env.ADOPTION_EXECUTABLE || '/usr/bin/graphtraj-desktop';
const installedRoot = process.env.ADOPTION_INSTALL_ROOT || '/opt/graphtraj-desktop';
process.env.GRAPHTRAJ_TOOL = path.join(installedRoot, 'python/bin/graphtraj-tool');
const exec = promisify(execFile);
const facts = { uiPassed: false, platform: process.platform, release: os.release(),
  executablePath, installedRoot, steps: [], unresolved: [], controlledData: true,
  modelExecution: false };
await fs.mkdir(evidence, { recursive: true });
let app;
let page;
const userData = path.join(root, 'preferences');
const secret = 'controlled-secret-never-display-267';
const consoleMessages = [];

/**
 * Compare the controlled Session after each GUI lifecycle boundary.
 *
 * `subagents status` needs a verified caller (src/graphtraj/interfaces/agents.py run_agents_feature)
 * and this test process is an unbound CI host by design. It therefore reads the
 * human desktop observer's public desktop_activity, as the installed app does:
 * the member's session and native activity. The execution identity is checked by
 * tests/linux_adoption_input.py against the retained completion event.
 */
function runningTask(project) {
  const reply = JSON.parse(execFileSync(process.env.GRAPHTRAJ_TOOL,
    ['--desktop-observer', '--allowed-features', 'desktop_activity'], {
      cwd: project, encoding: 'utf8',
      input: JSON.stringify({ action: 'execute', feature: 'desktop_activity',
        arguments: { task_id: process.env.ADOPTION_TASK_ID } }) + '\n',
    }));
  assert.ok(!reply.failed, JSON.stringify(reply));
  const task = reply.result.agents.find(agent => agent.alias === process.env.ADOPTION_AGENT_ALIAS);
  assert.ok(task, 'The controlled Runner member must be listed for its Task');
  assert.equal(task.state, 'running', 'The controlled Runner task must remain active');
  return { session: task.session, state: task.state };
}

/** Capture the X server, including native dialogs outside the renderer. */
async function screenshot(name) {
  await exec('import', ['-window', 'root', path.join(evidence, name.endsWith('.png') ? name : `${name}.png`)], { timeout: 10000 });
}

/** Wait for an actual native window and send input through X11. */
async function nativeWindow(title) {
  const { stdout } = await exec('xdotool', ['search', '--sync', '--onlyvisible', '--name', title], { timeout: 15000 });
  const id = stdout.trim().split('\n').at(-1);
  await exec('xdotool', ['windowactivate', '--sync', id]);
  return id;
}

/** Start the installed launcher; no development app directory is passed. */
async function launch() {
  facts.stage = 'installed application launch';
  assert.notEqual(process.geteuid(), 0, 'Run desktop checks as the ordinary CI user');
  app = await electron.launch({ executablePath,
    args: [`--user-data-dir=${userData}`, '--ozone-platform=x11'],
    // The controlled Runner peer is not a real model-discovery executable.
    env: { ...process.env, PATH: process.env.PATH.split(path.delimiter).filter(entry => entry !== path.join(root, 'fixture-bin')).join(path.delimiter),
      LINUX_ADOPTION_SECRET: secret },
    timeout: 30000 });
  page = await app.firstWindow();
  page.setDefaultTimeout(15000);
  app.on('console', message => consoleMessages.push(message.text()));
  assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
  assert.equal(await app.evaluate(({ app }) => app.getAppPath()), path.join(installedRoot, 'resources/app'));
  facts.sandbox = await app.evaluate(({ app, BrowserWindow }) => ({
    disabled: app.commandLine.hasSwitch('no-sandbox'),
    renderer: BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences().sandbox,
  }));
  assert.deepEqual(facts.sandbox, { disabled: false, renderer: true });
  const mainPid = await app.evaluate(() => process.pid);
  assert.equal(mainPid, app.process().pid, 'The Linux launcher must exec the installed main process');
  facts.mainPid = mainPid;
  // D saves directly (no approval dialog since 045ef3a4); any message box is a regression.
  await guardApprovals(app);
}

/** Close the test application with a bounded fallback, retaining failed cleanup. */
async function closeApp() {
  const closing = app;
  app = null;
  let timer;
  try {
    await Promise.race([closing.close(), new Promise((_, reject) => {
      timer = setTimeout(() => {
        closing.process().kill('SIGKILL');
        reject(new Error('Installed application did not close within 5 seconds'));
      }, 5000);
    })]);
  } finally { clearTimeout(timer); }
}

const button = name => page.getByRole('button', { name, exact: true }).filter({ visible: true });
const currentProject = () => page.locator('.project-button[aria-current="true"]');
const monitorTitle = title => page.locator('.monitor-page:visible').getByRole('button', { name: title, exact: true });

/** Type a folder into the real GTK chooser and press its Open button. */
async function chooseFolder(title, folder, name, action) {
  const chooser = await nativeWindow(title);
  await exec('xdotool', ['key', '--clearmodifiers', 'ctrl+l']);
  await exec('xdotool', ['type', '--clearmodifiers', '--delay', '1', folder]);
  await screenshot(`${name}-native-picker`);
  // The retained GTK screenshot places Open in the lower-right corner. Click
  // that native control rather than depending on location-entry key handling.
  const { stdout } = await exec('xdotool', ['getwindowgeometry', '--shell', chooser]);
  const width = Number(stdout.match(/^WIDTH=(\d+)$/m)[1]);
  const height = Number(stdout.match(/^HEIGHT=(\d+)$/m)[1]);
  facts[action] = { ...(facts[action] ?? {}), [name]: { folder, chooser, width, height, action: 'native Open button click' } };
  await exec('xdotool', ['mousemove', '--sync', '--window', chooser,
    String(width - 50), String(height - 26), 'click', '1']);
}

/** Choose a directory with the GTK chooser; never replace Electron dialog APIs. */
async function pick(folder, name) {
  facts.stage = `${name} native directory picker`;
  // D: Add project lives in the Projects view (main.tsx ProjectIndexEditor).
  await projectsView(page);
  await button('Add project').click();
  await chooseFolder('Add existing GraphTraj project', folder, name, 'pickerInput');
  await currentProject().filter({ hasText: folder }).waitFor();
  await button('Monitor').click();
  const graph = fixtures.operate(folder, 'task_graph');
  await monitorTitle(graph.tasks[0].title).waitFor();
}

/** After every Save: no approval dialog and no credential in the window or its logs. */
async function checkSave(label) {
  assert.equal(await approvalDialogs(app), 0, `${label}: D saves directly; no approval dialog may appear`);
  const text = await page.locator('body').innerText();
  assert.ok(!text.includes(secret) && !consoleMessages.some(entry => entry.includes(secret)),
    `${label}: the credential value must not appear in the window or its logs`);
}

/**
 * Exercise the shared writer through D's direct Save, or decline with Cancel.
 * D removed the approval dialog (045ef3a4; user decision in
 * docs/specs/optional-desktop-gui-mvp.md): Cancel discards the draft without a write.
 */
async function save(model, approve, name) {
  facts.stage = `${name} direct settings ${approve ? 'Save' : 'Cancel'}`;
  const field = page.getByLabel('Model', { exact: true }).filter({ visible: true });
  const before = await field.inputValue();
  await field.fill(model);
  await page.getByText('1 unsaved changes', { exact: true }).filter({ visible: true }).waitFor();
  if (approve) {
    await button('Save').click();
    await page.getByRole('status').filter({ hasText: 'Settings saved.' }).waitFor();
  } else {
    await button('Cancel').click();
    assert.equal(await field.inputValue(), before, 'Cancel restores the saved value');
  }
  await page.getByText('All changes saved', { exact: true }).filter({ visible: true }).waitFor();
  await checkSave(name);
  await screenshot(`${name}-direct-${approve ? 'save' : 'cancel'}`);
}

/** Read D's project usage for one model against the controlled quantities. */
async function modelQuantities() {
  const dashboard = page.getByRole('region', { name: 'Usage dashboard', exact: true });
  const model = dashboard.getByRole('button', { name: /^gpt-5\.3-codex\b/ });
  await model.waitFor();
  await model.click();
  const totals = Object.fromEntries(await dashboard.locator('.new-usage-totals > span').evaluateAll(cells =>
    cells.map(cell => [cell.querySelector('small').textContent, cell.querySelector('strong').textContent])));
  const titles = await dashboard.getByRole('img', { name: /^Reported input by date/ }).locator('title')
    .evaluateAll(items => items.map(item => item.textContent));
  const footer = await dashboard.locator('.d-usage-history-note').evaluate(element => element.textContent);
  return {
    records: (await model.locator('small').innerText()).match(/^(\d+) reports/)?.[1],
    input: titles.map(title => title.split(': ')[1]).find(Boolean)?.replace(' input tokens', ''),
    inputTotal: totals['INPUT · INCLUDES CACHE'],
    output: totals.OUTPUT,
    cacheRead: totals['CACHE READ'],
    cacheWrite: footer.match(/Cache writes: ([^.]+)\./)?.[1],
    rate: totals['KNOWN INPUT HIT RATE'],
    priced: await model.locator('strong').innerText(),
    unpriced: footer.match(/(\d+) unpriced/)?.[1],
  };
}

try {
  await assert.rejects(fs.access(path.join(os.homedir(), '.graphtraj/projects.json')), { code: 'ENOENT' });
  assert.ok(process.env.ADOPTION_ACTIVITY_PROJECT && process.env.ADOPTION_AGENT_ALIAS && process.env.ADOPTION_TASK_ID,
    'Launch via tests/linux_adoption_input.py to create controlled records through public Runner');
  facts.source = JSON.parse(await fs.readFile(path.join(installedRoot, 'source.json'), 'utf8'));
  if (process.env.GITHUB_SHA) assert.equal(facts.source.source, process.env.GITHUB_SHA);
  facts.python = execFileSync(path.join(installedRoot, 'python/bin/python'), ['--version'], { encoding: 'utf8' }).trim();
  facts.systemPackages = execFileSync('dpkg-query', ['-W', 'graphtraj-desktop', 'python3', 'python3-venv',
    'xvfb', 'xdotool', 'openbox', 'libgtk-3-0t64'], { encoding: 'utf8' });
  const first = await fs.realpath(process.env.ADOPTION_ACTIVITY_PROJECT);
  const second = await fixtures.makeProject(path.join(root, 'second'), 'linux-second');
  // Only the real Relocate chooser can point the disposable entry at this directory.
  const relocateFrom = await fs.realpath(await fixtures.makeProject(path.join(root, 'relocate-from'), 'linux-relocate-from'));
  const relocateTo = await fs.realpath(await fixtures.makeProject(path.join(root, 'relocate-to'), 'linux-relocate-to'));
  await fixtures.recordActivity(second, { taskId: '1', taskName: 'linux-second', alias: 'historical@x1',
    records: [{ type: 'response_item', payload: { type: 'message', role: 'assistant',
      content: [{ type: 'output_text', text: 'Controlled historical message; no model execution.' }] } }],
    additionalMembers: [{ alias: 'current@x2', historical: false, records: [{ type: 'response_item',
      payload: { type: 'message', role: 'assistant', content: [{ type: 'output_text',
        text: 'Controlled current member already completed; no model execution.' }] } }] }],
  });
  const roles = path.join(second, '.graphtraj/roles.yml');
  // Only disposable project configuration, never private Runner state.
  await fs.writeFile(roles, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      api_key_env: LINUX_ADOPTION_SECRET\n      reports: [report.md]\nrole_tree: {}\n');
  const original = await fs.readFile(roles);
  const firstRoles = await fs.readFile(path.join(first, '.graphtraj/roles.yml'));
  const graphBefore = fixtures.operate(first, 'task_graph');
  const runningBefore = runningTask(first);
  facts.controlledExecution = runningBefore;
  assert.ok(graphBefore.tasks.length, 'Activity project needs at least one Task');
  await launch();
  await pick(first, 'first');
  await pick(second, 'second');
  await pick(second, 'duplicate');
  assert.equal(await page.locator('.project-button').count(), 2);
  await screenshot('two-projects');
  facts.steps.push('Installed executable, actual directory picker, two project graphs and deduplication');

  facts.stage = 'native relocate chooser';
  await pick(relocateFrom, 'relocate-source');
  const relocateId = (await page.evaluate(() => window.graphtraj.projects())).projects
    .find(project => project.root === relocateFrom).id;
  await projectsView(page);
  await button(`Relocate ${relocateFrom}`).click();
  await chooseFolder('Relocate GraphTraj project', relocateTo, 'relocate', 'relocateInput');
  await page.getByRole('row').filter({ hasText: relocateTo }).waitFor();
  const relocated = (await page.evaluate(() => window.graphtraj.projects())).projects.find(project => project.id === relocateId);
  assert.equal(relocated.root, relocateTo, 'The real Relocate chooser must change only the indexed path');
  await screenshot('relocated');
  await removeIndexEntry(page, relocateTo);
  await page.locator('.project-button').filter({ hasText: relocateTo }).waitFor({ state: 'detached' });
  assert.equal(fixtures.operate(relocateFrom, 'task_graph').tasks.length, 2);
  assert.equal(fixtures.operate(relocateTo, 'task_graph').tasks.length, 2);
  await page.locator('.project-button').filter({ hasText: second }).click();
  facts.steps.push('Actual Relocate chooser changed only the indexed path; removing that entry kept both directories');

  await openTask(page.locator('.monitor-page:visible'), '1');
  facts.stage = 'parallel Chat through installed desktop bridge';
  const roster = await page.evaluate(async () => {
    const { selected } = await window.graphtraj.projects();
    return window.graphtraj.activity(selected, { task_id: '1' });
  });
  await parallelChat({ page, members: roster.agents, shot: screenshot });
  await button('Teams & roles').click();
  // The legacy role's Model field is in 'Saved project model settings' (Settings.tsx).
  const savedModel = page.locator('summary').filter({ hasText: /^Saved project model settings$/ }).filter({ visible: true });
  if (await savedModel.locator('..').getAttribute('open') === null) await savedModel.click();
  await page.getByLabel('Model', { exact: true }).filter({ visible: true }).waitFor();
  await save('denied-model', false, 'denied');
  assert.deepEqual(await fs.readFile(roles), original);
  await save('saved-model', true, 'approved');
  const saved = await fs.readFile(roles, 'utf8');
  assert.match(saved, /model: saved-model/);
  assert.match(saved, /reports:\s*- report.md/);
  assert.match(saved, /api_key_env: LINUX_ADOPTION_SECRET/);
  await screenshot('settings-saved');
  // A real concurrent config edit must be retained by the native writer.
  const external = saved.replace('saved-model', 'external-model');
  await fs.writeFile(roles, external);
  await page.getByLabel('Model', { exact: true }).filter({ visible: true }).fill('stale-model');
  await button('Save').click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  assert.equal(await fs.readFile(roles, 'utf8'), external);
  await screenshot('settings-conflict');
  await button('Reload').click();
  await page.getByRole('status').filter({ hasText: 'Loaded current configuration.' }).waitFor();
  assert.equal(await page.getByLabel('Model', { exact: true }).filter({ visible: true }).inputValue(), 'external-model',
    'Reload discards the draft and shows the external configuration');
  await save('original-model', true, 'restored');
  assert.match(await fs.readFile(roles, 'utf8'), /model: original-model/);
  assert.deepEqual(await fs.readFile(path.join(first, '.graphtraj/roles.yml')), firstRoles);
  assert.ok(!(await page.locator('body').innerText()).includes(secret));
  facts.steps.push('Direct Cancel/Save (no approval dialog), conflict retention, restoration, preserved fields and cross-project isolation');
  const projects = await page.evaluate(() => window.graphtraj.projects());
  const storedIndex = JSON.parse(await fs.readFile(path.join(os.homedir(), '.graphtraj/projects.json'), 'utf8'));
  assert.deepEqual(storedIndex.projects.map(project => project.root).sort(), [first, second].sort());
  facts.index = { path: path.join(os.homedir(), '.graphtraj/projects.json'), projects: storedIndex.projects };
  const activityId = projects.projects.find(project => project.root === first).id;
  const settingsId = projects.projects.find(project => project.root === second).id;
  let saveNumber = 0;
  const settings = await settingsAdoption({ page, firstId: settingsId, secondId: activityId,
    runtimeHome: path.join(root, 'runtime-home'),
    checkSave: async label => {
      await checkSave(label);
      await screenshot(`configuration-${++saveNumber}-saved`);
    },
    shot: screenshot, step: text => facts.steps.push(text),
  });
  facts.settings = settings;
  await button('Monitor').click();
  await page.locator('.project-button').filter({ hasText: first }).click();
  await monitorTitle(graphBefore.tasks[0].title).waitFor();
  await closeApp();
  assert.deepEqual(fixtures.operate(first, 'task_graph'), graphBefore);
  assert.deepEqual(runningTask(first), runningBefore);
  await launch();
  await currentProject().filter({ hasText: first }).waitFor();
  assert.equal(await page.locator('.project-button').count(), 2);
  const taskId = process.env.ADOPTION_TASK_ID;
  assert.deepEqual(await page.evaluate(id => window.graphtraj.settings(id), settingsId), settings.roles);
  assert.deepEqual((await page.evaluate(id => window.graphtraj.connections(id, { action: 'read' }), activityId)).catalog, settings.global.catalog);
  facts.stage = 'controlled Chat';
  await openTask(page.locator('.monitor-page:visible'), taskId);
  await page.getByRole('complementary', { name: 'Task details' }).waitFor();
  {
    const activity = await page.evaluate(async ({ taskId, alias }) => {
      const { selected } = await window.graphtraj.projects();
      return window.graphtraj.activity(selected, { task_id: taskId, alias });
    }, { taskId, alias: process.env.ADOPTION_AGENT_ALIAS });
    const message = activity.events?.find(event => event.kind === 'message' && event.text === 'GraphTraj GUI controlled message');
    const tool = activity.events?.find(event => event.kind === 'tool' && event.name);
    assert.ok(message && tool, 'Controlled input needs readable message and named tool records in its first page');
    const usage = activity.events.find(event => event.kind === 'usage').usage;
    assert.deepEqual(usage.tokens, { input: 1000, cache_read: 600, output: 80, reasoning: 20 });
    await button('Expand chat').click();
    const reader = page.getByRole('region', { name: 'Expanded agent conversations', exact: true });
    const messageCard = reader.locator('.activity-event').filter({ hasText: message.text });
    // D's copy control is named 'Copy record' (Activity.tsx EventCard).
    await messageCard.getByRole('button', { name: 'Copy record', exact: true }).click();
    assert.equal(await app.evaluate(({ clipboard }) => clipboard.readText()), message.text);
    // D titles tool records 'Tool · <name>'; call and result are separate records (Activity.tsx).
    const toolCard = reader.locator('.activity-event').filter({ hasText: `Tool · ${tool.name}` }).first().locator('details.tool-card');
    await toolCard.locator(':scope > summary').click();
    assert.match(await toolCard.locator('.tool-details').first().innerText(), /echo controlled tool output/);
    const resultCard = reader.locator('.activity-event').filter({ hasText: 'controlled tool output' })
      .filter({ has: page.locator('summary small', { hasText: /^result · / }) }).locator('details.tool-card');
    await resultCard.locator(':scope > summary').click();
    const readable = resultCard.locator('.tool-details > pre, .tool-details > .tool-content').first();
    assert.equal((await readable.innerText()).trim(), 'controlled tool output');
    // Copy lives under the record's Technical details disclosure.
    await resultCard.locator('details.tool-technical > summary').click();
    await resultCard.getByRole('button', { name: 'Copy record', exact: true }).click();
    assert.equal(await app.evaluate(({ clipboard }) => clipboard.readText()), 'controlled tool output');
    facts.steps.push('Controlled message and tool command/result rendered; expansion and real clipboard copy verified');
    await screenshot('chat-message-and-tool');
  }
  facts.stage = 'controlled Dashboard';
  await button('Project usage').click();
  await page.getByRole('region', { name: 'Usage dashboard', exact: true }).waitFor();
  const activity = await page.evaluate(async ({ taskId, alias }) => {
    const { selected } = await window.graphtraj.projects();
    return window.graphtraj.activity(selected, { task_id: taskId, alias });
  }, { taskId, alias: process.env.ADOPTION_AGENT_ALIAS });
  const usageDate = localDate(new Date(activity.events.find(event => event.kind === 'usage').time));
  await page.getByLabel('Start date').fill(usageDate);
  await page.getByLabel('End date').fill(usageDate);
  // D replaced the Model breakdown table with a model list, totals and a dated chart (UsageDashboard.tsx).
  const quantities = await modelQuantities();
  const input = await page.evaluate(() => (1000).toLocaleString());
  assert.deepEqual(quantities, { records: '1', input, inputTotal: '1.0k', output: '80', cacheRead: '600',
    cacheWrite: 'Unknown', rate: '60.0%', priced: '$0.001925', unpriced: '0' });
  facts.steps.push('Controlled usage: input1000/cache600/output80/reasoning20; rate60%; equivalent USD0.001925, reasoning counted within output');
  await screenshot('dashboard');
  await page.getByRole('region', { name: 'Usage dashboard', exact: true }).getByRole('button', { name: /^gpt-5\.3-codex\b/ }).scrollIntoViewIfNeeded();
  await screenshot('dashboard-model-quantities');
  await datedUsage({ page, first, second, agent: process.env.ADOPTION_AGENT_ALIAS, date: usageDate, shot: screenshot });
  // Test application failure at the OS boundary. A crashed renderer leaves the
  // main process alive and makes Playwright's browser-context close ambiguous.
  facts.stage = 'GUI main-process termination';
  const terminated = app.process();
  let exitTimer;
  const exited = new Promise((resolve, reject) => {
    terminated.once('exit', (code, signal) => resolve({ pid: terminated.pid, code, signal }));
    exitTimer = setTimeout(() => {
      terminated.kill('SIGKILL');
      reject(new Error('Terminated GUI main process did not exit within 5 seconds'));
    }, 5000);
  });
  terminated.kill('SIGTERM');
  try { facts.terminatedProcess = await exited; }
  finally { clearTimeout(exitTimer); }
  app = null;
  assert.deepEqual(fixtures.operate(first, 'task_graph'), graphBefore);
  assert.deepEqual(runningTask(first), runningBefore);
  fixtures.operate(second, 'task_register', fixtures.task('3', 'cli-after-gui-failure', ['2']));
  assert.equal(fixtures.operate(second, 'task_graph').tasks.length, 3);
  await launch();
  await currentProject().filter({ hasText: first }).waitFor();
  await datedUsage({ page, first, second, agent: process.env.ADOPTION_AGENT_ALIAS, date: usageDate, shot: name => screenshot(`reopened-${name}`) });
  facts.stage = 'remove project after reopen';
  await removeIndexEntry(page, second);
  await page.locator('.project-button').filter({ hasText: second }).waitFor({ state: 'detached' });
  assert.equal(await page.locator('.project-button').count(), 1);
  assert.equal(fixtures.operate(second, 'task_graph').tasks.length, 3);
  assert.deepEqual(runningTask(first), runningBefore);
  facts.steps.push('Persisted projects, GUI normal exit and main-process termination preserve the active controlled Runner Session/execution and CLI operation; removal retains project');
  facts.reusedEvidence = 'Accepted A/B/C/D summary supplied via Worldline20261010T042341.450707+0900; integration20261010T030236.725956+0900. This test makes no model calls.';
  facts.uiPassed = true;
} catch (error) {
  facts.failure = error.stack || String(error);
  if (page && !page.isClosed()) facts.visibleErrors = await page.getByRole('alert').allTextContents().catch(() => []);
  process.exitCode = 1;
  await screenshot('failure').catch(() => {});
} finally {
  // Retain the observed boundary before cleanup can itself fail or be stopped.
  await fs.writeFile(path.join(evidence, 'ui-result.json'), JSON.stringify(facts, null, 2));
  if (app) await closeApp().catch(error => {
    facts.uiPassed = false;
    facts.cleanupFailure = String(error);
    process.exitCode = 1;
  });
  await fs.writeFile(path.join(evidence, 'ui-result.json'), JSON.stringify(facts, null, 2));
  console.log(JSON.stringify(facts, null, 2));
}
// Native app exits and evidence writes above must finish before protocol handles
// can be abandoned; the standalone test retains its actual result exit status.
process.exit(process.exitCode || 0);
