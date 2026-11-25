import { _electron as electron } from 'playwright';
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const loader = path.join(path.dirname(require.resolve('playwright-core/package.json')), 'lib/server/electron/loader.js');
const app = process.argv[2];
const work = process.argv[3];
try {
  const handle = await electron.launch({ executablePath: path.join(app, 'Contents/MacOS/GraphTraj'), args: ['-r', loader, `--user-data-dir=${work}/ud`], env: { ...process.env, HOME: `${work}/home` }, timeout: 60000 });
  const page = await handle.firstWindow();
  await page.getByRole('button', { name: 'Hide sidebar' }).waitFor({ timeout: 30000 });
  console.log('LAUNCHED', await page.title());
  await handle.close();
} catch (error) { console.log('LAUNCH-FAILED', String(error.stack || error).slice(0, 2000)); }
