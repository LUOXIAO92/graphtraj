/**
 * Build the installable macOS artifact from an already-built desktop tree.
 *
 * The produced `.app` is unsigned and has no updater, by design for this MVP.
 * Component license notices are copied into `Contents/Resources` so the
 * distributed binary retains them. The `.app` is wrapped in a zip because a zip
 * preserves the bundle's symlinks and permissions when it is unpacked again.
 *
 * Usage: node scripts/package-mac.mjs [--arch=arm64|x64] [--out=<dir>]
 *
 * Environment:
 *   GRAPHTRAJ_ELECTRON_ZIP_DIR  optional directory of cached Electron zip files
 *   GRAPHTRAJ_ELECTRON_CACHE    optional Electron download cache directory
 *   GRAPHTRAJ_PACKAGE_OUT       optional output directory override
 */
import { packager } from '@electron/packager';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const desktop = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const licenses = ['THIRD_PARTY_LICENSES.txt', 'licenses'];

/** Read a repeatable `--name=value` argument without pulling in an argument parser. */
function option(name) {
  const prefix = `--${name}=`;
  const found = process.argv.find(argument => argument.startsWith(prefix));
  return found === undefined ? undefined : found.slice(prefix.length);
}

const arch = option('arch') || process.env.GRAPHTRAJ_PACKAGE_ARCH || process.arch;
if (!['arm64', 'x64'].includes(arch)) throw new Error(`Unsupported macOS architecture: ${arch}`);
if (process.platform !== 'darwin') throw new Error('The macOS artifact is built on macOS only.');

const out = path.resolve(option('out') || process.env.GRAPHTRAJ_PACKAGE_OUT || path.join(desktop, 'dist-package'));
const appName = 'GraphTraj';
const bundleRoot = path.join(out, `${appName}-darwin-${arch}`);
const appPath = path.join(bundleRoot, `${appName}.app`);
const zipPath = path.join(out, `${appName}-darwin-${arch}.zip`);
const version = JSON.parse(await fsp.readFile(path.join(desktop, 'package.json'), 'utf8')).version;

// The package step consumes the renderer and main-process output, so fail before
// spending time on a download when `npm run build` has not produced them.
for (const built of ['dist/index.html', 'dist-electron/main.js']) {
  await fsp.access(path.join(desktop, built));
}

await fsp.rm(bundleRoot, { recursive: true, force: true });
await fsp.mkdir(out, { recursive: true });
const zipDirectory = process.env.GRAPHTRAJ_ELECTRON_ZIP_DIR;
const cacheRoot = process.env.GRAPHTRAJ_ELECTRON_CACHE;
await packager({
  dir: desktop,
  out,
  name: appName,
  appBundleId: `dev.graphtraj.desktop`,
  appVersion: version,
  platform: 'darwin',
  arch,
  prune: true,
  overwrite: true,
  asar: false,
  quiet: false,
  ...(zipDirectory ? { electronZipDir: path.resolve(zipDirectory) } : {}),
  ...(cacheRoot ? { download: { cacheRoot: path.resolve(cacheRoot) } } : {}),
  // Keep the packaged runtime small and unrelated to the development tree.
  ignore: [
    /^\/dist-package/, /^\/tests/, /^\/src/, /^\/scripts/, /^\/licenses/,
    /^\/THIRD_PARTY_LICENSES\.txt/, /^\/package-lock\.json/, /^\/\.gitignore/,
    /^\/tsconfig.*\.json$/, /^\/vite\.config\.mts$/,
  ],
  extraResource: licenses.map(relative => path.join(desktop, relative)),
});

// The app must carry the license notices it distributes, inside the bundle.
const resources = path.join(appPath, 'Contents', 'Resources');
for (const relative of licenses) {
  const name = path.basename(relative);
  const target = path.join(resources, name);
  if (!fs.existsSync(target)) throw new Error(`Missing packaged license resource: ${target}`);
}

// Zip the bundle itself (not its parent directory) so unpacking restores
// `GraphTraj.app` directly. `-y` stores symlinks as symlinks and preserves
// permissions, which the app bundle's framework links depend on.
await fsp.rm(zipPath, { force: true });
execFileSync('zip', ['-q', '-r', '-y', zipPath, `${appName}.app`], { cwd: bundleRoot });

const bytes = await fsp.readFile(zipPath);
const digest = createHash('sha256').update(bytes).digest('hex');
const clean = { name: appName, version, platform: 'darwin', arch, electron: '44.5.1',
  app: path.relative(desktop, appPath), zip: path.relative(desktop, zipPath),
  bytes: bytes.length, sha256: digest, resources: licenses };
await fsp.writeFile(path.join(out, `${appName}-darwin-${arch}.json`), JSON.stringify(clean, null, 2) + '\n');

console.log(`packaged app: ${appPath}`);
console.log(`artifact: ${zipPath}`);
console.log(`artifact sha256: ${digest}`);
