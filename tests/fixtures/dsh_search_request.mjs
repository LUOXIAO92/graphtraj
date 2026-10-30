// Print where the installed web-search-deepseek sends one search for a row, and whether the row's key goes with it.
// fetch is replaced, so nothing leaves this process.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [packageRoot, config] = process.argv.slice(2);
const load = (name) => import(pathToFileURL(join(packageRoot, 'node_modules/@deepseek-ai', name, 'lib/index.js')).href);
const { Config, apply } = await load('dsh-web-search-deepseek');
let provider;
apply({ get: () => undefined, web: { registerSearchProvider: (registered) => { provider = registered; } } },
    Config(JSON.parse(config)));
let sent;
globalThis.fetch = async (url, init) => {
    sent = { url: String(url), keyed: Object.values(init.headers).includes(process.env.DEEPSEEK_API_KEY) };
    return new Response('{}', { status: 500 });
};
await provider.search({ query: 'where does this go' }).catch(() => {});
console.log(JSON.stringify(sent));
