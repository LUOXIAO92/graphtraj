/** Read only one explicitly supplied native trace; no host/model is started. */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const [nativePackage, trace] = process.argv.slice(2);
const require = createRequire(nativePackage);
const { Session } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-session')));
const [header, ...events] = readFileSync(trace, 'utf8').trim().split('\n').map(JSON.parse);
const session = Session.create(header.id, events, header, header.inheritedEventCount || 0);
console.log(JSON.stringify(session.deriveMessages()));
