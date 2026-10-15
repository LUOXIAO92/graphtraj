import type { ActivityEvent } from './activity';

export type Tokens = Partial<Record<'input' | 'input_uncached' | 'output' | 'cache_read' | 'cache_write' | 'reasoning', number>>;
export type Call = {
  key: string; project: string; task: string; agent: string; session: string;
  model: string; time: string | null; tokens: Tokens; phase: string; offset: number;
  counter: boolean; cumulative?: Tokens; baseline?: Tokens | null; attributable: boolean;
  source?: ActivityEvent['source'] & { event_id?: string };
};
export type Filters = { task?: string; agent?: string; model?: string; from?: string; to?: string };
export const metrics = ['input', 'output', 'cache_read', 'cache_write'] as const;

/** Calendar dates use the viewer's local timezone, including DST boundaries. */
export function localDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** Include today and the six preceding local calendar days. */
export function defaultDates(now = new Date()): Filters {
  const start = new Date(now);
  start.setDate(start.getDate() - 6);
  return { from: localDate(start), to: localDate(now) };
}

/** Date-only endpoints include the entire end day; timestamps retain exact semantics. */
function boundary(value: string, end: boolean): number {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(value).getTime();
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  if (localDate(date) !== value) return NaN;
  if (end) date.setDate(date.getDate() + 1);
  return date.getTime() - (end ? 1 : 0);
}

/** Retain only native usage, keyed by actual ownership rather than its display parent. */
export function collect(calls: Map<string, Call>, project: string, events: ActivityEvent[]): Call[] {
  const changed: Call[] = [];
  for (const event of events) {
    const usage = event.usage;
    if (event.kind !== 'usage' || !usage) continue;
    const session = String(usage.session ?? '');
    const identity = usage.identity;
    const key = JSON.stringify([project, identity || event.id]);
    const old = calls.get(key);
    if (old?.phase === 'final' && usage.phase !== 'final') continue;
    if (old && !old.counter && old.offset > event.source.offset && usage.phase !== 'final') continue;
    if (old?.counter && (old.baseline !== undefined || usage.previous_cumulative === undefined
        || event.source.offset > old.offset)) continue;
    const tokens = Object.fromEntries(Object.entries(usage.tokens).filter(([, value]) =>
      Number.isFinite(value) && value >= 0)) as Tokens;
    const convert = (raw: Record<string, number>): Tokens => Object.fromEntries(Object.entries({
      input: raw.input_tokens, output: raw.output_tokens, cache_read: raw.cached_input_tokens,
      cache_write: raw.cache_write_input_tokens, reasoning: raw.reasoning_output_tokens,
    }).filter(([, value]) => Number.isFinite(value) && value >= 0)) as Tokens;
    const cumulative = usage.cumulative ? convert(usage.cumulative as Record<string, number>) : undefined;
    const baseline = usage.previous_cumulative === undefined ? undefined : usage.previous_cumulative === null
      ? null : convert(usage.previous_cumulative as Record<string, number>);
    const call: Call = { key, project, session, task: String(usage.task_id ?? ''),
      agent: String(usage.agent ?? ''), model: event.model || 'Unknown model',
      time: old?.counter ? old.time : event.time == null || !Number.isFinite(new Date(event.time).getTime()) ? null : new Date(event.time).toISOString(),
      tokens: { ...old?.tokens, ...tokens }, phase: usage.phase, offset: event.source.offset, counter: Boolean(cumulative), cumulative, baseline, source: { ...event.source, event_id: event.id },
      attributable: usage.attributable && Boolean(identity) && Boolean(session),
    };
    if (JSON.stringify(old) !== JSON.stringify(call)) {
      calls.set(key, call); changed.push(call);
    }
  }
  return changed;
}

/** Difference Codex counters before filtering, so stream snapshots cannot inflate totals. */
export function records(calls: Map<string, Call>, filters: Filters = {}): Call[] {
  const previous = new Map<string, { totals: Tokens; row: Call }>();
  const result: Call[] = [];
  for (const call of [...calls.values()].sort((a, b) =>
    a.time && b.time && a.time !== b.time ? a.time.localeCompare(b.time) :
      a.cumulative && b.cumulative && a.session === b.session
        ? (a.cumulative.input ?? 0) + (a.cumulative.output ?? 0) - (b.cumulative.input ?? 0) - (b.cumulative.output ?? 0)
        : a.offset - b.offset)) {
    if (!call.cumulative) { result.push(call); continue; }
    const key = JSON.stringify([call.project, call.session]);
    const before = previous.get(key);
    // First retained totals may include inherited history; use only reported last usage.
    if (!before && !call.baseline) {
      const row = { ...call, tokens: { ...call.tokens } };
      result.push(row); previous.set(key, { totals: call.cumulative, row }); continue;
    }
    const tokens: Tokens = {};
    for (const metric of [...metrics, 'reasoning'] as const) {
      const total = call.cumulative[metric];
      const prior = (call.baseline === undefined ? before?.totals : call.baseline)?.[metric];
      if (total !== undefined && prior !== undefined && total >= prior) tokens[metric] = total - prior;
    }
    // An unchanged input counter with more output is an update to the same call.
    // Keep its input context for long-context pricing and its original timestamp.
    if (before && tokens.input === 0 && call.model === before.row.model
        && (call.baseline === undefined || JSON.stringify(call.baseline) === JSON.stringify(before.totals))) {
      for (const metric of [...metrics, 'reasoning'] as const) {
        if (tokens[metric] !== undefined && before.row.tokens[metric] !== undefined) {
          before.row.tokens[metric]! += tokens[metric]!;
        } else if (tokens[metric] === undefined && call.tokens[metric] !== undefined) {
          // Last-usage fields are per-call snapshots, not stream increments.
          before.row.tokens[metric] = call.tokens[metric];
        }
      }
      previous.set(key, { totals: call.cumulative, row: before.row });
    } else {
      // Providers may omit a field from lifetime totals while reporting it
      // on each call. Preserve that operand instead of dropping coverage.
      const row = { ...call, tokens: { ...call.tokens, ...tokens } };
      result.push(row); previous.set(key, { totals: call.cumulative, row });
    }
  }
  return result.filter(call => (!filters.task || call.task === filters.task) &&
    (!filters.agent || call.agent === filters.agent) && (!filters.model || call.model === filters.model) &&
    (!filters.from || call.time !== null && new Date(call.time).getTime() >= boundary(filters.from, false)) &&
    (!filters.to || call.time !== null && new Date(call.time).getTime() <= boundary(filters.to, true)));
}
