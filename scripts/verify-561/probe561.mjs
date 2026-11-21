/**
 * Task 561 local stand-in (no network listener): the installed DSH's own packages load graftling's real plugin.mjs
 * as a cordis plugin (as DSH's profile row `agents` does) and the Gateway invokes `agentMessages.receive` the way the
 * web server's /api route does (invokePrepared). Only the HTTP listener and the agent loop are left out: `agents` is
 * a minimal stand-in returning one agent with an inbox.
 *   node probe561.mjs <label> <installed dsh bin.js (realpath)> <graftling plugin.mjs>
 */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [label, nativeEntry, pluginPath] = process.argv.slice(2);
process.env.GRAFTLING_DSH_PACKAGE = nativeEntry;
const require = createRequire(nativeEntry);
const load = name => import(pathToFileURL(require.resolve(name)));
const { version } = require('@deepseek-ai/cordis/package.json');
console.log(`[${label}] cordis ${version} | plugin ${pluginPath}`);
const { Context } = await load('@deepseek-ai/cordis');
const { SessionStore } = await load('@deepseek-ai/dsh-session');
const { SessionQueryEngine } = await load('@deepseek-ai/dsh-session-query');
const { TypertRegistry } = await load('@deepseek-ai/dsh-typert-registry');
const { TypertGatewayService } = await load('@deepseek-ai/dsh-api-gateway');
const { RemoteAccessService } = await load('@deepseek-ai/dsh-api-remote-access');
const ctx = new Context();
await ctx.plugin(SessionStore).await();
await ctx.plugin(SessionQueryEngine).await();
await ctx.plugin(TypertRegistry).await();
ctx.plugin(RemoteAccessService);
await ctx.plugin(TypertGatewayService, {}).await();
const session = ctx.sessions.create('receiver', { meta: { cwd: process.cwd() } });
const inbox = { nextTurn: [], nextStep: [] };
const agent = { inbox, send(message) { inbox.nextStep.push(message); } };
ctx.provide('agents', { get: id => id === session.id ? agent : undefined });
ctx.provide('tools', {});
await ctx.plugin(await import(pathToFileURL(pluginPath)), {}).await();
const request = { id: `verify-561-${label}`, sessionId: session.id, senderSessionId: 'verify-561-child-session',
  sender: 'verify-561-child', recipient: 'verify-561-main', body: `verify-561 agents message (${label})` };
const peer = { signal: new AbortController().signal, principal: { kind: 'owner' } };
let code = 0;
try {
  const result = await ctx.typertGateway.invoke({ namespace: 'agentMessages', method: 'receive', args: { request }, peer });
  console.log(`[${label}] agentMessages.receive result: ${JSON.stringify(result)}`);
} catch (error) {
  code = 1;
  console.log(`[${label}] agentMessages.receive threw: ${error.message}`);
  console.log(`[${label}]   at ${error.stack.split('\n').filter(line => line.includes(' at ')).slice(0, 3).map(line => line.trim()).join(' | ')}`);
}
const held = inbox.nextStep.filter(message => message.source?.communicationId === request.id).length;
console.log(`[${label}] OBSERVABLE: ${held ? 'DELIVERED' : 'NOT DELIVERED'} (next-step inbox holds ${held})`);
await ctx.fiber.dispose();
process.exit(code);
