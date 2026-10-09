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
 *
 * The native tool is resolved from PATH or GRAPHTRAJ_TOOL, the same mechanism
 * the app uses in production. No project, session or credential is uploaded.
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
const secret = process.env.GRAPHTRAJ_ADOPTION_SECRET || `adoption-${randomUUID()}`;
const facts = { app: app ?? null, evidence, steps: [], screenshots: [], passed: false };

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

/**
 * Launch the installed bundle with Playwright's Electron driver.
 *
 * A packaged app cannot be started through the `electron` npm module, so the
 * driver's loader is passed explicitly; everything else is the app's own start.
 */
async function launch(extraEnvironment = {}) {
  const binary = path.join(app, 'Contents', 'MacOS', path.basename(app, '.app'));
  return electron.launch({
    executablePath: binary,
    args: ['-r', electronLoader()],
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

  const root = path.join(evidence, 'fixtures');
  await fs.rm(root, { recursive: true, force: true });
  await fs.mkdir(root);
  const second = await fixtures.makeProject(path.join(root, 'second-project'), 'second-project');
  const first = await fixtures.makeProject(path.join(root, 'first-project'), 'first-project');
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
    const boundary = await page.evaluate(() => ({
      require: typeof window.require, process: typeof window.process, bridge: typeof window.graphtraj,
    }));
    assert.deepEqual(boundary, { require: 'undefined', process: 'undefined', bridge: 'object' });

    // The native folder dialog cannot be driven by the desktop; the same
    // "add an existing directory" entry is exercised with a controlled answer.
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

    await page.locator('.react-flow__node').first().click();
    await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
    await page.getByText('No participating Agents recorded.').waitFor();
    facts.screenshots.push(await shot(page, '02-node-detail-chat.png'));
    step('opened a node: detail pane and its Agent activity (Chat) surface rendered');

    await projectEntry(page, 'first-project').click();
    await page.getByText('first project', { exact: true }).waitFor();
    assert.equal(await page.getByText('second project', { exact: true }).count(), 0);
    facts.screenshots.push(await shot(page, '03-project-switched.png'));
    step('switched the selected project: the graph shows only the selected project');

    await page.getByRole('button', { name: 'Usage', exact: true }).click();
    await page.locator('section.usage-dashboard').waitFor();
    await page.locator('section.usage-dashboard').getByRole('status').waitFor();
    facts.screenshots.push(await shot(page, '04-usage-dashboard.png'));
    step('opened the Usage dashboard for the selected project');

    await page.getByRole('button', { name: 'Settings', exact: true }).click();
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
    await appHandle.close();
    appHandle = await launch({ GRAPHTRAJ_ADOPTION_SECRET: secret });
    page = await appHandle.firstWindow();
    page.setDefaultTimeout(30000);
    appHandle.on('console', message => consoleMessages.push(message.text()));
    await projectEntry(page, 'first-project').waitFor();
    await projectEntry(page, 'second-project').waitFor();
    facts.screenshots.push(await shot(page, '08-restarted-persisted.png'));
    step('restarting the installed app restored the project list from the standard user data path');

    const rendered = await page.evaluate(() => document.body.innerText);
    for (const text of [rendered, ...consoleMessages]) {
      assert.ok(!text.includes(secret), 'the credential value must not appear in the window or its logs');
    }
    facts.consoleMessages = consoleMessages.length;

    // Optionality: the GUI is gone, the native operations are not.
    await appHandle.close();
    appHandle = null;
    const leftovers = desktopProcesses();
    assert.equal(leftovers, '', `the desktop must leave no process behind: ${leftovers}`);
    fixtures.operate(second, 'ticket_register', fixtures.ticket('3', 'after-gui-exit', ['2']));
    assert.equal(fixtures.operate(second, 'ticket_graph').tickets.length, 3);
    step('native operations still worked after the window closed and no desktop process remained');
    facts.optionality = { leftoverProcesses: leftovers, ticketsAfterExit: 3 };
  } finally {
    if (appHandle) await appHandle.close().catch(() => {});
  }
  facts.passed = true;
}

try {
  await main();
} catch (error) {
  facts.failure = String(error && error.stack ? error.stack : error);
  console.error(facts.failure);
  process.exitCode = 1;
} finally {
  await fs.mkdir(evidence, { recursive: true });
  await fs.writeFile(path.join(evidence, 'evidence.json'), JSON.stringify(facts, null, 2) + '\n');
  console.log(`evidence: ${path.join(evidence, 'evidence.json')}`);
}
