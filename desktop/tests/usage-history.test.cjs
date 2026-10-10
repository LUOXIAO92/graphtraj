const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { Projects } = require('../electron/projects.ts');
const { ActivityReader } = require('../electron/activity.ts');
const { records, summarize } = require('../src/usage.ts');

/** Controlled normalized native-boundary records, never a model execution. */
function event(id, input, output, extra = {}) {
  return { id, kind: 'usage', time: '2026-10-10T12:00:00Z', model: 'gpt-5.3-codex',
    source: { runtime: 'codex', offset: Number(id), trace: 'must-not-be-copied' },
    text: 'must-not-be-copied', usage: { identity: 's:' + id, session: 's', ticket_id: '1',
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
    return { tickets: [{ ticket_id: '1' }] };
  } };
  const a = event('1', 100, 5, { cumulative: { input_tokens: 100, output_tokens: 5 } });
  const b = event('2', 100, 10, { cumulative: { input_tokens: 100, output_tokens: 10 } });
  const c = event('3', 200, 20, { cumulative: { input_tokens: 300, output_tokens: 30 } });
  let expired = false;
  t.mock.method(ActivityReader.prototype, 'read', async (folder, request) => {
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
  await Promise.all([projects.activity({ projectId: first, ticket_id: '1', alias: 'child' }), projects.usage(first)]);
  assert.equal((await projects.usage(first)).pending, true);
  let page = await projects.usage(first);
  assert.equal(page.pending, false);
  const totals = value => summarize(records(new Map(value.calls.map(call => [call.key, call]))));
  assert.equal(totals(page).tokens.input.value, 300);
  assert.equal(totals(page).tokens.output.value, 30);
  assert.equal(totals(page).cacheRate, .5);
  assert.equal(totals(await projects.usage(second)).tokens.input.value, 777);
  assert.equal(totals(await projects.usage(first)).tokens.input.value, 300);
  expired = true;
  page = await projects.usage(first);
  assert.equal(page.pending, true);
  assert.equal(totals(page).tokens.input.value, 300, 'cursor expiration must not erase saved history');
  for (let i = 0; i < 3; i++) page = await projects.usage(first);
  assert.equal(totals(page).tokens.output.value, 30);
  projects.close();
  const reopened = new Projects(file, reader);
  t.after(() => reopened.close());
  await reopened.load();
  for (let i = 0; i < 3; i++) page = await reopened.usage(first);
  assert.equal(totals(page).tokens.input.value, 300);
  assert.equal(totals(page).tokens.output.value, 30);
  offline = true;
  page = await reopened.usage(first);
  assert.equal(totals(page).tokens.input.value, 300);
  assert.match(page.notices.join(' '), /saved history/);
  for (const name of await fs.readdir(path.join(root, '.graphtraj/usage-history'))) {
    assert.doesNotMatch(await fs.readFile(path.join(root, '.graphtraj/usage-history', name), 'utf8'), /must-not-be-copied/);
  }
  await reopened.remove(first);
  await assert.rejects(async () => reopened.usage(first), /added project/);
});
