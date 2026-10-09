import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Build on Windows from a clean commit; no signing, registry changes or global installs.
assert.equal(process.platform, 'win32', 'Windows packaging requires a Windows worker');
assert.equal(process.arch, 'x64', 'This installation artifact targets Windows x64');
const desktop = fileURLToPath(new URL('..', import.meta.url));
const source = path.dirname(desktop);
const output = path.resolve(process.env.GRAPHTRAJ_WIN_OUTPUT || path.join(desktop, 'test-results/package-win'));
const python = process.env.GRAPHTRAJ_BUILD_PYTHON;
assert.ok(python && path.isAbsolute(python), 'Set GRAPHTRAJ_BUILD_PYTHON to the build interpreter');
const run = (exe, args, cwd = source) => execFileSync(exe, args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'] }).trim();
const commit = run('git', ['rev-parse', 'HEAD']);
assert.equal(run('git', ['status', '--porcelain', '--untracked-files=no']), '', 'Commit tracked changes before packaging');
assert.equal(run(python, ['-c', 'import platform; print(platform.python_version())']), '3.13.7');
const manifest = JSON.parse(await fs.readFile(path.join(desktop, 'package.json'), 'utf8'));
assert.equal(manifest.devDependencies.electron, '44.5.1');
// Electron 44 exposes install-electron explicitly; npm ci does not fetch its binary.
run(process.execPath, [path.join(desktop, 'node_modules/electron/install.js')], desktop);
assert.equal((await fs.readFile(path.join(desktop, 'node_modules/electron/dist/version'), 'utf8')).trim().replace(/^v/, ''),
  manifest.devDependencies.electron);
const bundle = path.join(output, 'GraphTraj');
await fs.mkdir(output, { recursive: true });
await fs.mkdir(bundle); // Refuse to merge with a stale package.
await fs.cp(path.join(desktop, 'node_modules/electron/dist'), bundle, { recursive: true });
await fs.rename(path.join(bundle, 'electron.exe'), path.join(bundle, 'GraphTraj.exe'));
await fs.rm(path.join(bundle, 'resources/default_app.asar'), { force: true });
const app = path.join(bundle, 'resources/app');
await fs.mkdir(app, { recursive: true });
for (const name of ['dist', 'dist-electron']) {
  // Keep the output outside the renderer tree when copying assets.
  await fs.cp(path.join(desktop, name), path.join(app, name), {
    recursive: true, filter: filename => filename !== output,
  });
}
await fs.writeFile(path.join(app, 'package.json'), JSON.stringify({
  name: manifest.name, version: manifest.version, main: manifest.main,
}));
for (const name of ['THIRD_PARTY_LICENSES.txt', 'licenses']) {
  await fs.cp(path.join(desktop, name), path.join(bundle, name), { recursive: true });
}
const runtime = path.join(bundle, 'resources/python');
const pythonRoot = run(python, ['-c', 'import sys; print(sys.base_prefix)']);
await fs.cp(pythonRoot, runtime, {
  recursive: true,
  filter: filename => !['site-packages', 'Scripts', '__pycache__'].includes(path.basename(filename)),
});
const wheels = path.join(output, 'wheels');
run(python, ['-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '--wheel-dir', wheels, source]);
const wheel = (await fs.readdir(wheels)).find(name => name.startsWith('graphtraj-') && name.endsWith('.whl'));
assert.ok(wheel);
const dependencies = ['click==8.1.8', 'PyYAML==6.0.2', 'websockets==15.0.1', 'colorama==0.4.6'];
run(python, ['-m', 'pip', 'install', '--no-compile', '--no-deps', '--only-binary=:all:',
  '--target', path.join(runtime, 'Lib/site-packages'), ...dependencies, path.join(wheels, wheel)]);
// pip's generated launchers refer to the build interpreter; the app uses the bundled interpreter directly.
for (const directory of ['bin', 'Scripts']) {
  await fs.rm(path.join(runtime, 'Lib/site-packages', directory), { recursive: true, force: true });
}
// Check the relocated interpreter before archiving; it must import this exact wheel.
const installedPython = path.join(runtime, 'python.exe');
const packages = JSON.parse(run(installedPython, ['-I', '-c',
  'import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))']));
assert.equal(packages.graphtraj, manifest.version);
const hashes = {};
/** Hash every shipped file, including Python distribution licenses and package metadata. */
async function inventory(directory) {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) await inventory(filename);
    else hashes[path.relative(bundle, filename).replaceAll('\\', '/')] = createHash('sha256').update(await fs.readFile(filename)).digest('hex');
  }
}
await inventory(bundle);
await fs.writeFile(path.join(bundle, 'build-manifest.json'), JSON.stringify({
  commit, platform: process.platform, arch: process.arch, node: process.version,
  python: '3.13.7', electron: manifest.devDependencies.electron, packages,
  npmLockSHA256: createHash('sha256').update(await fs.readFile(path.join(desktop, 'package-lock.json'))).digest('hex'),
  hashes,
}, null, 2));
// Copy-only, per-user installation. The shortcut always targets the persistent copy.
await fs.writeFile(path.join(output, 'Install-GraphTraj.ps1'), `param([string]$Destination = "$env:LOCALAPPDATA\\Programs\\GraphTraj")
$ErrorActionPreference = 'Stop'
if (Test-Path $Destination) { throw "Destination already exists: $Destination" }
New-Item -ItemType Directory -Path $Destination | Out-Null
Copy-Item -Path "$PSScriptRoot\\GraphTraj\\*" -Destination $Destination -Recurse
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut("$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\GraphTraj.lnk")
$link.TargetPath = "$Destination\\GraphTraj.exe"
$link.WorkingDirectory = $Destination
$link.Save()
Write-Output $Destination
`);
const archive = path.join(output, 'GraphTraj-windows-x64.zip');
process.env.GRAPHTRAJ_ARCHIVE_BUNDLE = bundle;
process.env.GRAPHTRAJ_ARCHIVE_INSTALLER = path.join(output, 'Install-GraphTraj.ps1');
process.env.GRAPHTRAJ_ARCHIVE_TARGET = archive;
run('powershell.exe', ['-NoProfile', '-Command',
  'Compress-Archive -LiteralPath $env:GRAPHTRAJ_ARCHIVE_BUNDLE,$env:GRAPHTRAJ_ARCHIVE_INSTALLER -DestinationPath $env:GRAPHTRAJ_ARCHIVE_TARGET'], source);

await fs.writeFile(archive + '.sha256', createHash('sha256').update(await fs.readFile(archive)).digest('hex') + '  GraphTraj-windows-x64.zip\n');
console.log(JSON.stringify({ commit, archive, packages }));
