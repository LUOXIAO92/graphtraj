/** Load a module of the installed graftling distribution (the range in pyproject.toml). */
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
// Installed from wheels, graftling sits beside graphtraj: <site-packages>/graftling.
const sibling = fileURLToPath(new URL('../../graftling/', import.meta.url));
const LOCATE = 'import graftling, os; print(os.path.dirname(graftling.__file__))';

/** Return the graftling package directory holding ``relative``; name every place looked when absent. */
export function graftlingDirectory(relative = '__init__.py', env = process.env) {
  if (existsSync(join(sibling, relative))) return sibling;
  // Run from a source tree (pytest on src, an editable graphtraj): ask the Python
  // that has graftling installed, GRAFTLING_PYTHON first, then python3 on PATH.
  const tried = [`${sibling} (beside graphtraj)`];
  for (const python of [env.GRAFTLING_PYTHON, 'python3'].filter(Boolean)) {
    try {
      const directory = execFileSync(python, ['-I', '-c', LOCATE], {
        encoding: 'utf8', env, stdio: ['ignore', 'pipe', 'ignore'], timeout: 30000,
      }).trim();
      if (existsSync(join(directory, relative))) return directory;
      tried.push(`${python} -> ${directory}`);
    } catch (error) {
      tried.push(`${python}: ${error.code ?? error.status ?? 'failed'}`);
    }
  }
  throw new Error(`GraphTraj cannot find the installed graftling distribution; looked at ${tried.join('; ')}. ` +
    'Install graftling into the Python that runs GraphTraj, or set GRAFTLING_PYTHON to a Python that has it.');
}

/** Synchronously load graftling/<relative> (an ES module without top-level await). */
export function graftlingModule(relative) {
  return require(join(graftlingDirectory(relative), relative));
}

/** Import graftling/<relative> asynchronously (a module that may use top-level await). */
export function graftlingImport(relative) {
  return import(pathToFileURL(join(graftlingDirectory(relative), relative)).href);
}
