/** Native Session/Remote registration with a controlled inbox, no model/UI. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [nativePackage, modulePath] = process.argv.slice(2);
const require = createRequire(nativePackage);
const load = name => import(pathToFileURL(require.resolve(name)));
const { Context } = await load('@deepseek-ai/cordis');
const { SessionStore } = await load('@deepseek-ai/dsh-session');
const { SessionQueryEngine } = await load('@deepseek-ai/dsh-session-query');
const { TypertRemoteService, Remote, remoteMethods } = await load('@deepseek-ai/dsh-typert-protocol');
const { TypertRegistry } = await load('@deepseek-ai/dsh-typert-registry');
const { TypertGatewayService } = await load('@deepseek-ai/dsh-api-gateway');
const { createUserMessage, AssistantStreamAccumulator } = await load('@deepseek-ai/dsh-llm');
const { installCommunication } = await import(pathToFileURL(modulePath));
const ctx = new Context();
await ctx.plugin(SessionStore).await();
await ctx.plugin(SessionQueryEngine).await();
await ctx.plugin(TypertRegistry).await();
await ctx.plugin(TypertGatewayService, {}).await();
const session = ctx.sessions.create('receiver', { meta: { cwd: process.cwd() } });
const inbox = { nextTurn: [], nextStep: [] };
let deliveries = 0;
const agent = { inbox, send(message, target, wakeup) {
  assert.equal(target, 'next-step');
  assert.equal(wakeup, true);
  inbox.nextStep.push(message);
  deliveries += 1;
} };
ctx.provide('agents', { get: id => id === session.id ? agent : undefined });
await installCommunication(ctx, { TypertRemoteService, Remote, createUserMessage }).await();
assert.equal(remoteMethods(ctx.agentMessages)[0].method, 'receive');
const fact = { id: 'execution-result-1', sessionId: session.id,
  senderSessionId: 'actual-child-session', sender: 'child-agent', recipient: 'parent-agent', body: 'reply body' };
const receive = request => ctx.typertGateway.invoke({ namespace: 'agentMessages', method: 'receive', args: { request } });
await Promise.all([receive(fact), receive(fact)]);
assert.equal(deliveries, 1);
const message = inbox.nextStep.shift();
session.append('user/message', message, { surfaceOp: 'append' });
await receive(fact);
assert.equal(deliveries, 1);
assert.deepEqual(session.deriveMessages()[0].content, [{ type: 'text', text: 'reply body' }]);
assert.equal(message.source.form, 'relay');
assert.equal(message.source.senderSessionId, fact.senderSessionId);
assert.equal(message.source.recipientAgentId, fact.recipient);
await assert.rejects(receive({ ...fact, sessionId: 'unmapped' }));
await ctx.fiber.dispose();
const chunks = [
  { time: 100, chunk: { type: 'text-delta', index: 0, text: 'one' } },
  { time: 90, chunk: { type: 'text-delta', index: 0, text: 'two' } },
  { time: 95, chunk: { type: 'reasoning-delta', index: 1, text: 'reason' } },
  { time: 96, chunk: { type: 'tool-call-delta', index: 2, id: 'call', name: 'read', argumentsDelta: '{' } },
  { time: 97, chunk: { type: 'tool-call-delta', index: 2, id: 'call', name: 'read', argumentsDelta: '}' } },
  { time: 98, chunk: { type: 'text-delta', index: 0, text: 'after tool' } },
];
const accumulator = new AssistantStreamAccumulator();
for (const chunk of chunks) accumulator.push(chunk);
console.log(JSON.stringify({ chunks, stream: accumulator.snapshot() }));
