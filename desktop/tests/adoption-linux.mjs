import assert from 'node:assert/strict';
import { execFile, execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { _electron as electron } from 'playwright';
import fixtures from './fixtures.cjs';

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

/** Compare the public Session identity after each GUI lifecycle boundary. */
function runningTask(project) {
  const status = fixtures.operate(project, 'alias_status', { aliases: [process.env.ADOPTION_AGENT_ALIAS] });
  const task = status.aliases[0];
  assert.equal(task.activity, 'running', 'The controlled Runner task must remain active');
  return { session: task.session, execution_id: task.execution_id };
}

/** Capture the X server, including native dialogs outside the renderer. */
async function screenshot(name) {
  await exec('import', ['-window', 'root', path.join(evidence, `${name}.png`)], { timeout: 10000 });
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
    env: { ...process.env, LINUX_ADOPTION_SECRET: 'controlled-secret-never-display-267' },
    timeout: 30000 });
  page = await app.firstWindow();
  page.setDefaultTimeout(15000);
  assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
  assert.equal(await app.evaluate(({ app }) => app.getAppPath()), path.join(installedRoot, 'resources/app'));
  facts.sandbox = await app.evaluate(({ app, BrowserWindow }) => ({
    disabled: app.commandLine.hasSwitch('no-sandbox'),
    renderer: BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences().sandbox,
  }));
  assert.deepEqual(facts.sandbox, { disabled: false, renderer: true });
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

/** Choose a directory with the GTK chooser; never replace Electron dialog APIs. */
async function pick(folder, name) {
  facts.stage = `${name} native directory picker`;
  await page.getByRole('button', { name: 'Add project', exact: true }).click();
  const chooser = await nativeWindow('Add existing GraphTraj project');
  await exec('xdotool', ['key', '--clearmodifiers', 'ctrl+l']);
  await exec('xdotool', ['type', '--clearmodifiers', '--delay', '1', folder]);
  await screenshot(`${name}-native-picker`);
  // The retained GTK screenshot places Open in the lower-right corner. Click
  // that native control rather than depending on location-entry key handling.
  const { stdout } = await exec('xdotool', ['getwindowgeometry', '--shell', chooser]);
  const width = Number(stdout.match(/^WIDTH=(\d+)$/m)[1]);
  const height = Number(stdout.match(/^HEIGHT=(\d+)$/m)[1]);
  facts.pickerInput = { folder, chooser, width, height, action: 'native Open button click' };
  await exec('xdotool', ['mousemove', '--sync', '--window', chooser,
    String(width - 50), String(height - 26), 'click', '1']);
  await page.locator('.project-button.current').filter({ hasText: folder }).waitFor();
  const graph = fixtures.operate(folder, 'ticket_graph');
  await page.getByText(graph.tickets[0].title, { exact: true }).waitFor();
}

/** Exercise the shared writer after a real OS approval or rejection. */
async function save(model, approve, name) {
  facts.stage = `${name} native settings dialog`;
  await page.getByLabel('Model', { exact: true }).fill(model);
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await nativeWindow('Save project settings');
  await screenshot(`${name}-native-approval`);
  await exec('xdotool', ['key', '--clearmodifiers', ...(approve ? ['Tab', 'Return'] : ['Return'])]);
  if (approve) await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  else await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
}

