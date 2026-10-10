import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { _electron as electron } from 'playwright';
import { controlledInput, retainedRecords } from './retained-records.mjs';

assert.equal(process.platform, 'win32', 'Adoption requires an actual Windows desktop');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Controlled retained-record construction is restricted to isolated CI');
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
  controlledInput,
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
async function makeProject(name, retained = false) {
  const project = path.join(root, name);
  await fs.mkdir(project);
  const git = args => execFileSync('git', args, { cwd: project, encoding: 'utf8' });
  git(['init', '--initial-branch=main']);
  await fs.writeFile(path.join(project, 'seed.txt'), 'Controlled Windows adoption project; no model execution.\n');
  git(['add', 'seed.txt']);
  git(['-c', 'user.name=Windows adoption', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Controlled project']);
  operate(project, 'project_setup', { source_repository: project, apply: true, create_dev: true });
  await fs.writeFile(path.join(project, '.graphtraj/roles.yml'), 'roles:\n  observation:\n    reader:\n      runtime: codex\n      model: controlled-original\n      api_key_env: WINDOWS_ADOPTION_TEST_KEY\nrole_tree: {}\n');
  let ticketDirectory;
  for (const [id, title, dependencies] of [['1', name, []], ['2', 'dependent', ['1']]]) {
    const registered = operate(project, 'ticket_register', {
      ticket_id: id, ticket_name: title, title, dependencies,
      source: `https://github.com/example/controlled-windows/issues/${id}`,
      body: 'Controlled Windows adoption record. No model execution.',
    });
    if (id === '1') ticketDirectory = registered.ticket_directory;
  }
  if (retained) {
    await retainedRecords(project, ticketDirectory);
    facts.steps.push('Seeded retained controlled records only in the newly created test project; no Agent execution or caller identity was created');
  }
  return project;
}

/** Detect any task/Runner mutation while the installed observer and settings UI operate. */
async function taskFiles(project) {
  const hashes = {};
  async function visit(directory) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(filename);
      else if (entry.isFile()) hashes[path.relative(project, filename)] = createHash('sha256').update(await fs.readFile(filename)).digest('hex');
    }
  }
  await visit(path.join(project, '.graphtraj/state'));
  const runner = path.join(project, '.graphtraj/runner');
  try { await visit(runner); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  return hashes;
}

// Windows UI Automation invokes actual OS controls. It never replaces Electron dialogs.
const nativeScript = path.join(evidence, 'native-ui.ps1');
await fs.writeFile(nativeScript, String.raw`param([int]$AppProcess, [string]$Action, [string]$Folder, [string]$Capture)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Windows.Forms,System.Drawing
if (-not [Environment]::UserInteractive -or (Get-Process -Id $PID).SessionId -eq 0) { throw 'No interactive Windows desktop session' }
# Owned native dialogs need not be immediate children in the UIA control view.
# Enumerate real HWNDs, verify their process/owner, then enter UIA at that HWND.
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class NativeWindows {
  public delegate bool Visitor(IntPtr window, IntPtr parameter);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Visitor visitor, IntPtr parameter);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, Visitor visitor, IntPtr parameter);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr window);
  [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetNextDlgTabItem(IntPtr dialog, IntPtr control, bool previous);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr SetText(IntPtr window, uint message, IntPtr parameter, string text);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr ReadText(IntPtr window, uint message, IntPtr size, StringBuilder text);
  [DllImport("user32.dll", EntryPoint="SendMessageW")] public static extern IntPtr ClickButton(IntPtr window, uint message, IntPtr parameter, IntPtr data);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr window, uint flags);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder text, int count);
}
'@
$deadline = (Get-Date).AddSeconds(20)
$target = $null
$observed = @()
while ((Get-Date) -lt $deadline -and -not $target) {
  $windows = New-Object 'System.Collections.Generic.List[IntPtr]'
  $visitor = [NativeWindows+Visitor]{ param($window, $parameter) $windows.Add($window); return $true }
  [NativeWindows]::EnumWindows($visitor, [IntPtr]::Zero) | Out-Null
  $observed = @()
  foreach ($window in $windows) {
    if (-not [NativeWindows]::IsWindowVisible($window)) { continue }
    [uint32]$windowProcess = 0
    [uint32]$ownerProcess = 0
    [NativeWindows]::GetWindowThreadProcessId($window, [ref]$windowProcess) | Out-Null
    $owner = [NativeWindows]::GetAncestor($window, 3)
    [NativeWindows]::GetWindowThreadProcessId($owner, [ref]$ownerProcess) | Out-Null
    if ($windowProcess -ne $AppProcess -and $ownerProcess -ne $AppProcess) { continue }
    $title = New-Object System.Text.StringBuilder 512
    $class = New-Object System.Text.StringBuilder 256
    [NativeWindows]::GetWindowText($window, $title, $title.Capacity) | Out-Null
    [NativeWindows]::GetClassName($window, $class, $class.Capacity) | Out-Null
    $observed += @{ handle=$window.ToInt64(); process=$windowProcess; ownerProcess=$ownerProcess; title=$title.ToString(); class=$class.ToString() }
    $expected = if ($Action -eq 'pick') { 'Add existing GraphTraj project' } else { 'Save project settings?' }
    if ($title.ToString() -eq $expected -or $class.ToString() -eq '#32770') {
      $dialogHandle = $window
      $target = [System.Windows.Automation.AutomationElement]::FromHandle($window)
      break
    }
  }
  if (-not $target) { Start-Sleep -Milliseconds 100 }
}
$observed | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 ($Capture + '.windows.json')
function Save-DesktopCapture([string]$Destination) {
  $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bitmap = New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bitmap.Size)
  $bitmap.Save($Destination,[System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
}
Save-DesktopCapture $Capture
if (-not $target) { throw "Native dialog unavailable for $Action; see HWND evidence and desktop capture" }
# The real Windows artifact exposes these controls as UIA Panes without patterns.
# Use their actual HWND classes and dialog navigation, not guessed AutomationIds.
$children = New-Object 'System.Collections.Generic.List[IntPtr]'
$childVisitor = [NativeWindows+Visitor]{ param($window, $parameter) $children.Add($window); return $true }
[NativeWindows]::EnumChildWindows($dialogHandle, $childVisitor, [IntPtr]::Zero) | Out-Null
$controls = @()
foreach ($child in $children) {
  $class = New-Object System.Text.StringBuilder 256
  [NativeWindows]::GetClassName($child, $class, $class.Capacity) | Out-Null
  $caption = New-Object System.Text.StringBuilder 1024
  [NativeWindows]::ReadText($child, 0x000D, [IntPtr]$caption.Capacity, $caption) | Out-Null
  $controls += @{ handle=$child.ToInt64(); id=[NativeWindows]::GetDlgCtrlID($child);
    class=$class.ToString(); text=$caption.ToString();
    visible=[NativeWindows]::IsWindowVisible($child); enabled=[NativeWindows]::IsWindowEnabled($child) }
}
$controls | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 ($Capture + '.win32-controls.json')
[NativeWindows]::SetForegroundWindow($dialogHandle) | Out-Null
if ($Action -eq 'pick') {
  $labels = @($controls | Where-Object { $_.visible -and $_.class -eq 'Static' -and $_.text.Replace('&','').Trim() -eq 'Folder:' })
  if ($labels.Count -ne 1) { throw 'Expected one actual native Folder label; see Win32 control evidence' }
  $edit = [NativeWindows]::GetNextDlgTabItem($dialogHandle, [IntPtr]$labels[0].handle, $false)
  $field = @($controls | Where-Object { $_.handle -eq $edit.ToInt64() -and $_.class -eq 'Edit' -and $_.visible -and $_.enabled })
  if ($field.Count -ne 1) { throw 'Folder label does not lead to one native Edit; see Win32 control evidence' }
  if ([NativeWindows]::SetText($edit, 0x000C, [IntPtr]::Zero, $Folder) -eq [IntPtr]::Zero) { throw 'WM_SETTEXT failed for the native Folder edit' }
  $value = New-Object System.Text.StringBuilder 32768
  [NativeWindows]::ReadText($edit, 0x000D, [IntPtr]$value.Capacity, $value) | Out-Null
  if ($value.ToString() -ne $Folder) { throw 'WM_GETTEXT did not return the entered Folder path' }
  @{ handle=$edit.ToInt64(); id=$field[0].id; class=$field[0].class; value=$value.ToString() } |
    ConvertTo-Json | Set-Content -Encoding UTF8 ($Capture + '.selection.json')
  Save-DesktopCapture ($Capture + '.filled.png')
  $names = @('Select Folder')
} elseif ($Action -eq 'approve') { $names = @('Save settings') } else { $names = @('Cancel') }
$buttons = @($controls | Where-Object { $_.class -eq 'Button' -and $_.visible -and $_.enabled -and $names -contains $_.text.Replace('&','').Trim() })
if ($buttons.Count -ne 1) { throw "Expected one actual native button for $Action; see Win32 control evidence" }
$dialogTitle = $target.Current.Name
# BM_CLICK drives the actual button and its parent notification; no dialog result is fabricated.
[NativeWindows]::ClickButton([IntPtr]$buttons[0].handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
@{ action=$Action; dialog=$dialogTitle; session=(Get-Process -Id $PID).SessionId; interactive=[Environment]::UserInteractive } | ConvertTo-Json -Compress
`);
let app;
let page;
let mainProcess;
let dialogNumber = 0;
/** Observe and operate only the installed app's actual native modal dialog. */
async function native(action, folder = '') {
  const capture = path.join(evidence, `native-${++dialogNumber}-${action}.png`);
  const result = await execute('powershell.exe', ['-NoProfile', '-File', nativeScript,
    '-AppProcess', String(mainProcess), '-Action', action, '-Folder', folder, '-Capture', capture], { timeout: 30000 });
  facts.steps.push(JSON.parse(result.stdout));
}
const preferences = path.join(root, 'user-data');
async function launch() {
  const env = { ...process.env, WINDOWS_ADOPTION_TEST_KEY: 'CONTROLLED-SECRET-MUST-NOT-APPEAR' };
  delete env.ELECTRON_RUN_AS_NODE;
  app = await electron.launch({ executablePath: executable, args: [`--user-data-dir=${preferences}`], env });
  page = await app.firstWindow();
  mainProcess = await app.evaluate(() => process.pid);
  facts.processes = { launched: app.process().pid, main: mainProcess };
  await app.evaluate(({ BrowserWindow }) => { const window = BrowserWindow.getAllWindows()[0]; window.show(); window.focus(); });
  page.setDefaultTimeout(20000);
}
async function pick(folder) {
  await page.getByRole('button', { name: 'Add project', exact: true }).click();
  try { await native('pick', folder); } catch (error) {
    await page.screenshot({ path: path.join(evidence, 'picker-failure-renderer.png') });
    facts.pickerAlert = await page.getByRole('alert').allTextContents();
    throw error;
  }
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
  for (const [relative, expected] of Object.entries(manifest.hashes)) {
    const bytes = await fs.readFile(path.join(path.dirname(executable), relative));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected, relative);
  }
  facts.steps.push('Installed files match the exact packaged manifest');
  facts.source = manifest.commit;
  facts.packages = manifest.packages;
  // Never seed supplied user projects: both roots must be newly created by this test.
  const first = await fs.realpath(await makeProject('first-project', true));
  const second = await fs.realpath(await makeProject('second-project'));
  const secondRoles = path.join(second, '.graphtraj/roles.yml');
  const secondBefore = await fs.readFile(secondRoles);
  const firstRoles = path.join(first, '.graphtraj/roles.yml');
  const original = await fs.readFile(firstRoles);
  cli('graphtraj.interfaces.cli.graphtraj', ['--help'], first);
  cli('graphtraj.interfaces.cli.agent_runner', ['--help'], first);
  const before = operate(first, 'ticket_graph');
  const secondGraph = operate(second, 'ticket_graph');
  const firstState = await taskFiles(first);
  const secondState = await taskFiles(second);
  await launch();
  const surface = await page.evaluate(() => ({ methods: Object.keys(window.graphtraj).sort(), require: typeof window.require, process: typeof window.process }));
  assert.deepEqual(surface.methods, ['activity', 'addProject', 'copyText', 'graph', 'projects', 'removeProject', 'saveSettings', 'selectProject', 'settings']);
  assert.equal(surface.require, 'undefined');
  assert.equal(surface.process, 'undefined');
  await pick(first);
  await pick(first);
  assert.equal(await page.locator('.project-button').count(), 1);
  await pick(second);
  assert.equal(await page.locator('.project-button').count(), 2);
  await capture('two-projects');
  await page.locator('.project-button').filter({ hasText: first }).click();
  await page.locator('.react-flow__node[data-id="1"]').click();
  await page.getByRole('complementary', { name: 'Ticket details' }).waitFor();
  const activity = operate(first, 'desktop_activity', { ticket_id: '1' });
  assert.equal(activity.agents.length, 1);
  assert.equal(activity.agents[0].historical, true);
  assert.equal(activity.agents[0].state, 'retired');
  {
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
    await page.locator('.activity-event details summary').filter({ hasText: 'Result / details' }).first().click();
    await page.getByText(facts.controlledInput.tool, { exact: true }).first().waitFor();
    facts.steps.push('Nonempty native Chat message/tool rendered');
  }
  await capture('node-chat');
  await page.getByRole('button', { name: 'Usage', exact: true }).click();
  await page.locator('.usage-dashboard').waitFor();
  {
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
  assert.deepEqual(operate(second, 'ticket_graph'), secondGraph);
  assert.deepEqual(await taskFiles(first), firstState);
  assert.deepEqual(await taskFiles(second), secondState);
  assert.deepEqual(await fs.readFile(secondRoles), secondBefore);
  facts.steps.push('Installed GUI exposes no execution-control methods and leaves both projects task/Runner records unchanged; actual task independence reuses accepted A/B/C/D evidence, not a Windows Runtime claim');
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
