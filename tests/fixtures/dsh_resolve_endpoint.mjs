// Print the Messages root the installed DSH resolves for one llm-deepseek row in this environment.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [packageRoot, config] = process.argv.slice(2);
const load = (name) => import(pathToFileURL(join(packageRoot, 'node_modules/@deepseek-ai', name, 'lib/index.js')).href);
const { resolveAdapterOptions } = await load('dsh-llm-deepseek');
const { createLaunchEnvironmentSnapshot } = await load('dsh-launch-environment');
const snapshot = createLaunchEnvironmentSnapshot([{ source: 'process', values: process.env }]);
console.log(resolveAdapterOptions(JSON.parse(config), snapshot).baseURL);
