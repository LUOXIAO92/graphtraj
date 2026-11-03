// Print the writable roots the installed DSH sandbox derives from one file policy.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [packageRoot, policy] = process.argv.slice(2);
const { workspaceWritableRoots } = await import(
  pathToFileURL(join(packageRoot, 'node_modules/@deepseek-ai/dsh-sandbox/lib/index.js')).href);
console.log(JSON.stringify(workspaceWritableRoots(JSON.parse(policy))));
