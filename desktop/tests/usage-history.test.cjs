const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { Projects } = require('../electron/projects.ts');
const { ActivityReader } = require('../electron/activity.ts');
const { UsageHistory } = require('../electron/history.ts');
const { records, summarize } = require('../src/usage.ts');

/** Controlled normalized native-boundary records, never a model execution. */
function event(id, input, output, extra = {}) {
  return { id, kind: 'usage', time: '2026-10-10T12:00:00Z', model: 'gpt-5.3-codex',
    source: { runtime: 'codex', offset: Number(id), trace: '/native/owned-session.jsonl' },
    text: 'must-not-be-copied', usage: { identity: 's:' + id, session: 's', task_id: '1',
      agent: 'child', attributable: true, phase: 'final', provider_usage: { secret: 'must-not-be-copied' },
      tokens: { input, output, cache_read: input / 2 }, ...extra } };
}

test('controlled Projects boundary persists monitor/backfill usage across refresh, replay, reopen and offline sources', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-history-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  for (const name of ['first', 'second']) await fs.mkdir(path.join(root, name));
  let offline = false;
  const reader = { read: async () => {
    if (offline) throw new Error('Source removed');
    return { tasks: [{ task_id: '1' }] };
  } };
  const a = event('1', 100, 5, { cumulative: { input_tokens: 100, output_tokens: 5 } });
  const b = event('2', 100, 10, { cumulative: { input_tokens: 100, output_tokens: 10 } });
  const c = event('3', 200, 20, { cumulative: { input_tokens: 300, output_tokens: 30 } });
  let expired = false;
  t.mock.method(ActivityReader.prototype, 'read', async (folder, request) => {
    if (offline) throw new Error('Source removed');
    const base = { agents: [{ alias: 'child' }], availability: 'available' };
    if (!request.alias) return base;
    if (expired && request.cursor) { expired = false; return { ...base, availability: 'cursor-expired' }; }
    if (folder.endsWith('second')) return { ...base, events: [event('1', 777, 3)] };
    const index = Number(request.cursor || 0);
    return { ...base, events: [a, b, c].slice(index, index + 1),
      cursor: String(Math.min(index + 1, 3)), has_more: index < 2 };
  });
  const file = path.join(root, '.graphtraj/projects.json');
  const projects = new Projects(file, reader);
  t.after(() => projects.close());
  await projects.load();
  const first = (await projects.add(path.join(root, 'first'))).selected;
  const second = (await projects.add(path.join(root, 'second'))).selected;
  await assert.rejects(async () => projects.usage('../unselected'), /added project/);
  // Monitor ingestion and simultaneous usage backfill may see the same event.
  await Promise.all([projects.activity({ projectId: first, task_id: '1', alias: 'child' }), projects.usage(first)]);
  const totals = value => summarize(records(new Map(value.calls.map(call => [call.key, call]))));
  let page = await settled(projects, first);
  assert.equal(totals(page).tokens.input.value, 300);
  assert.equal(totals(page).tokens.output.value, 30);
  assert.equal(totals(page).cacheRate, .5);
  assert.equal(totals(await settled(projects, second)).tokens.input.value, 777);
  assert.equal(totals(await projects.usage(first)).tokens.input.value, 300);
  projects.close();
  expired = true;
  const reopened = new Projects(file, reader);
  t.after(() => reopened.close());
  await reopened.load();
  const saved = await reopened.usage(first);
  assert.equal(totals(saved).tokens.input.value, 300, 'saved facts return before native replay');
  page = await settled(reopened, first);
  assert.equal(totals(page).tokens.output.value, 30);
  reopened.close();
  offline = true;
  const disconnected = new Projects(file, reader);
  t.after(() => disconnected.close());
  await disconnected.load();
  page = await settled(disconnected, first);
  assert.equal(totals(page).tokens.input.value, 300);
  assert.match(page.notices.join(' '), /saved history/);
  for (const name of await fs.readdir(path.join(root, '.graphtraj/usage-history'))) {
    assert.doesNotMatch(await fs.readFile(path.join(root, '.graphtraj/usage-history', name), 'utf8'), /must-not-be-copied/);
  }
  await disconnected.remove(first);
  await assert.rejects(async () => disconnected.usage(first), /added project/);
});

/** Wait for the public background observation, never inspect private implementation state. */
async function settled(projects, id) {
  let page = await projects.usage(id);
  for (let i = 0; page.pending && i < 400; i++) {
    await new Promise(resolve => setTimeout(resolve, 5));
    page = await projects.usage(id);
  }
  assert.equal(page.pending, false, 'background read completed');
  return page;
}

