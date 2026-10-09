import assert from 'node:assert/strict';
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { _electron as electron } from 'playwright';

assert.equal(process.platform, 'win32', 'Adoption requires an actual Windows desktop');
const evidence = path.resolve(process.env.GRAPHTRAJ_WIN_EVIDENCE || 'test-results/windows');
const executable = process.env.GRAPHTRAJ_WIN_EXE;
assert.ok(executable && path.isAbsolute(executable), 'Set GRAPHTRAJ_WIN_EXE to the installed GraphTraj.exe');
const python = path.join(path.dirname(executable), 'resources/python/python.exe');
const root = path.resolve(process.env.GRAPHTRAJ_WIN_TEST_ROOT || path.join(os.tmpdir(), 'graphtraj-win-adoption'));
await fs.mkdir(evidence, { recursive: true });
await fs.mkdir(root, { recursive: true });
const facts = {
  passed: false, source: process.env.GITHUB_SHA || null,
  platform: process.platform, os: os.release(), arch: process.arch, node: process.version,
  executable, python, steps: [], unresolved: [],
  data: 'Disposable controlled projects; no model calls or private user records.',
  controlledInput: { message: 'GraphTraj GUI controlled message', tool: 'controlled tool output',
    model: 'gpt-5.3-codex', input: 1000, cacheRead: 600, output: 80, reasoning: 20 },
};
const execute = promisify(execFile);
const cli = (entry, args, cwd) => execFileSync(python, ['-I', '-X', 'utf8', '-c', `from ${entry} import main; main()`, ...args], { cwd, encoding: 'utf8' });
/** Exercise public installed operations without editing delivery state. */
function operate(project, feature, args = {}) {
  const reply = JSON.parse(execFileSync(python, ['-I', '-X', 'utf8', '-c', 'from graphtraj.interfaces.local_tool import main; main()', ...(feature === 'desktop_activity' ? ['--desktop-observer'] : [])], {
    cwd: project, encoding: 'utf8', input: JSON.stringify({ action: 'execute', feature, arguments: args }) + '\n',
  }));
  assert.ok(!reply.failed, JSON.stringify(reply));
  return reply.result;
}
/** Set up disposable source/configuration, then register tickets through public operations. */
async function makeProject(name) {
  const project = path.join(root, name);
  await fs.mkdir(project);
  const git = args => execFileSync('git', args, { cwd: project, encoding: 'utf8' });
  git(['init', '--initial-branch=main']);
  await fs.writeFile(path.join(project, 'seed.txt'), 'Controlled Windows adoption project; no model execution.\n');
  git(['add', 'seed.txt']);
  git(['-c', 'user.name=Windows adoption', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Controlled project']);
  operate(project, 'project_setup', { source_repository: project, apply: true, create_dev: true });
  await fs.writeFile(path.join(project, '.graphtraj/roles.yml'), 'roles:\n  observation:\n    reader:\n      runtime: codex\n      model: controlled-original\n      api_key_env: WINDOWS_ADOPTION_TEST_KEY\nrole_tree: {}\n');
  for (const [id, title, dependencies] of [['1', name, []], ['2', 'dependent', ['1']]]) {
    operate(project, 'ticket_register', {
      ticket_id: id, ticket_name: title, title, dependencies,
      source: `https://github.com/example/controlled-windows/issues/${id}`,
      body: 'Controlled Windows adoption record. No model execution.',
    });
  }
  return project;
}

// Windows UI Automation invokes actual OS controls. It never replaces Electron dialogs.
const nativeScript = path.join(evidence, 'native-ui.ps1');
await fs.writeFile(nativeScript, String.raw`param([int]$AppProcess, [string]$Action, [string]$Folder, [string]$Capture)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Windows.Forms,System.Drawing
if (-not [Environment]::UserInteractive -or (Get-Process -Id $PID).SessionId -eq 0) { throw 'No interactive Windows desktop session' }
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$AppProcess)
$deadline = (Get-Date).AddSeconds(20)
$target = $null
while ((Get-Date) -lt $deadline -and -not $target) {
  foreach ($window in $root.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)) {
    $title = $window.Current.Name
    if (($Action -eq 'pick' -and $title -eq 'Add existing GraphTraj project') -or ($Action -ne 'pick' -and $title -eq 'Save project settings?')) { $target = $window; break }
  }
  if (-not $target) { Start-Sleep -Milliseconds 100 }
}
if (-not $target) { throw "Native dialog unavailable for $Action" }
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bitmap.Size)
$bitmap.Save($Capture,[System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose(); $bitmap.Dispose()
if ($Action -eq 'pick') {
  $editCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'1148')
  $edit = $target.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$editCondition)
  if (-not $edit) { throw 'Native folder path control unavailable' }
  $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Folder)
  $names = @('Select Folder','Select folder','Open')
} elseif ($Action -eq 'approve') { $names = @('Save settings') } else { $names = @('Cancel') }
$button = $null
foreach ($name in $names) {
  $byName = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
  $button = $target.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$byName)
  if ($button) { break }
}
if (-not $button) { throw "Native button unavailable for $Action" }
$dialogTitle = $target.Current.Name
$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
@{ action=$Action; dialog=$dialogTitle; session=(Get-Process -Id $PID).SessionId; interactive=[Environment]::UserInteractive } | ConvertTo-Json -Compress
`);
let app;
let page;
let dialogNumber = 0;
/** Observe and operate only the installed app's actual native modal dialog. */
async function native(action, folder = '') {
  const capture = path.join(evidence, `native-${++dialogNumber}-${action}.png`);
  const result = await execute('powershell.exe', ['-NoProfile', '-File', nativeScript,
    '-AppProcess', String(app.process().pid), '-Action', action, '-Folder', folder, '-Capture', capture], { timeout: 30000 });
  facts.steps.push(JSON.parse(result.stdout));
}
const preferences = path.join(root, 'user-data');
async function launch() {
  const env = { ...process.env, WINDOWS_ADOPTION_TEST_KEY: 'CONTROLLED-SECRET-MUST-NOT-APPEAR' };
  delete env.GRAPHTRAJ_TOOL;
  delete env.ELECTRON_RUN_AS_NODE;
  app = await electron.launch({ executablePath: executable, args: [`--user-data-dir=${preferences}`], env });
  page = await app.firstWindow();
  page.setDefaultTimeout(20000);
}
async function pick(folder) {
  await page.getByRole('button', { name: 'Add project', exact: true }).click();
  await native('pick', folder);
  await page.locator('.project-button.current').filter({ hasText: folder }).waitFor();
  await page.getByText('Connected', { exact: false }).waitFor();
}
async function capture(name) {
  assert.ok(!(await page.locator('body').innerText()).includes('CONTROLLED-SECRET-MUST-NOT-APPEAR'));
  await page.screenshot({ path: path.join(evidence, name + '.png') });
}
try {
  const manifest = JSON.parse(await fs.readFile(path.join(path.dirname(executable), 'build-manifest.json'), 'utf8'));
  assert.equal(manifest.commit, facts.source || manifest.commit);
  facts.source = manifest.commit;
  facts.packages = manifest.packages;
  // Optional supplied roots must be disposable and credential-free, prepared through native operations.
  const first = await fs.realpath(process.env.GRAPHTRAJ_WIN_PROJECT_A || await makeProject('first-project'));
  const second = await fs.realpath(process.env.GRAPHTRAJ_WIN_PROJECT_B || await makeProject('second-project'));
  const secondRoles = path.join(second, '.graphtraj/roles.yml');
  const secondBefore = await fs.readFile(secondRoles);
  const firstRoles = path.join(first, '.graphtraj/roles.yml');
  const original = await fs.readFile(firstRoles);
  cli('graphtraj.interfaces.cli.graphtraj', ['--help'], first);
  cli('graphtraj.interfaces.cli.agent_runner', ['--help'], first);
  const before = operate(first, 'ticket_graph');
  const liveAlias = process.env.GRAPHTRAJ_WIN_LIVE_ALIAS;
  const liveBefore = liveAlias ? operate(first, 'alias_status', { aliases: [liveAlias] }).agents.find(agent => agent.alias === liveAlias) : null;
  if (liveAlias) assert.equal(liveBefore?.activity, 'running', 'The supplied controlled execution must actually be running');
  const checkLive = () => {
    if (!liveAlias) return;
    const current = operate(first, 'alias_status', { aliases: [liveAlias] }).agents.find(agent => agent.alias === liveAlias);
    assert.equal(current?.execution_id, liveBefore.execution_id);
    assert.equal(current?.session, liveBefore.session);
    assert.equal(current?.activity, 'running');
  };
  await launch();
  await pick(first);
  await pick(first);
  assert.equal(await page.locator('.project-button').count(), 1);
  await pick(second);
  assert.equal(await page.locator('.project-button').count(), 2);
  await capture('two-projects');
  await page.locator('.project-button').filter({ hasText: first }).click();
  await page.locator('.react-flow__node').filter({ hasText: '#1' }).click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  const activity = operate(first, 'desktop_activity', { ticket_id: '1' });
  if (activity.agents.length) {
    await page.getByRole('button', { name: activity.agents[0].alias, exact: true }).click();
    await page.locator('.activity-event').first().waitFor();
    const observed = operate(first, 'desktop_activity', { ticket_id: '1', alias: activity.agents[0].alias });
    const message = observed.events?.find(event => event.kind === 'message' && event.text);
    const tool = observed.events?.find(event => event.kind === 'tool' && event.name);
    assert.ok(message, 'Nonempty Chat messages required');
    assert.ok(tool, 'Nonempty Chat tools required');
    assert.equal(message.text, facts.controlledInput.message);
    assert.ok(observed.events.some(event => event.kind === 'tool' && event.result === facts.controlledInput.tool));
    const usage = observed.events.find(event => event.kind === 'usage')?.usage;
    assert.ok(usage, 'Controlled Runtime usage required');
    assert.equal(usage.tokens.input, 1000);
    assert.equal(usage.tokens.cache_read, 600);
    assert.equal(usage.tokens.output, 80); // Reasoning 20 is already a subset of output 80.
    await page.locator('.activity-event').filter({ hasText: message.text }).first().waitFor();
    await page.locator('.activity-event').filter({ hasText: tool.name }).first().waitFor();
    await page.locator('.activity-event details summary').first().click();
    facts.steps.push('Nonempty native Chat message/tool rendered');
  } else facts.unresolved.push('Controlled Chat/usage fixture requires public Runner registration; Windows lacks the POSIX authenticated control transport used by the supplied fixtures. No private-state fixture was fabricated.');
  await capture('node-chat');
  await page.getByRole('button', { name: 'Usage', exact: true }).click();
  await page.locator('.usage-dashboard').waitFor();
  if (activity.agents.length) {
    const row = page.getByRole('table', { name: 'Model breakdown', exact: true }).getByRole('row').filter({ hasText: 'gpt-5.3-codex' });
    await row.waitFor();
    const cells = row.locator('td');
    assert.match(await cells.nth(1).innerText(), /^1,?000/);
    assert.match(await cells.nth(2).innerText(), /^80/);
    assert.match(await cells.nth(3).innerText(), /^600/);
    assert.equal(await cells.nth(5).innerText(), '60%');
    assert.match(await cells.nth(6).innerText(), /^\$0\.001925/);
    facts.steps.push('Controlled 1000 input / 600 cache / 80 output gives 60% cache and $0.001925 at the bundled C snapshot; reasoning is not added twice');
  }
  await capture('dashboard');
  facts.steps.push('Installed Dashboard renders; quantity algorithms reuse accepted C evidence');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Model', { exact: true }).fill('controlled-denied');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await native('deny');
  await page.getByRole('alert').filter({ hasText: 'did not approve' }).waitFor();
  assert.deepEqual(await fs.readFile(firstRoles), original);
  await capture('settings-denied');
  await page.getByLabel('Model', { exact: true }).fill('controlled-approved');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await native('approve');
  await page.getByRole('status').getByText('Settings saved.', { exact: true }).waitFor();
  assert.match(await fs.readFile(firstRoles, 'utf8'), /model: controlled-approved/);
  assert.deepEqual(await fs.readFile(secondRoles), secondBefore);
  await capture('settings-approved');
  // An external edit is an ordinary config edit, not a private-state mutation.
  await fs.appendFile(firstRoles, '\n# Controlled concurrent edit\n');
  const concurrent = await fs.readFile(firstRoles);
  await page.getByLabel('Model', { exact: true }).fill('controlled-stale');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'changed while editing' }).waitFor();
  assert.deepEqual(await fs.readFile(firstRoles), concurrent);
  assert.deepEqual(await fs.readFile(secondRoles), secondBefore);
  await capture('settings-conflict');
  await app.close(); app = null;
  assert.deepEqual(operate(first, 'ticket_graph'), before);
  checkLive();
  await launch();
  await page.locator('.project-button.current').filter({ hasText: first }).waitFor();
  await page.getByRole('button', { name: `Remove ${second}`, exact: true }).click();
  assert.equal(await page.locator('.project-button').count(), 1);
  assert.equal(operate(second, 'ticket_graph').tickets.length, 2);
  await capture('restart-removal');
  const crashed = app.process();
  const exited = new Promise(resolve => crashed.once('exit', resolve));
  crashed.kill();
  await exited;
  app = null;
  cli('graphtraj.interfaces.cli.agent_runner', ['--help'], first);
  assert.deepEqual(operate(first, 'ticket_graph'), before);
  facts.steps.push('CLI and native graph survive GUI normal exit and process termination; removed project retained');
  checkLive();
  if (liveAlias) facts.steps.push('Supplied live execution retains its Session, execution ID and running status through GUI exit/failure');
  else facts.unresolved.push('Running Main/Runner isolation needs an authorized live Windows execution; CLI/graph survival alone does not establish it.');
  facts.passed = facts.unresolved.length === 0;
} catch (error) {
  facts.error = String(error);
} finally {
  if (app) await app.close().catch(() => {});
  await fs.writeFile(path.join(evidence, 'adoption.json'), JSON.stringify(facts, null, 2));
}
if (!facts.passed) {
  console.error(JSON.stringify({ passed: false, error: facts.error, unresolved: facts.unresolved }));
  process.exitCode = 1;
}
