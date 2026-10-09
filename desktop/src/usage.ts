import type { ActivityEvent } from '../electron/activity';
import { prices, type Price } from './prices.ts';

export type Tokens = Partial<Record<'input' | 'input_uncached' | 'output' | 'cache_read' | 'cache_write' | 'reasoning', number>>;
export type Call = {
  key: string; project: string; ticket: string; agent: string; session: string;
  model: string; time: string | null; tokens: Tokens; phase: string; offset: number;
  counter: boolean; cumulative?: Tokens; attributable: boolean;
};
export type Filters = { ticket?: string; agent?: string; model?: string; from?: string; to?: string };
export const metrics = ['input', 'output', 'cache_read', 'cache_write'] as const;

/** Retain only native usage, keyed by actual ownership rather than its display parent. */
export function collect(calls: Map<string, Call>, project: string, events: ActivityEvent[]): void {
  for (const event of events) {
    const usage = event.usage;
    if (event.kind !== 'usage' || !usage) continue;
    const session = String(usage.session ?? '');
    const identity = usage.identity;
    const key = JSON.stringify([project, identity || event.id]);
    const old = calls.get(key);
    if (old && (old.phase === 'final' && usage.phase !== 'final' || old.offset > event.source.offset)) continue;
    if (old?.counter) continue; // Preserve the original time/model of replayed counters.
    const tokens = Object.fromEntries(Object.entries(usage.tokens).filter(([, value]) =>
      Number.isFinite(value) && value >= 0)) as Tokens;
    const raw = usage.cumulative as Record<string, number> | undefined;
    const cumulative = raw ? Object.fromEntries(Object.entries({ input: raw.input_tokens,
      output: raw.output_tokens, cache_read: raw.cached_input_tokens,
      cache_write: raw.cache_write_input_tokens, reasoning: raw.reasoning_output_tokens,
    }).filter(([, value]) => Number.isFinite(value) && value >= 0)) as Tokens : undefined;
    calls.set(key, { key, project, session, ticket: String(usage.ticket_id ?? ''),
      agent: String(usage.agent ?? ''), model: event.model || 'Unknown model',
      time: event.time == null || !Number.isFinite(new Date(event.time).getTime()) ? null : new Date(event.time).toISOString(),
      tokens: { ...old?.tokens, ...tokens }, phase: usage.phase, offset: event.source.offset, counter: Boolean(cumulative), cumulative,
      attributable: usage.attributable && Boolean(identity) && Boolean(session),
    });
  }
}

/** Difference Codex counters before filtering, so stream snapshots cannot inflate totals. */
export function records(calls: Map<string, Call>, filters: Filters = {}): Call[] {
  const previous = new Map<string, Tokens>();
  return [...calls.values()].sort((a, b) => a.offset - b.offset).map(call => {
    if (!call.cumulative) return call;
    const key = JSON.stringify([call.project, call.session]);
    const before = previous.get(key);
    previous.set(key, call.cumulative);
    // A first observation may include earlier calls outside the retained Trace.
    // Only its reported last usage can be attributed to its model/time.
    if (!before) return call;
    const tokens: Tokens = {};
    for (const metric of [...metrics, 'reasoning'] as const) {
      const total = call.cumulative[metric];
      const prior = before[metric];
      if (total !== undefined && prior !== undefined && total >= prior) tokens[metric] = total - prior;
    }
    return { ...call, tokens };
  }).filter(call => (!filters.ticket || call.ticket === filters.ticket) &&
    (!filters.agent || call.agent === filters.agent) && (!filters.model || call.model === filters.model) &&
    (!filters.from || call.time !== null && call.time >= new Date(filters.from).toISOString()) &&
    (!filters.to || call.time !== null && call.time <= new Date(filters.to).toISOString()));
}

export type Cost = { amount: number | null; price?: Price; basis: string; reason?: string; parts: Partial<Record<keyof Tokens, number>> };

