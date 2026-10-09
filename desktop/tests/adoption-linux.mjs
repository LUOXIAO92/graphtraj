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
const facts = { passed: false, platform: process.platform, release: os.release(),
  executablePath, installedRoot, steps: [], unresolved: [], controlledData: true,
  modelExecution: false };
await fs.mkdir(evidence, { recursive: true });
let app;
let page;
const userData = path.join(root, 'preferences');

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
  app = await electron.launch({ executablePath,
    args: [`--user-data-dir=${userData}`, '--ozone-platform=x11'],
    env: { ...process.env, LINUX_ADOPTION_SECRET: 'controlled-secret-never-display-267' },
    timeout: 30000 });
  page = await app.firstWindow();
  page.setDefaultTimeout(15000);
  assert.equal(await app.evaluate(({ app }) => app.isPackaged), true);
  assert.equal(await app.evaluate(({ app }) => app.getAppPath()), path.join(installedRoot, 'resources/app'));
}

/** Choose a directory with the GTK chooser; never replace Electron dialog APIs. */
async function pick(folder, name) {
  await page.getByRole('button', { name: 'Add project', exact: true }).click();
  await nativeWindow('Add existing GraphTraj project');
  await exec('xdotool', ['key', '--clearmodifiers', 'ctrl+l']);
  await exec('xdotool', ['type', '--clearmodifiers', '--delay', '1', folder + '/']);
  await screenshot(`${name}-native-picker`);
  await exec('xdotool', ['key', '--clearmodifiers', 'Return']);
  // GTK resolves the entered folder before its Open action can be selected.
  await new Promise(resolve => setTimeout(resolve, 500));
  await exec('xdotool', ['key', '--clearmodifiers', 'alt+o']);
  await page.locator('.project-button.current').filter({ hasText: folder }).waitFor();
  const graph = fixtures.operate(folder, 'ticket_graph');
  await page.getByText(graph.tickets[0].title, { exact: true }).waitFor();
}

/** Exercise the shared writer after a real OS approval or rejection. */
async function save(model, approve, name) {
  await page.getByLabel('Model', { exact: true }).fill(model);
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await nativeWindow('Save project settings');
  await screenshot(`${name}-native-approval`);
  await exec('xdotool', ['key', '--clearmodifiers', ...(approve ? ['Tab', 'Return'] : ['Return'])]);
  if (approve) await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  else await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
}

try {
  facts.source = JSON.parse(await fs.readFile(path.join(installedRoot, 'source.json'), 'utf8'));
  if (process.env.GITHUB_SHA) assert.equal(facts.source.source, process.env.GITHUB_SHA);
  facts.python = execFileSync(path.join(installedRoot, 'python/bin/python'), ['--version'], { encoding: 'utf8' }).trim();
  facts.systemPackages = execFileSync('dpkg-query', ['-W', 'graphtraj-desktop', 'python3', 'python3-venv',
    'xvfb', 'xdotool', 'openbox', 'libgtk-3-0t64'], { encoding: 'utf8' });
  const first = process.env.ADOPTION_ACTIVITY_PROJECT
    ? await fs.realpath(process.env.ADOPTION_ACTIVITY_PROJECT)
    : await fixtures.makeProject(path.join(root, 'first'), 'linux-first');
  const second = await fixtures.makeProject(path.join(root, 'second'), 'linux-second');
  const roles = path.join(second, '.graphtraj/roles.yml');
  // Only disposable project configuration, never private Runner state.
  await fs.writeFile(roles, 'roles:\n  custom_group:\n    observer:\n      runtime: codex\n      model: original-model\n      api_key_env: LINUX_ADOPTION_SECRET\n      reports: [report.md]\nrole_tree: {}\n');
  const original = await fs.readFile(roles);
  const firstRoles = await fs.readFile(path.join(first, '.graphtraj/roles.yml'));
  const graphBefore = fixtures.operate(first, 'ticket_graph');
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
  await app.close();
  app = null;
  assert.deepEqual(fixtures.operate(first, 'ticket_graph'), graphBefore);
  await launch();
  await page.locator('.project-button.current').filter({ hasText: first }).waitFor();
  assert.equal(await page.locator('.project-button').count(), 2);
  const ticketId = process.env.ADOPTION_TICKET_ID || graphBefore.tickets[0].ticket_id;
  await page.locator('.react-flow__node').filter({ hasText: `#${ticketId}` }).first().click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  if (process.env.ADOPTION_ACTIVITY_PROJECT) {
    assert.ok(process.env.ADOPTION_AGENT_ALIAS, 'Specify the controlled activity Agent');
    const activity = await page.evaluate(async ({ ticketId, alias }) => {
      const { selected } = await window.graphtraj.projects();
      return window.graphtraj.activity(selected, { ticket_id: ticketId, alias });
    }, { ticketId, alias: process.env.ADOPTION_AGENT_ALIAS });
    const message = activity.events?.find(event => event.kind === 'message' && event.text);
    const tool = activity.events?.find(event => event.kind === 'tool' && event.name);
    assert.ok(message && tool, 'Controlled input needs readable message and named tool records in its first page');
    await page.getByRole('button', { name: process.env.ADOPTION_AGENT_ALIAS, exact: true }).click();
    await page.locator('.activity-event').filter({ hasText: message.text }).first().waitFor();
    const toolCard = page.locator('.activity-event').filter({ hasText: tool.name }).first();
    await toolCard.locator('details summary').click();
    facts.steps.push('Installed observer projects a retained message and tool into readable Chat');
    await screenshot('chat-message-and-tool');
  } else facts.unresolved.push('Nonempty Chat: requires publishable controlled activity project prepared through public Runner operations');
  await page.getByRole('button', { name: 'Usage', exact: true }).click();
  await page.locator('.usage-dashboard').waitFor();
  if (process.env.ADOPTION_ACTIVITY_PROJECT) {
    await page.getByRole('table').filter({ has: page.locator('caption', { hasText: 'Model breakdown' }) })
      .locator('tbody tr').first().waitFor();
  } else facts.unresolved.push('Nonempty Dashboard: requires attributable retained usage in controlled activity project');
  await screenshot('dashboard');
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.forcefullyCrashRenderer());
  assert.deepEqual(fixtures.operate(first, 'ticket_graph'), graphBefore);
  await app.close();
  app = null;
  fixtures.operate(second, 'ticket_register', fixtures.ticket('3', 'cli-after-gui-failure', ['2']));
  assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
  await launch();
  await page.getByRole('button', { name: `Remove ${second}`, exact: true }).click();
  assert.equal(await page.locator('.project-button').count(), 1);
  assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
  facts.steps.push('Persisted projects, GUI exit/renderer failure leave native queries and CLI mutation operational, removal retains project');
  facts.reusedEvidenceRequired = 'Leader attaches accepted prior real Main/Runner execution and usage algorithm evidence; this run makes no model calls';
  // Prior evidence is a separate acceptance responsibility; never report overall
  // success for missing Linux boundaries or absent controlled activity input.
  assert.ok(process.env.ADOPTION_ACTIVITY_PROJECT, facts.unresolved.join('; '));
  facts.passed = true;
} catch (error) {
  facts.failure = String(error);
  process.exitCode = 1;
  await screenshot('failure').catch(() => {});
} finally {
  if (app) await app.close().catch(() => { app.process().kill('SIGKILL'); });
  await fs.writeFile(path.join(evidence, 'result.json'), JSON.stringify(facts, null, 2));
  console.log(JSON.stringify(facts, null, 2));
}
