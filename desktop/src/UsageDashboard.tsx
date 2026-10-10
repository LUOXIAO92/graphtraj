import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card } from '@heroui/react';
import type { Project } from '../electron/types';
import { defaultDates, localDate, cost, groups, metrics, records, summarize, type Call, type Filters } from './usage.ts';
import { prices } from './prices.ts';
import './usage.css';

const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 6 });
const money = (value: number) => '$' + value.toFixed(6);

/** Query backend-owned history; UI filters never limit collection or write usage facts. */
export function UsageView({ projectId, projects = [] }: { projectId?: string; projects?: Project[] }) {
  const [calls, setCalls] = useState(new Map<string, Call>());
  const [filters, setFilters] = useState<Filters>(() => defaultDates());
  const [coverage, setCoverage] = useState<string[]>([]);
  const [updated, setUpdated] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const global = projectId === undefined;
  const selection = JSON.stringify(projectId ? [projectId] : projects.map(project => project.id));
  const projectNames = JSON.stringify(projects.map(({ id, root }) => [id, root]));
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const retained = new Map<string, Call>();
    setCalls(new Map()); setUpdated(''); setLoading(true);
    async function refresh() {
      const notices: string[] = [];
      let pending = false;
      for (const id of JSON.parse(selection) as string[]) {
        try {
          const page = await window.graphtraj.usage(id);
          if (!alive) return;
          for (const call of page.calls) retained.set(call.key, call);
          const name = projects.find(project => project.id === id)?.root;
          notices.push(...page.notices.map(notice => global && name ? `${name}: ${notice}` : notice));
          pending ||= page.pending;
        } catch { notices.push('Usage history could not be read or saved. Showing the last successful read; retrying.'); }
      }
      if (alive) {
        setCalls(new Map(retained)); setCoverage([...new Set(notices)]);
        setUpdated(new Date().toISOString()); setLoading(pending);
        timer = setTimeout(refresh, pending ? 250 : 3000);
      }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [selection, projectNames, retry]);
  const all = useMemo(() => records(calls), [calls]);
  const rows = useMemo(() => !filters.from || !filters.to || filters.from > filters.to ? [] : records(calls, filters), [calls, filters]);
  const total = summarize(rows);
  const breakdown = groups(rows, 'model'), trend = groups(rows, 'day');
  const comparison = projects.map(project => ({
    name: project.root, ...summarize(rows.filter(row => row.project === project.id)),
  }));
  const knownDays = all.flatMap(row => row.time ? [localDate(new Date(row.time))] : []).sort();
  const invalidRange = !filters.from || !filters.to || filters.from > filters.to;
  const patch = (key: keyof Filters, value: string) => setFilters(old => ({ ...old, [key]: value }));
  function table(data: ReturnType<typeof groups>, caption: string) {
    return <div className="usage-table"><table><caption>{caption}</caption><thead><tr>
      <th scope="col">{caption === 'Daily trend (local dates)' ? 'Date' : caption === 'Project comparison' ? 'Project' : 'Model'}</th><th scope="col">Usage records</th>
      {metrics.map(metric => <th scope="col" key={metric}>{metric.replace('_', ' ')}</th>)}
      <th scope="col">Cache read rate</th><th scope="col">Priced subtotal USD</th><th scope="col">Unpriced records</th>
    </tr></thead><tbody>{data.map(row => <tr key={row.name}><th scope="row">{row.name}</th><td>{row.count}</td>
      {metrics.map(metric => <td key={metric}>{row.tokens[metric].known ? number(row.tokens[metric].value) : 'Unknown'}
        <small>{row.tokens[metric].known}/{row.count} reported</small></td>)}
      <td>{row.cacheRate === null ? 'Unknown' : number(row.cacheRate * 100) + '%'}</td>
      <td>{row.priced ? money(row.amount) : 'Unknown'}<small>{row.priced}/{row.count} priced</small></td><td>{row.unpriced}</td>
    </tr>)}</tbody></table></div>;
  }
  return <section className="usage-dashboard" aria-label="Usage dashboard">
    <header><div><p className="eyebrow">Recorded Runtime usage</p><h1>{global ? 'Global usage' : 'Project usage'}</h1></div>
      <Button variant="secondary" onPress={() => setRetry(value => value + 1)}>Reconnect usage</Button></header>
    <p role="status">{loading ? 'Loading history…' : 'Observation active'} · Last update {updated || 'not yet available'} · {global ? 'Added projects only' : 'Project selected in sidebar'}</p>
    <div className="usage-filters">
      {!global && <><label>Ticket<select value={filters.ticket ?? ''} onChange={event => patch('ticket', event.target.value)}><option value="">All tickets</option>
        {[...new Set(all.map(row => row.ticket))].sort().map(ticket => <option key={ticket} value={ticket}>#{ticket}</option>)}</select></label>
      <label>Agent<select value={filters.agent ?? ''} onChange={event => patch('agent', event.target.value)}><option value="">All Agents</option>
        {[...new Set(all.map(row => row.agent))].sort().map(agent => <option key={agent}>{agent}</option>)}</select></label>
      <label>Model<select value={filters.model ?? ''} onChange={event => patch('model', event.target.value)}><option value="">All models</option>
        {[...new Set(all.map(row => row.model))].sort().map(model => <option key={model}>{model}</option>)}</select></label></>}
      <label>Start date<input type="date" value={filters.from ?? ''} onChange={event => patch('from', event.target.value)} /></label>
      <label>End date<input type="date" value={filters.to ?? ''} onChange={event => patch('to', event.target.value)} /></label>
      <Button variant="ghost" onPress={() => setFilters(defaultDates())}>Last 7 days</Button>
    </div>
    {invalidRange ? <p role="alert">Choose both dates with the start on or before the end. No totals are shown for an invalid range.</p>
      : <p>Includes both dates in local time. The same start and end selects one full calendar day.</p>}
    <div className="usage-cards">{metrics.map(metric => <Card key={metric}><Card.Header><Card.Description>{metric.replace('_', ' ')} tokens</Card.Description>
      <Card.Title>{total.tokens[metric].known ? number(total.tokens[metric].value) : 'Unknown'}</Card.Title></Card.Header>
      <Card.Content>{total.tokens[metric].known}/{total.count} records reported</Card.Content></Card>)}
      <Card><Card.Header><Card.Description>Weighted cache read rate</Card.Description><Card.Title>{total.cacheRate === null ? 'Unknown' : number(total.cacheRate * 100) + '%'}</Card.Title></Card.Header>
        <Card.Content>Cache reads ÷ input including cached tokens. Writes are not hits.</Card.Content></Card>
      <Card><Card.Header><Card.Description>Official-price equivalent · USD</Card.Description><Card.Title>{total.priced ? money(total.amount) : 'Unknown'}</Card.Title></Card.Header>
        <Card.Content>Priced subtotal: {total.priced}/{total.count} records. {total.approximated} at current-rate approximation.</Card.Content></Card>
    </div>
    <p>Equivalent token estimate, not a provider bill or subscription invoice. Standard-tier equivalent for OpenAI; third-party routing charges are not inferred.</p>
    <Card><Card.Header><Card.Title>Data coverage</Card.Title></Card.Header><Card.Content>
      <p>{total.count} attributable usage records · {total.unidentified} excluded without call identity/ownership · {total.unpriced} unpriced records</p>
      <p>Unpriced known quantities: {metrics.map(metric => `${metric.replace('_', ' ')} ${number(total.unpricedTokens[metric])}`).join(' · ')}. Missing quantities remain unknown.</p>
      <p>Main calls are not covered by this member view. {all.filter(row => !row.time).length} records have unknown time; time filters exclude them.</p>
      <p>{total.counterObservations} Codex cumulative observations: provider call IDs are not recorded; differences prevent repeated counters inflating totals. Initial earlier counter history is not attributed to this model.</p>
      <p>Missing fields are unknown, never zero. Totals cover retained usage only, not guaranteed coverage of every date in the selected range.</p>
      <p>Saved records with known dates: {knownDays.length ? `${knownDays[0]} through ${knownDays.at(-1)}` : 'none'}. Dates without records mean no reported usage, not zero consumption.</p>
      <p>History is saved under HOME/.graphtraj. Retained native records are backfilled while viewing usage; records unavailable from the source cannot be recovered. Closing the desktop does not affect Runner.</p>
      {coverage.length > 0 && <details open><summary>Observation gaps ({coverage.length})</summary><ul>{coverage.map(value => <li key={value}>{value}</li>)}</ul></details>}
    </Card.Content></Card>
    {!rows.length && <p>No usage records match this view.</p>}
    {global ? table(comparison, 'Project comparison') : table(breakdown, 'Model breakdown')}
    <div className="usage-trend" aria-label="Daily recorded input tokens">{trend.map(day => <div key={day.name}><span>{day.name}</span>
      {day.tokens.input.known > 0 && <meter min={0} max={Math.max(1, ...trend.map(item => item.tokens.input.value))} value={day.tokens.input.value} aria-label={`${day.name} input tokens`} />}
      <span>{day.tokens.input.known ? number(day.tokens.input.value) : 'Unknown'} input tokens</span></div>)}</div>
    {table(trend, 'Daily trend (local dates)')}
    {!global && <details><summary>Call arithmetic and unpriced reasons</summary><div className="usage-table"><table><thead><tr>
      <th>Time</th><th>Ticket / Agent</th><th>Model</th><th>USD / reason</th><th>Price basis</th></tr></thead><tbody>
      {rows.map(row => { const estimate = cost(row); return <tr key={row.key}><td>{row.time ?? 'Unknown'}</td><td>#{row.ticket}<small>{row.agent}</small></td>
        <td>{row.model}<small>{metrics.map(metric => `${metric}: ${row.tokens[metric] ?? 'unknown'}`).join(' · ')}</small></td>
        <td>{estimate.amount === null ? estimate.reason : money(estimate.amount)}<small>{Object.entries(estimate.parts).map(([key, value]) => `${key} ${money(value)}`).join(' + ')}</small></td>
        <td>{estimate.basis}<small>{estimate.price?.id ?? 'No price'}</small></td></tr>; })}
    </tbody></table></div></details>}
    <PriceInformation />
  </section>;
}

/** Expose the bundled rates and their applicability beside the resulting estimate. */
export function PriceInformation() {
  return <details className="price-information"><summary>Pricing information · verified 2026-10-10</summary>
    {prices.map(price => <Card key={price.id}><Card.Header><Card.Title>{price.modelVersion}</Card.Title><Card.Description>{price.id}</Card.Description></Card.Header><Card.Content>
      <p>{price.currency} per {price.unit}: input {price.input}, cache read {price.cacheRead}, cache write {price.cacheWrite ?? 'no separate charge'}, output {price.output}.</p>
      <p>{price.rules}</p><p>Effective date: {price.effectiveFrom ?? 'not established; current-rate approximation'}. Verified {price.verified}.</p>
      <p>Original vendor: {price.vendor}. Source: <span>{price.source}</span></p>
    </Card.Content></Card>)}
    <p>Supporting rules: https://developers.openai.com/api/docs/guides/prompt-caching · https://developers.openai.com/api/docs/pricing</p>
  </details>;
}