try {
  assert.ok(process.env.ADOPTION_ACTIVITY_PROJECT && process.env.ADOPTION_AGENT_ALIAS && process.env.ADOPTION_TICKET_ID,
    'Launch via tests/linux_adoption_input.py to create controlled records through public Runner');
  facts.source = JSON.parse(await fs.readFile(path.join(installedRoot, 'source.json'), 'utf8'));
  if (process.env.GITHUB_SHA) assert.equal(facts.source.source, process.env.GITHUB_SHA);
  facts.python = execFileSync(path.join(installedRoot, 'python/bin/python'), ['--version'], { encoding: 'utf8' }).trim();
  facts.systemPackages = execFileSync('dpkg-query', ['-W', 'graphtraj-desktop', 'python3', 'python3-venv',
    'xvfb', 'xdotool', 'openbox', 'libgtk-3-0t64'], { encoding: 'utf8' });
  const first = await fs.realpath(process.env.ADOPTION_ACTIVITY_PROJECT);
  const second = await fixtures.makeProject(path.join(root, 'second'), 'linux-second');
  const roles = path.join(second, '.graphtraj/roles.yml');
  // Only disposable project configuration, never private Runner state.
  await fs.writeFile(roles, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      api_key_env: LINUX_ADOPTION_SECRET\n      reports: [report.md]\nrole_tree: {}\n');
  const original = await fs.readFile(roles);
  const firstRoles = await fs.readFile(path.join(first, '.graphtraj/roles.yml'));
  const graphBefore = fixtures.operate(first, 'ticket_graph');
  const runningBefore = runningTask(first);
  facts.controlledExecution = runningBefore;
  assert.ok(graphBefore.tickets.length, 'Activity project needs at least one Ticket');
  await launch();
  await pick(first, 'first');
  await pick(second, 'second');
  await pick(second, 'duplicate');
  assert.equal(await page.locator('.project-button').count(), 2);
  await screenshot('two-projects');
  facts.steps.push('Installed executable, actual directory picker, two project graphs and deduplication');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Model', { exact: true }).waitFor();
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
  await page.getByLabel('Model', { exact: true }).fill('stale-model');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  assert.equal(await fs.readFile(roles, 'utf8'), external);
  await screenshot('settings-conflict');
  await page.getByRole('button', { name: 'Reload and discard draft', exact: true }).click();
  await page.getByRole('status').getByText('Loaded current configuration. Draft discarded.', { exact: true }).waitFor();
  await save('original-model', true, 'restored');
  assert.match(await fs.readFile(roles, 'utf8'), /model: original-model/);
  assert.deepEqual(await fs.readFile(path.join(first, '.graphtraj/roles.yml')), firstRoles);
  assert.ok(!(await page.locator('body').innerText()).includes('controlled-secret-never-display-267'));
  facts.steps.push('Native reject/approve, conflict retention, restoration, preserved fields and cross-project isolation');
  await page.getByRole('button', { name: 'Task graph', exact: true }).click();
  await page.locator('.project-button').filter({ hasText: first }).click();
  await page.locator('.react-flow__node').first().waitFor();
  await closeApp();
  assert.deepEqual(fixtures.operate(first, 'ticket_graph'), graphBefore);
  assert.deepEqual(runningTask(first), runningBefore);
  await launch();
  await page.locator('.project-button.current').filter({ hasText: first }).waitFor();
  assert.equal(await page.locator('.project-button').count(), 2);
  const ticketId = process.env.ADOPTION_TICKET_ID;
  facts.stage = 'controlled Chat';
  await page.locator(`.react-flow__node[data-id="${ticketId}"]`).click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  {
    const activity = await page.evaluate(async ({ ticketId, alias }) => {
      const { selected } = await window.graphtraj.projects();
      return window.graphtraj.activity(selected, { ticket_id: ticketId, alias });
    }, { ticketId, alias: process.env.ADOPTION_AGENT_ALIAS });
    const message = activity.events?.find(event => event.kind === 'message' && event.text === 'GraphTraj GUI controlled message');
    const tool = activity.events?.find(event => event.kind === 'tool' && event.name);
    assert.ok(message && tool, 'Controlled input needs readable message and named tool records in its first page');
    const usage = activity.events.find(event => event.kind === 'usage').usage;
    assert.deepEqual(usage.tokens, { input: 1000, cache_read: 600, output: 80, reasoning: 20 });
    await page.getByRole('button', { name: process.env.ADOPTION_AGENT_ALIAS, exact: true }).click();
    const messageCard = page.locator('.activity-event').filter({ hasText: message.text });
    await messageCard.getByRole('button', { name: 'Copy', exact: true }).click();
    assert.equal(await app.evaluate(({ clipboard }) => clipboard.readText()), message.text);
    const toolCard = page.locator('.activity-event').filter({ hasText: tool.name }).first();
    await toolCard.locator('details summary').click();
    assert.match(await toolCard.locator('pre').innerText(), /echo controlled tool output/);
    const resultCard = page.locator('.activity-event').filter({ hasText: 'controlled tool output' })
      .filter({ has: page.locator('summary', { hasText: 'Result / details' }) });
    await resultCard.locator('summary').click();
    assert.equal(await resultCard.locator('pre').innerText(), 'controlled tool output');
    await resultCard.getByRole('button', { name: 'Copy', exact: true }).click();
    assert.equal(await app.evaluate(({ clipboard }) => clipboard.readText()), 'controlled tool output');
    facts.steps.push('Controlled message and tool command/result rendered; expansion and real clipboard copy verified');
    await screenshot('chat-message-and-tool');
  }
  facts.stage = 'controlled Dashboard';
  await page.getByRole('button', { name: 'Usage', exact: true }).click();
  await page.locator('.usage-dashboard').waitFor();
  const modelRow = page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Model breakdown' }) })
    .locator('tbody tr').filter({ hasText: 'gpt-5.3-codex' });
  await modelRow.waitFor();
  const cells = await modelRow.locator('td').evaluateAll(cells => cells.map(cell => cell.firstChild.textContent));
  const input = await page.evaluate(() => (1000).toLocaleString());
  assert.deepEqual(cells, ['1', input, '80', '600', 'Unknown', '60%', '$0.001925', '0']);
  facts.steps.push('Controlled usage: input1000/cache600/output80/reasoning20; rate60%; equivalent USD0.001925, reasoning counted within output');
  await screenshot('dashboard');
  await modelRow.scrollIntoViewIfNeeded();
  await screenshot('dashboard-model-quantities');
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.forcefullyCrashRenderer());
  assert.deepEqual(fixtures.operate(first, 'ticket_graph'), graphBefore);
  assert.deepEqual(runningTask(first), runningBefore);
  await closeApp();
  fixtures.operate(second, 'ticket_register', fixtures.ticket('3', 'cli-after-gui-failure', ['2']));
  assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
  await launch();
  await page.getByRole('button', { name: `Remove ${second}`, exact: true }).click();
  assert.equal(await page.locator('.project-button').count(), 1);
  assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
  assert.deepEqual(runningTask(first), runningBefore);
  facts.steps.push('Persisted projects, GUI exit/renderer failure preserve the active controlled Runner Session/execution and CLI operation; removal retains project');
  facts.reusedEvidence = 'Accepted A/B/C/D summary supplied via Worldline20261010T042341.450707+0900; integration20261010T030236.725956+0900. This test makes no model calls.';
  facts.uiPassed = true;
} catch (error) {
  facts.failure = String(error);
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
