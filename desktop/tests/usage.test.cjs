const test = require('node:test');
const assert = require('node:assert/strict');
const { collect, records, cost, summarize, groups } = require('../src/usage.ts');

function event(id, tokens, extra = {}) {
  return { id, kind: 'usage', model: 'gpt-5.3-codex', time: '2026-10-10T12:00:00Z',
    source: { offset: Number(id.replace(/\D/g, '')) || 1, runtime: 'dsh' },
    usage: { tokens, identity: 's:' + id, phase: 'final', attributable: true,
      session: 's', ticket_id: '263', agent: 'child', ...extra } };
}

test('stream totals replace, final wins, replay and parent display count the actual child once', () => {
  const map = new Map();
  const a = event('1', { input: 100, cache_read: 25, cache_write: 0, output: 1 }, { phase: 'stream' });
  const b = event('2', { input: 100, cache_read: 25, cache_write: 0, output: 10 }, { identity: 's:1' });
  collect(map, 'p', [a, b, a, b]);
  collect(map, 'p', [{ ...b, id: 'parent-copy', agent: 'parent' }]);
  assert.equal(map.size, 1);
  assert.equal(records(map)[0].agent, 'child');
  assert.equal(summarize(records(map)).tokens.output.value, 10);
  assert.equal(summarize(records(map)).cacheRate, .25);
});

test('weighted cache rate includes writes in denominator, and missing operands stay unknown', () => {
  const map = new Map();
  collect(map, 'p', [event('1', { input: 100, cache_read: 90, cache_write: 10, output: 10 }),
    event('2', { input: 900, cache_read: 0, cache_write: 400, output: 20 })]);
  assert.equal(summarize(records(map)).cacheRate, .09);
  collect(map, 'p', [event('3', { input: 100, output: 5 })]);
  assert.equal(summarize(records(map)).cacheRate, null);
  assert.equal(summarize(records(map)).tokens.cache_read.known, 2);
});

test('known official arithmetic reproduces breakdowns, trends, missing prices and historical selection', () => {
  const map = new Map();
  collect(map, 'p', [event('1', { input: 1000000, cache_read: 600000, output: 100000 }),
    { ...event('2', { input: 1000, cache_read: 100, output: 100 }), model: 'unverified' }]);
  const rows = records(map), total = summarize(rows);
  assert.equal(cost(rows[0]).amount, 2.205); // 0.4*1.75 + 0.6*.175 + 0.1*14
  assert.equal(total.amount, 2.205);
  assert.equal(total.unpriced, 1);
  assert.equal(total.unpricedTokens.input, 1000);
  assert.equal(groups(rows, 'model').reduce((n, row) => n + row.amount, 0), total.amount);
  assert.equal(groups(rows, 'day')[0].amount, total.amount);
  const current = cost(rows[0]).price;
  const historic = { ...current, id: 'historical-controlled', effectiveFrom: '2026-10-01', effectiveTo: '2026-11-01', input: 1 };
  assert.equal(cost(rows[0], [historic, current]).basis, 'Historical applicable rate');
  assert.ok(Math.abs(cost(rows[0], [historic, current]).amount - 1.905) < 1e-12);
  assert.equal(cost(rows[0]).basis, 'Current-rate approximation');
});

test('Astra charges disjoint cache writes and includes reasoning once; long context uses documented multipliers', () => {
  const map = new Map();
  collect(map, 'p', [{ ...event('1', { input: 100000, cache_read: 50000, cache_write: 10000, output: 1000, reasoning: 800 }), model: 'gpt-6-astra' }]);
  const row = records(map)[0];
  assert.equal(cost(row).amount, .625); // .4 + .05 + .125 + .05
  assert.equal(cost({ ...row, tokens: { ...row.tokens, input: 300000 } }).amount, 5.225);
  assert.equal(cost({ ...row, tokens: { input: 100000, cache_read: 50000, output: 1000 } }).amount, null);
});

test('DeepSeek off-peak and unknown peak holiday applicability stay distinct', () => {
  const map = new Map();
  collect(map, 'p', [{ ...event('1', { input: 1000000, cache_read: 500000, cache_write: 1000, output: 100000 }), model: 'deepseek-v4-flash' }]);
  const row = records(map)[0];
  assert.equal(cost(row).amount, .1365);
  assert.equal(cost({ ...row, time: '2026-10-09T02:00:00Z' }).amount, null);
  assert.match(cost({ ...row, time: '2026-10-09T02:00:00Z' }).reason, /holiday/);
});

test('cumulative updates difference before model/time filtering and replay do not sum snapshots', () => {
  const map = new Map();
  const make = (id, output, time) => ({ ...event(id, { input: 100, cache_read: 60, output }, {
    cumulative: { input_tokens: 100, cached_input_tokens: 60, output_tokens: output } }), time });
  const a = make('1', 5, '2026-10-10T10:00:00Z'), b = make('2', 10, '2026-10-10T11:00:00Z');
  collect(map, 'p', [a, b, a, b]);
  assert.equal(summarize(records(map)).tokens.output.value, 10);
  assert.equal(summarize(records(map)).tokens.input.value, 100);
  assert.equal(records(map).length, 1);
  assert.equal(summarize(records(map, { from: '2026-10-10T10:30:00Z' })).tokens.output.value, 0);
});

test('project, ownership, model and time filters preserve unknown/unattributable coverage', () => {
  const map = new Map();
  collect(map, 'p', [event('1', { input: 0, output: 0 }, { attributable: false }), event('2', { input: 50 })]);
  collect(map, 'other-project', [event('2', { input: 75 })]);
  assert.equal(map.size, 3);
  assert.equal(summarize(records(map)).unidentified, 1);
  assert.equal(records(map, { agent: 'parent' }).length, 0);
  assert.equal(records(map, { model: 'other' }).length, 0);
  assert.equal(records(map, { ticket: '262' }).length, 0);
  assert.equal(records(map, { to: '2026-10-09T00:00:00Z' }).length, 0);
});

test('partial cumulative stream fields retain previously reported operands', () => {
  const map = new Map();
  collect(map, 'p', [event('1', { input: 100, cache_read: 20 }, { phase: 'stream' }),
    event('2', { output: 8 }, { identity: 's:1', phase: 'stream' }),
    event('3', { output: 10 }, { identity: 's:1', phase: 'final' })]);
  const result = summarize(records(map));
  assert.equal(result.tokens.input.value, 100);
  assert.equal(result.tokens.output.value, 10);
  assert.equal(result.cacheRate, .2);
});

test('streamed Codex output retains the original long-context price tier', () => {
  const map = new Map();
  const tokens = { input: 300000, cache_read: 100000, cache_write: 100000, output: 1000 };
  const make = (id, output) => ({ ...event(id, { ...tokens, output }, {
    cumulative: { input_tokens: 300000, cached_input_tokens: 100000, cache_write_input_tokens: 100000, output_tokens: output },
  }), model: 'gpt-6-astra' });
  collect(map, 'p', [make('1', 1000), make('2', 2000)]);
  const rows = records(map);
  assert.equal(rows.length, 1);
  assert.equal(cost(rows[0]).amount, 4.85); // 2 + .2 + 2.5 + .15
});
