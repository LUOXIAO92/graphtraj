import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card } from '@heroui/react';
import type { Project } from '../electron/types';
import { defaultDates, localDate, cost, groups, records, summarize, aliasRole, compactNumber, headMoney, money, type Call, type Filters } from './usage.ts';
import { prices } from './prices.ts';
import { Dialog, Icon, StateMessage } from './ui';

/** Query backend-owned history; UI filters never limit collection or write usage facts. */
export function UsageView({ projectId, projects = [] }: { projectId?: string; projects?: Project[] }) {
  const [ratesOpen, setRatesOpen] = useState(false);
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
      await Promise.all((JSON.parse(selection) as string[]).map(async id => {
        try {
          const page = await window.graphtraj.usage(id);
          if (!alive) return;
          for (const [key, call] of retained) if (call.project === id) retained.delete(key);
          for (const call of page.calls) retained.set(call.key, call);
          setCalls(new Map(retained));
          const name = projects.find(project => project.id === id)?.root;
          notices.push(...page.notices.map(notice => global && name ? `${name}: ${notice}` : notice));
          pending ||= page.pending;
        } catch { notices.push('Usage history could not be read or saved. Showing the last successful read; retrying.'); }
      }));
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
  const trend = groups(rows, 'day');
  const comparison = projects.map(project => ({
    name: project.root, ...summarize(rows.filter(row => row.project === project.id)),
  }));
  const knownDays = all.flatMap(row => row.time ? [localDate(new Date(row.time))] : []).sort();
  const invalidRange = !filters.from || !filters.to || filters.from > filters.to;
  const patch = (key: keyof Filters, value: string) => setFilters(old => ({ ...old, [key]: value }));
  const dates = { from: filters.from ?? '', to: filters.to ?? '' };
  const periodRows = invalidRange ? [] : records(calls, { ...dates, task: filters.task, agent: filters.agent });
  const periodTotal = summarize(periodRows);
  const display = (value: { known: number; value: number }) => value.known ? compactNumber(value.value) : 'Unknown';
  const hasRows = rows.length > 0 && !invalidRange;
  // V9: metric cards, cost first. U3: the head cost has two decimals; the full value is in its title
  // and in the Call arithmetic. Missing values stay Unknown / Unpriced, never 0.
  const costCard = <div className="new-cost usage-kpi usage-kpi-lead"><span>Official-price equivalent · reported estimate</span>
    <strong data-usage-cost title={!invalidRange && total.priced ? `${money(total.amount)} USD` : undefined}>{invalidRange ? '—' : !rows.length ? 'No data' : total.priced ? headMoney(total.amount) : 'Unknown'}{total.priced > 0 && !invalidRange && <small>USD</small>}</strong>
    <small>{invalidRange ? 'Totals are withheld until the dates are valid.' : `${total.priced} / ${rows.length} selected reports can be priced`}</small></div>;
  const totals = <div className="new-usage-totals">{(['input','output','cache_read'] as const).map((key,index) => <span key={key} className="usage-kpi"><small>{['Input · includes cache','Output','Cache read'][index]}</small><strong>{display(total.tokens[key])}</strong><small>{total.tokens[key].known} / {total.count} reports include this field</small></span>)}<span className="usage-kpi"><small>Known input hit rate</small><strong>{total.cacheRate === null ? 'Unknown' : (total.cacheRate * 100).toFixed(1) + '%'}</strong><small>Weighted; unknown cache excluded</small></span></div>;
  // V10: one empty-state presentation; the dashboard's only status role stays the observation line.
  const empty = <StateMessage kind={invalidRange ? 'error' : loading ? 'loading' : 'empty'} layout="block" role={null} className="d-usage-empty"
    title={invalidRange ? 'Choose a valid date range' : loading ? 'Loading usage history…' : !all.length ? 'No retained usage report' : 'No dated usage in this view'}>
    <p>{invalidRange ? 'Choose both dates with the start on or before the end. No totals are shown for an invalid range.' : 'No reports match these dates and filters. Input, output, cache and cost remain unknown; absence of reports does not establish zero usage.'}</p></StateMessage>;
  const trendHeading = (label: string) => <div className="d-history-chart-heading"><h2>Input over time</h2><span className="usage-legend"><span><i className="legend-input"/>Input</span><span><i className="legend-cache"/>of which cache read</span><span><i className="legend-gap"/>No report (not zero)</span><span>{label}</span></span></div>;
  return <section className={`new-usage d-dated-usage usage-dashboard ${global ? 'd-global-usage' : 'd-project-usage'}`} aria-label="Usage dashboard">
    <header className="new-section-heading"><div><h1>{global ? 'Usage across projects' : 'Project usage'}</h1><p>{global ? `${projects.length} indexed projects · compare available history` : 'Retained usage in this project only'}</p></div>{!global && <button className="d-rate-reference" onClick={() => setRatesOpen(true)}>Rate reference</button>}</header>
    <div className="d-usage-date-controls usage-filters"><label>Start date<input type="date" aria-invalid={invalidRange} value={filters.from ?? ''} onChange={event => patch('from',event.target.value)}/></label><label>End date<input type="date" aria-invalid={invalidRange} value={filters.to ?? ''} onChange={event => patch('to',event.target.value)}/></label><Button variant="secondary" onPress={() => setFilters(defaultDates())}>Last 7 days</Button>{!global && <div className="d-project-usage-filters"><label>Task<select value={filters.task ?? ''} onChange={event => patch('task',event.target.value)}><option value="">All tasks</option>{[...new Set(all.map(row => row.task).filter(Boolean))].sort().map(task => <option key={task} value={task}>#{task}</option>)}</select></label><label>Agent<select value={filters.agent ?? ''} onChange={event => patch('agent',event.target.value)}><option value="">All Agents</option>{[...new Set(all.map(row => row.agent))].sort().map(agent => <option key={agent}>{agent}</option>)}</select></label></div>}</div>
    <p className={`d-usage-date-note ${invalidRange ? 'has-error' : ''}`} role={invalidRange ? 'alert' : undefined}>{invalidRange ? 'Choose both dates with the start on or before the end. No totals are shown for an invalid range.' : `${filters.from} → ${filters.to} · Both dates included · Local calendar days`}</p>
    <div className="usage-kpis">{costCard}{hasRows && totals}</div>
    {global ? <div className="d-global-usage-body">{hasRows ? <><div className="d-history-chart-heading"><h2>Project comparison</h2><span>Selected dates only</span></div><table className="d-project-usage-table" aria-label="Project comparison"><thead><tr><th>Project</th><th>Input</th><th>Output</th><th>Cache read</th><th>Est. USD</th></tr></thead><tbody>{comparison.map(item => <tr key={item.name}><th scope="row"><span className="project-avatar">{item.name.split(/[\\/]/).at(-1)?.slice(0,2)}</span><span title={item.name}><strong>{item.name.split(/[\\/]/).at(-1)}</strong><small>{item.count} dated reports</small></span></th>{(['input','output','cache_read'] as const).map(key => <td key={key}>{display(item.tokens[key])}{item.tokens[key].known < item.count && <small>Partial</small>}</td>)}<td>{item.priced ? money(item.amount) : 'Unknown'}{item.priced < item.count && <small>Partial estimate</small>}</td></tr>)}</tbody></table><div className="usage-panel">{trendHeading('Indexed projects with dated reports')}<DHistoryTrend trend={trend} {...dates}/></div></> : empty}</div>
      : <div className="d-usage-layout"><aside className="d-model-list"><span className="section-label">MODELS IN THIS PROJECT</span>{['', ...new Set(all.map(row => row.model))].map(model => { const value = summarize(periodRows.filter(row => !model || row.model === model)); const share = value.priced && periodTotal.amount > 0 ? Math.min(100, value.amount / periodTotal.amount * 100) : null; return <button key={model} className={(filters.model ?? '') === model ? 'selected' : ''} aria-pressed={(filters.model ?? '') === model} onClick={() => patch('model',model)}><span>{model || 'All models'}</span><strong className={value.count && !value.priced ? 'unpriced' : ''}>{!value.count ? 'No data' : value.priced ? money(value.amount) : 'Unpriced'}</strong>{share !== null && <i aria-hidden="true" style={{ '--share': `${share}%` } as React.CSSProperties}/>}<small>{value.count} reports in the selected dates</small></button>; })}</aside>
        <div className="d-usage-chart">{hasRows ? <><div className="usage-panel">{trendHeading(filters.model || 'All models')}<DHistoryTrend trend={trend} {...dates}/></div>
          <div className="usage-panel"><div className="d-history-chart-heading"><h2>Reports in this project</h2><span>{rows.length} records</span></div>
            <table className="d-dated-records" aria-label="Reports in this project"><thead><tr><th scope="col">Date</th><th scope="col">Agent</th><th scope="col">Task</th><th scope="col">Model</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Est. USD</th></tr></thead>
              <tbody>{rows.map(row => { const estimate = cost(row); return <tr key={row.key}><td><time dateTime={row.time ?? undefined}>{row.time ? localDate(new Date(row.time)) : 'Unknown time'}</time></td><td title={row.agent}>{row.agent.startsWith('Main:') ? 'Main' : aliasRole(row.agent)}</td><td className={row.task ? '' : 'mono'} title={row.task ? undefined : row.session}>{row.task ? `#${row.task}` : row.session}</td><td>{row.model}</td><td>{row.tokens.input === undefined ? 'Unknown' : compactNumber(row.tokens.input)}</td><td>{row.tokens.output === undefined ? 'Unknown' : compactNumber(row.tokens.output)}</td><td className={estimate.amount === null ? 'unpriced' : ''} title={estimate.reason ?? estimate.basis}>{estimate.amount === null ? 'Unpriced' : money(estimate.amount)}</td></tr>; })}</tbody></table></div></> : empty}</div></div>}
    {/* V9: the footer is one line (first sentence and observation status); the rest stays under 'About this usage history'. */}
    <footer className="d-usage-history-note"><div className="usage-note-line"><Icon name="info" size={14}/><span>Missing usage, prices and cache writes stay unknown; partial totals include reported fields only.</span><span role="status">{loading ? 'Loading history…' : 'Observation active'} · Last update {updated || 'not yet available'}</span></div><details><summary>About this usage history</summary><p>History is saved under HOME/.graphtraj. Native records are backfilled while viewing usage. Recorded dates: {knownDays.length ? `${knownDays[0]} through ${knownDays.at(-1)}` : 'none'}. Dates without reports are not zero consumption.</p><p>{total.unidentified} records excluded without call identity/ownership · {total.unpriced} unpriced · {total.approximated} current-rate approximations. Main calls with verified native project attribution are included; unassociated history is not covered. {all.filter(row => !row.time).length} records have unknown time and are excluded by date filters.</p><p>{total.counterObservations} Codex cumulative observations use counter differences to avoid duplication. Initial earlier counter history is not attributed to this model. Cache writes: {display(total.tokens.cache_write)}.</p><p>Equivalent token estimate, not a provider bill. Standard-tier equivalent for OpenAI; third-party routing charges are not inferred.</p>{coverage.map(value => <p className="usage-coverage" key={value}>{value}</p>)}<Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Reconnect usage</Button><PriceInformation/>{!global && <details><summary>Call arithmetic and unpriced reasons</summary>{rows.map(row => { const estimate = cost(row); return <p key={row.key}>{row.model} · {estimate.amount === null ? estimate.reason : money(estimate.amount)} · {estimate.basis} · {Object.entries(estimate.parts).map(([key,value]) => `${key} ${money(value)}`).join(' + ')}<br/>Session {row.session} · {row.source?.trace ? `${row.source.trace} · byte ${row.source.offset}` : 'Source path was not retained in this older report.'}{row.source?.event_id && <><br/>Source record {row.source.event_id}</>}</p>; })}</details>}</details></footer>
    {ratesOpen && <Dialog title="Rate reference" onClose={() => setRatesOpen(false)}><PriceInformation/></Dialog>}
  </section>;
}

/** Calendar days from one local date to another, inclusive (date strings only). */
function calendarDays(from: string, to: string) {
  const days: string[] = [];
  for (let time = Date.parse(`${from}T00:00:00Z`), end = Date.parse(`${to}T00:00:00Z`); time <= end && days.length < 400; time += 86400000) days.push(new Date(time).toISOString().slice(0, 10));
  return days;
}

/** Plot actual dated reports on D's calendar axis; dates without a report are hollow markers, never zero. */
function DHistoryTrend({ trend, from, to }: { trend: ReturnType<typeof groups>; from: string; to: string }) {
  if (trend.every(point => !point.tokens.input.known)) return <div className="d-history-trend-unavailable">Input trend unavailable: none of these reports includes input tokens.</div>;
  const max = Math.max(1, ...trend.map(point => point.tokens.input.value));
  const day = (date: string) => Date.parse(`${date}T00:00:00Z`);
  const span = day(to) - day(from);
  const x = (date: string) => span ? 82 + (day(date) - day(from)) / span * 690 : 427;
  const days = calendarDays(from, to);
  const reported = new Set(trend.map(point => point.name));
  // Date axis: every day up to two weeks, otherwise about seven evenly spaced labels including both ends.
  const step = days.length <= 14 ? 1 : Math.ceil((days.length - 1) / 6);
  const ticks = days.filter((_, index) => index % step === 0 || index === days.length - 1);
  return <div className="trend-chart d-history-trend"><svg viewBox="0 0 825 255" role="img" aria-label={`Reported input by date, ${from} to ${to}. Dates without reports are not zero.`}>{[0,1,2,3].map(index => <g key={index}><line x1="65" x2="790" y1={42 + index * 53} y2={42 + index * 53} className={index === 3 ? 'chart-baseline' : 'chart-grid'}/><text x="52" y={46 + index * 53} textAnchor="end">{compactNumber(max * (1 - index / 3))}</text></g>)}
    {days.length <= 62 && days.filter(date => !reported.has(date)).map(date => <circle key={`gap-${date}`} className="chart-gap" cx={x(date)} cy="194" r="6"/>)}
    {trend.map(point => { const height = point.tokens.input.value / max * 159; return <g key={point.name}><title>{point.name}: {point.tokens.input.known ? point.tokens.input.value.toLocaleString() : 'Unknown'} input tokens</title>{point.tokens.input.known ? <><rect x={x(point.name) - 12} y={201 - height} width="24" height={height} rx="3" className="chart-bar-input"/>{point.tokens.cache_read.known > 0 && <rect x={x(point.name) - 12} y={201 - point.tokens.cache_read.value / max * 159} width="24" height={point.tokens.cache_read.value / max * 159} rx="3" className="chart-bar-cache"/>}</> : <circle cx={x(point.name)} cy="194" r="6" className="chart-gap"/>}</g>; })}
    {span ? ticks.map((date, index) => <text key={date} x={x(date)} y="228" textAnchor={index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle'}>{date.slice(5)}</text>) : <text x="427" y="228" textAnchor="middle">{from}</text>}</svg></div>;
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
