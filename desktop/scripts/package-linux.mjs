import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Build on the target OS. Python comes from the declared distribution packages;
// the matching GraphTraj wheel and its exact dependencies install offline.
assert.equal(process.platform, 'linux', 'Build this package on Linux');
assert.equal(process.arch, 'x64', 'This package targets Linux amd64');
const desktop = fileURLToPath(new URL('..', import.meta.url));
const source = path.dirname(desktop);
const output = path.resolve(process.argv[2] || path.join(desktop, 'test-results/linux-package'));
const stage = path.join(output, 'stage');
const install = path.join(stage, 'opt/graphtraj-desktop');
const app = path.join(install, 'resources/app');
const python = process.env.PYTHON || '/usr/bin/python3';
const pins = ['click==8.1.8', 'PyYAML==6.0.2', 'websockets==15.0.1'];
const run = (command, args, cwd = desktop) => execFileSync(command, args, { cwd, stdio: 'inherit' });
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: source, encoding: 'utf8' }).trim();
assert.equal(execFileSync('git', ['status', '--porcelain', '--untracked-files=no'],
  { cwd: source, encoding: 'utf8' }).trim(), '', 'Package a committed source tree');
await fs.mkdir(output, { recursive: true });
// Exclusive staging avoids deleting an existing artifact or another build.
await fs.mkdir(stage);
run('npm', ['run', 'build']);
await fs.cp(path.join(desktop, 'node_modules/electron/dist'), install, { recursive: true });
await fs.rename(path.join(install, 'electron'), path.join(install, 'graphtraj-desktop-bin'));
await fs.mkdir(app, { recursive: true });
for (const name of ['dist', 'dist-electron', 'package.json', 'package-lock.json', 'THIRD_PARTY_LICENSES.txt']) {
  await fs.cp(path.join(desktop, name), path.join(app, name), { recursive: true });
}
await fs.mkdir(path.join(install, 'wheels'));
const buildPython = path.join(output, 'build-python/bin/python');
run(python, ['-m', 'venv', path.join(output, 'build-python')]);
run(buildPython, ['-m', 'pip', 'install', 'setuptools==75.8.0', 'wheel==0.45.1']);
run(buildPython, ['-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
  '--wheel-dir', path.join(install, 'wheels'), source]);
run(buildPython, ['-m', 'pip', 'download', '--only-binary=:all:', '--no-deps',
  '--dest', path.join(install, 'wheels'), ...pins]);
await fs.writeFile(path.join(install, 'python-requirements.txt'), pins.join('\n') + '\n');
await fs.writeFile(path.join(install, 'source.json'), JSON.stringify({ source: sha,
  platform: 'linux-x64', node: process.version, electron: '44.5.1', pythonDependencies: pins }, null, 2));
// Retain the target Electron binary's original LICENSE and LICENSES.chromium.html
// plus frontend notices and wheel dist-info licenses. Never reuse macOS notices
// as the Linux binary's only license record.
await fs.access(path.join(install, 'LICENSE'));
await fs.access(path.join(install, 'LICENSES.chromium.html'));

await fs.mkdir(path.join(stage, 'usr/bin'), { recursive: true });
await fs.writeFile(path.join(stage, 'usr/bin/graphtraj-desktop'), `#!/bin/sh
export GRAPHTRAJ_TOOL=/opt/graphtraj-desktop/python/bin/graphtraj-tool
exec /opt/graphtraj-desktop/graphtraj-desktop-bin "$@"
`, { mode: 0o755 });
await fs.mkdir(path.join(stage, 'usr/share/applications'), { recursive: true });
await fs.writeFile(path.join(stage, 'usr/share/applications/graphtraj-desktop.desktop'), `[Desktop Entry]
Type=Application
Name=GraphTraj
Comment=Optional project monitor and settings
Exec=/usr/bin/graphtraj-desktop
Terminal=false
Categories=Development;
`);
await fs.mkdir(path.join(stage, 'DEBIAN'));
await fs.writeFile(path.join(stage, 'DEBIAN/control'), `Package: graphtraj-desktop
Version: 0.1.0
Architecture: amd64
Maintainer: GraphTraj contributors
Depends: python3 (>= 3.12), python3-venv, libgtk-3-0t64, libnss3, libasound2t64, libgbm1, libxss1, libxtst6, libatk-bridge2.0-0t64
Description: Optional GraphTraj desktop project monitor and settings
`);
await fs.writeFile(path.join(stage, 'DEBIAN/postinst'), `#!/bin/sh
set -eu
if [ "$1" = configure ]; then
  python3 -m venv /opt/graphtraj-desktop/python
  /opt/graphtraj-desktop/python/bin/python -m pip install --no-index --no-deps /opt/graphtraj-desktop/wheels/*.whl
  /opt/graphtraj-desktop/python/bin/python -m pip check
  chown root:root /opt/graphtraj-desktop/chrome-sandbox
  chmod 4755 /opt/graphtraj-desktop/chrome-sandbox
fi
`, { mode: 0o755 });
await fs.writeFile(path.join(stage, 'DEBIAN/postrm'), `#!/bin/sh
set -eu
if [ "$1" = remove ] || [ "$1" = purge ]; then
  rm -rf /opt/graphtraj-desktop/python
fi
`, { mode: 0o755 });
const artifact = path.join(output, 'graphtraj-desktop_0.1.0_amd64.deb');
run('dpkg-deb', ['--root-owner-group', '--build', stage, artifact]);
const digest = createHash('sha256').update(await fs.readFile(artifact)).digest('hex');
await fs.writeFile(path.join(output, 'SHA256SUMS'), `${digest}  ${path.basename(artifact)}\n`);
await fs.copyFile(path.join(install, 'source.json'), path.join(output, 'source.json'));
console.log(JSON.stringify({ artifact, sha256: digest, source: sha }));
