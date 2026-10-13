import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

/** Ship GUI code provenance inside the matching backend, not in a caller request. */
export async function desktopHostManifest(executable, app, source) {
  const files = {};
  const add = async file => { files[path.relative(path.dirname(executable), file).replaceAll('\\', '/')] =
    createHash('sha256').update(await fs.readFile(file)).digest('hex'); };
  const walk = async directory => {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(file);
      else await add(file);
    }
  };
  await add(executable);
  await add(path.join(app, 'package.json'));
  await walk(path.join(app, 'dist-electron'));
  await walk(path.join(app, 'dist'));
  await fs.writeFile(path.join(source, 'src/graphtraj/interfaces/desktop-host.json'),
    JSON.stringify({ executable: path.basename(executable), files }, null, 2));
}