/** Apply a versioned original-vendor rate; absent operands never become zero. */
export function cost(call: Call, catalog: Price[] = prices): Cost {
  const versions = catalog.filter(price => price.models.includes(call.model));
  const price = versions.filter(price => price.effectiveFrom && call.time && price.effectiveFrom <= call.time &&
    (!price.effectiveTo || call.time < price.effectiveTo)).at(-1) ?? versions.at(-1);
  const parts: Cost['parts'] = {};
  const basis = price?.effectiveFrom && call.time && price.effectiveFrom <= call.time &&
    (!price.effectiveTo || call.time < price.effectiveTo) ? 'Historical applicable rate' : 'Current-rate approximation';
  const unknown = (reason: string): Cost => ({ amount: null, price, basis, reason, parts });
  if (!call.attributable) return unknown('Call ownership or identity unavailable');
  if (!price) return unknown('No verified model price');
  const t = call.tokens;
  let multiplier = 1;
  if (price.peak) {
    if (!call.time) return unknown('Peak/off-peak time unavailable');
    const date = new Date(call.time), hour = date.getUTCHours(), day = date.getUTCDay();
    // Without an official holiday calendar, weekday peak windows are ambiguous.
    if (day > 0 && day < 6 && (hour >= 1 && hour < 4 || hour >= 6 && hour < 10)) {
      return unknown('Peak/Chinese holiday applicability unverified');
    }
  }
  if (price.longContext && t.input === undefined) return unknown('Context tier requires total input');
  const long = price.longContext && t.input! > price.longContext.threshold;
  if (long) multiplier = price.longContext!.inputMultiplier;
  if (t.output !== undefined) parts.output = t.output * price.output * (long ? price.longContext!.outputMultiplier : 1) / 1e6;
  if (t.cache_read !== undefined) parts.cache_read = t.cache_read * price.cacheRead * multiplier / 1e6;
  const write = price.cacheWrite === null ? 0 : t.cache_write;
  if (write !== undefined && price.cacheWrite !== null) parts.cache_write = write * price.cacheWrite * multiplier / 1e6;
  if (t.input !== undefined && t.cache_read !== undefined && write !== undefined) {
    const ordinary = t.input - t.cache_read - write;
    if (ordinary < 0) return unknown('Cache quantities exceed total input');
    parts.input = ordinary * price.input * multiplier / 1e6;
  }
  if (parts.input === undefined || parts.output === undefined || parts.cache_read === undefined ||
      price.cacheWrite !== null && parts.cache_write === undefined) return unknown('Missing usage needed for pricing');
  return { amount: Object.values(parts).reduce((sum, value) => sum + value, 0), price, basis, parts };
}

/** Weighted cache rate and partial totals retain explicit per-field coverage. */
export function summarize(rows: Call[]) {
  const owned = rows.filter(row => row.attributable);
  const tokens = Object.fromEntries(metrics.map(metric => [metric, {
    value: owned.reduce((sum, row) => sum + (row.tokens[metric] ?? 0), 0),
    known: owned.filter(row => row.tokens[metric] !== undefined).length,
  }])) as Record<typeof metrics[number], { value: number; known: number }>;
  const operands = owned.length > 0 && owned.every(row => row.tokens.input !== undefined &&
    row.tokens.cache_read !== undefined && row.tokens.cache_read <= row.tokens.input);
  const priced = owned.map(row => ({ row, cost: cost(row) }));
  const complete = priced.filter(item => item.cost.amount !== null);
  const unpriced = priced.filter(item => item.cost.amount === null);
  return { tokens, count: owned.length, unidentified: rows.length - owned.length,
    counterObservations: owned.filter(row => row.counter).length,
    cacheRate: operands && tokens.input.value > 0 ? tokens.cache_read.value / tokens.input.value : null,
    amount: complete.reduce((sum, item) => sum + item.cost.amount!, 0), priced: complete.length,
    approximated: complete.filter(item => item.cost.basis === 'Current-rate approximation').length,
    unpriced: unpriced.length,
    unpricedTokens: Object.fromEntries(metrics.map(metric => [metric,
      unpriced.reduce((sum, item) => sum + (item.row.tokens[metric] ?? 0), 0)])) as Record<typeof metrics[number], number>,
  };
}

/** Use the same arithmetic for model breakdowns and UTC daily trends. */
export function groups(rows: Call[], by: 'model' | 'day') {
  const grouped = new Map<string, Call[]>();
  for (const row of rows) {
    const key = by === 'model' ? row.model : row.time?.slice(0, 10) ?? 'Unknown time';
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(row);
  }
  return [...grouped].sort(([a], [b]) => a.localeCompare(b)).map(([name, rows]) => ({ name, ...summarize(rows) }));
}
