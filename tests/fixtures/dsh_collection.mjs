/** Exercise the installed DSH v4 event/flush services, without launching an Agent. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { globSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const [nativePackage, modulePath, python] = process.argv.slice(2);
const require = createRequire(nativePackage);
const load = name => import(pathToFileURL(require.resolve(name)).href);
const { Context } = await load('@deepseek-ai/cordis');
const { SessionStore, buildForkSeed } = await load('@deepseek-ai/dsh-session');
const { SessionQueryEngine } = await load('@deepseek-ai/dsh-session-query');
const { createUserMessage } = await load('@deepseek-ai/dsh-llm');
const { default: JsonlPersistence } = await load('@deepseek-ai/dsh-session-persistence-jsonl');
const { installCollection } = await import(pathToFileURL(modulePath).href);
const ctx = new Context();
await ctx.plugin(SessionStore).await();
await ctx.plugin(SessionQueryEngine).await();
const nativeRoot = join(process.cwd(), 'native-durable');
mkdirSync(nativeRoot);
await ctx.plugin(JsonlPersistence, { root: nativeRoot, compression: 'none' }).await();
const failures = [];
const counts = [];
let failNext = false;
async function entry(agent, payload) {
  if (failNext) { failNext = false; throw new Error('controlled delivery interruption'); }
  const result = await new Promise((resolve, reject) => {
    const child = spawn(python, ['-m', 'graphtraj.runtimes.native_entry', 'dsh'], {
      cwd: process.cwd(), env: { ...process.env,
        DSH_SESSION_ID: agent.session.id, DSH_GRAPHTRAJ_SESSION: agent.session.id,
        DSH_GRAPHTRAJ_SOURCE: agent.session.header.origin ? 'child' : 'main' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let output = '', errors = '';
    child.stdout.on('data', part => { output += part; });
    child.stderr.on('data', part => { errors += part; });
    child.on('error', reject);
    child.on('close', code => {
      if (code) reject(new Error(errors));
      else { try { resolve(JSON.parse(output)); } catch (error) { reject(error); } }
    });
    child.stdin.end(JSON.stringify(payload));
  });
  if (result.error) throw new Error(result.error);
  if (payload.records) counts.push(payload.records.length);
  return result;
}
const collect = installCollection(ctx, entry);
const session = ctx.sessions.create('real-main', { meta: { cwd: process.cwd() } });
await ctx.sessionPersistence.create(session.header);
let callbacks = 0;
ctx.on('session/event', () => { callbacks += 1; });
const agent = { session };
await entry(agent, { event: 'agent/created', source: 'startup', header: session.header });
// The pre-existing prefix must be captured, even though the listener missed it.
session.append('turn/start', { turn: 0 });
assert.equal(callbacks, 1);
assert.equal(globSync('**/*.jsonl', { cwd: nativeRoot }).length, 0);
session.append('step/start', { turn: 0, step: 0 });
await collect(agent);
session.append('user/message', createUserMessage({
  content: [{ type: 'text', text: 'native append sentinel' }], source: { kind: 'user' },
}), { surfaceOp: 'append' });
await ctx.sessions.flush(session);
// A failed transport must remain replayable; the native flush reports the error.
failNext = true;
session.append('step/end', { turn: 0, step: 0 });
try { await ctx.sessions.flush(session); } catch (error) { failures.push(error.message); }
await ctx.sessions.flush(session);
session.append('turn/end', { turn: 0, reason: { kind: 'completed' } });
await ctx.sessions.flush(session);
const observation = await ctx.sessionQuery.observeSession(session.id, { projectionMode: 'none' });
const original = [...observation.events];
observation[Symbol.dispose]();
// Resume replays the same seqs into the same Python archive.
await collect(agent);
await ctx.sessions.flush(session);
const seed = buildForkSeed(original, original.at(-1).seq);
const child = ctx.sessions.create('real-child', {
  seed, inheritedEventCount: original.length,
  meta: { cwd: process.cwd(), origin: 'subagent', delegationDepth: 1,
          parentSession: session.id, isSeeded: true },
});
await entry({ session: child }, { event: 'agent/created', source: 'startup', header: child.header });
await collect({ session: child });
await ctx.sessions.flush(child);
assert.ok(failures.some(message => message.includes('controlled delivery interruption')));
// Shutdown must drain the final event even without another explicit checkpoint.
session.append('turn/start', { turn: 1 });
const finalObservation = await ctx.sessionQuery.observeSession(session.id, { projectionMode: 'none' });
const finalEvents = [...finalObservation.events];
finalObservation[Symbol.dispose]();
const childObservation = await ctx.sessionQuery.observeSession(child.id, { projectionMode: 'none' });
const childEvents = [...childObservation.events];
childObservation[Symbol.dispose]();
await ctx.fiber.dispose();
const nativeFile = globSync('**/*.jsonl', { cwd: nativeRoot })[0];
assert.ok(nativeFile);
const nativeDisk = readFileSync(join(nativeRoot, nativeFile), 'utf8').trim().split('\n').map(JSON.parse);
assert.deepEqual(nativeDisk.slice(1), finalEvents);
console.log(JSON.stringify({ count: original.length, counts, failures,
  callbackBeforeDisk: true, nativeDiskEvents: nativeDisk.slice(1),
  header: session.header, events: finalEvents, messages: session.deriveMessages(),
  child: { header: child.header, events: childEvents, messages: child.deriveMessages() },
}));