test('legacy facts reconcile from native baselines while original history and source remain retained', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-correction-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { createHash } = require('node:crypto');
  const { collect } = require('../electron/usage.ts');
  const project = 'p';
  const original = new Map();
  const a = event('1', 100, 10, { cumulative: { input_tokens: 100, output_tokens: 10 } });
  const b = event('2', 100, 10, { cumulative: { input_tokens: 1000, output_tokens: 100 } });
  collect(original, project, [a, b]);
  for (const call of original.values()) delete call.source; // Version one did not retain source locators.
  const file = path.join(root, createHash('sha256').update(project).digest('hex') + '.json');
  const bytes = JSON.stringify({ version: 1, calls: [...original.values()] });
  await fs.writeFile(file, bytes);
  const store = new UsageHistory(root);
  let calls = await store.receive(project);
  assert.equal(summarize(records(new Map(calls.map(call => [call.key, call])))).tokens.input.value, 1000);
  calls = await store.receive(project, [{ ...a, source: { ...a.source, offset: 500 },
    usage: { ...a.usage, previous_cumulative: a.usage.cumulative } }]);
  assert.equal(summarize(records(new Map(calls.map(call => [call.key, call])))).tokens.input.value, 1000,
    'a later repeated counter cannot erase the original call during reconciliation');
  calls = await store.receive(project, [{ ...a, usage: { ...a.usage, previous_cumulative: null } },
    { ...b, usage: { ...b.usage, previous_cumulative: { input_tokens: 900, output_tokens: 90 } } }]);
  assert.equal(summarize(records(new Map(calls.map(call => [call.key, call])))).tokens.input.value, 200);
  assert.equal(await fs.readFile(file, 'utf8'), bytes);
  const recovered = await new UsageHistory(root).receive(project);
  assert.deepEqual(recovered, calls);
  assert.equal(calls[1].source.trace, '/native/owned-session.jsonl');
  assert.equal(calls[1].source.event_id, b.id);
});

test('same representative dataset cold/hot/reopen avoids history pages and multi-reference charging', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-benchmark-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await fs.mkdir(path.join(root, 'one')); await fs.mkdir(path.join(root, 'two'));
  const reader = { read: async () => ({ tasks: [] }) };
  let reads = 0, written = 600;
  let release;
  let slow = false;
  t.mock.method(ActivityReader.prototype, 'read', async (folder, request) => {
    reads++;
    if (folder.endsWith('two') && slow) await new Promise(resolve => { release = resolve; });
    const base = { agents: [{ alias: 'a', runtime: 'codex', session: 's' },
      { alias: 'another-reference', runtime: 'codex', session: 's' }], availability: 'available' };
    if (!request.alias) return base;
    const start = Number(request.cursor || 0), end = Math.min(start + 200, written);
    return { ...base, events: Array.from({ length: end - start }, (_, i) => event(String(start + i + 1), 100, 10)),
      cursor: String(end), has_more: end < written };
  });
  const file = path.join(root, '.graphtraj/projects.json');
  const projects = new Projects(file, reader); t.after(() => projects.close());
  await projects.load();
  const first = (await projects.add(path.join(root, 'one'))).selected;
  const second = (await projects.add(path.join(root, 'two'))).selected;
  const started = performance.now();
  assert.equal((await projects.usage(first)).calls.length, 0);
  assert.equal((await settled(projects, first)).calls.length, 600);
  const cold = { ms: performance.now() - started, reads };
  const hotStart = performance.now(), hotReads = reads;
  assert.equal((await projects.usage(first)).calls.length, 600);
  const hot = { ms: performance.now() - hotStart, reads: reads - hotReads };
  await settled(projects, second);
  projects.close();
  const reopened = new Projects(file, reader); t.after(() => reopened.close());
  await reopened.load();
  const reopenStart = performance.now(), reopenReads = reads;
  const saved = await reopened.usage(first);
  assert.equal(saved.calls.length, 600);
  const reopenSavedMs = performance.now() - reopenStart;
  assert.equal((await settled(reopened, first)).calls.length, 600);
  const reopen = { ms: performance.now() - reopenStart, saved_ms: reopenSavedMs, reads: reads - reopenReads };
  assert.equal(hot.reads, 0); assert.ok(reopen.reads < cold.reads);
  console.log(JSON.stringify({ dataset: '600 facts, 200 per page, 2 aliases for same Session', cold, hot, reopen }));
  // One blocked project's native transport cannot delay saved results from either project.
  slow = true;
  assert.equal((await reopened.usage(second)).calls.length, 600);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(release);
  assert.equal((await reopened.usage(first)).calls.length, 600);
  slow = false; release();
  await settled(reopened, second);
  reopened.close();
  written = 601;
  const appended = new Projects(file, reader); t.after(() => appended.close());
  await appended.load();
  assert.equal((await settled(appended, first)).calls.length, 601);
  assert.equal((await appended.usage(first)).calls.length, 601);
  await appended.remove(second);
  await assert.rejects(appended.usage(second), /added project/);
});

test('removing an indexed project stops the remainder of its active native read batch', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'usage-removal-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  let entered, release;
  const started = new Promise(resolve => { entered = resolve; });
  const requests = [];
  t.mock.method(ActivityReader.prototype, 'read', async (folder, request) => {
    if (!request.alias) return { agents: [{ alias: 'first' }, { alias: 'second' }] };
    requests.push(request.alias);
    if (request.alias === 'first') await new Promise(resolve => { release = resolve; entered(); });
    return { agents: [], events: [event('1', 100, 10)], availability: 'available' };
  });
  const projects = new Projects(path.join(root, '.graphtraj/projects.json'), { read: async () => ({ tasks: [] }) });
  t.after(() => projects.close());
  await projects.load();
  const id = (await projects.add(root)).selected;
  await projects.usage(id);
  await started;
  await projects.remove(id);
  release();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(requests, ['first']);
  await assert.rejects(projects.usage(id), /added project/);
});
