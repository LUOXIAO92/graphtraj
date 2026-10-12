import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import Markdown from 'react-markdown';
import type { Activity, ActivityEvent, Agent } from '../electron/activity';
import { ToolContent } from './ToolContent';
import { Avatar, Icon, Status } from './ui';

const readable = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

export function EventCard({ event }: { event: ActivityEvent }) {
  const [copied, setCopied] = useState('');
  const content = event.text ?? readable(event.result ?? event.arguments ?? event.usage) ?? '';
  const details = event.details === undefined ? '' : readable(event.details);
  const error = event.error ? readable(event.error) : '';
  const parts = event.kind === 'tool' ? event.content ?? [] : [];
  const rawResult = event.kind === 'tool' && event.result !== undefined ? readable(event.result) : '';
  const copyContent = [content, details, error].filter(Boolean).join('\n\n');
  const title = event.kind === 'tool' ? `Tool · ${event.name || 'Name not recorded'}`
    : event.role === 'reasoning' ? 'Reasoning' : event.kind === 'work' ? 'Execution event' : event.role || event.kind;
  const time = event.time === null ? 'Time not recorded' : new Date(event.time).toLocaleString();
  const copy = <button aria-label="Copy record" onClick={() => {
    void window.graphtraj.copyText(copyContent).then(() => setCopied('Copied'), () => setCopied('Copy unavailable'));
  }}><Icon name={copied === 'Copied' ? 'check' : 'copy'} size={14}/>{copied || 'Copy'}</button>;
  if (event.kind === 'usage') return null;
  if (event.kind === 'tool' || event.details) return <div className="tool-message activity-event"><time>{time}</time>
    <details className={`tool-card ${event.error ? 'tool-error' : ''}`}><summary><span className="tool-icon"><Icon name="terminal" size={16}/></span><span><strong>{title}</strong><small>{event.phase || event.kind} · {event.source.runtime}</small></span><span className="tool-result">{event.error ? 'Error' : event.phase || 'Recorded'}<Icon name={event.error ? 'info' : 'check'} size={13}/></span><Icon name="down" size={14}/></summary>
      <div className="tool-details">{parts.length ? <ToolContent parts={parts}/> : <pre>{content}</pre>}<details className="tool-technical"><summary>Technical details<Icon name="down" size={12}/></summary><dl><dt>Source</dt><dd title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</dd>{event.call_id && <><dt>Call ID</dt><dd>{event.call_id}</dd></>}{event.tool_type && <><dt>Record type</dt><dd>{event.tool_type}</dd></>}{rawResult && <><dt>Raw result</dt><dd><pre>{rawResult}</pre></dd></>}{details && <><dt>Record details</dt><dd><pre>{details}</pre></dd></>}{error && <><dt>Error flag</dt><dd><pre>{error}</pre></dd></>}</dl>{copy}</details></div></details></div>;
  return <article className="message activity-event"><div className="message-heading"><Avatar name={title}/><strong>{title}</strong><time>{time}</time></div><div className="message-body"><Markdown skipHtml components={{ a: ({ children }) => <span>{children}</span>, img: () => <span>[External image omitted]</span> }}>{content || 'No readable text in this record.'}</Markdown></div><div className="record-source">{copy}<span title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</span></div></article>;
}

/** Use recorded turn identity, or the exact native record for per-message usage. */
function scopeKey(event: ActivityEvent) {
  return JSON.stringify([event.agent, event.session, event.source.runtime, event.source.trace,
    event.turn_id == null ? ['record', event.source.offset] : ['turn', event.turn_id]]);
}

/** Supplement a recorded turn/response without summing native observations. */
function UsageSupplement({ events, agent, attached }: { events: ActivityEvent[]; agent: string; attached: boolean }) {
  const latest = events.at(-1)!;
  const tokens = latest.usage?.tokens;
  const scope = latest.turn_id != null ? `Recorded turn${attached ? '' : ' (content outside this page)'}`
    : attached ? 'Recorded response' : 'Response / turn association unavailable';
  return <footer className="usage-supplement" aria-label={`Usage for ${agent}`}>
    <details><summary>Usage · {agent} · {scope} · {latest.source.runtime} · {latest.usage?.scope === 'latest-response' ? 'Latest response observation' : 'Native usage observation'} · Input {tokens?.input ?? 'Unknown'} · Output {tokens?.output ?? 'Unknown'}</summary>
      {events.map(event => <div key={event.id} className="usage-observation">
        <p>{event.time == null ? 'Time not recorded' : new Date(event.time).toLocaleString()} · {event.source.runtime} · {event.usage?.phase} · {event.turn_id == null ? 'Turn ID not recorded' : `Turn ${event.turn_id}`}</p>
        <dl><dt>{event.usage?.scope === 'latest-response' ? 'Latest response (last_token_usage)' : 'Native reported usage'}</dt><dd><pre>{readable(event.usage?.provider_usage)}</pre></dd>
          <dt>Normalized tokens (missing fields remain unknown)</dt><dd><pre>{readable(event.usage?.tokens)}</pre></dd>
          {event.usage?.cumulative != null && <><dt>Cumulative native Session counter (total_token_usage; not this turn)</dt><dd><pre>{readable(event.usage.cumulative)}</pre></dd></>}
        </dl><p>{typeof event.usage?.coverage === 'string' ? event.usage.coverage : 'Recorded native fields; no model request count is inferred.'}</p>
        <small title={event.source.trace}>Source byte {event.source.offset}</small>
      </div>)}
    </details>
  </footer>;
}

/** Resolve tools over all loaded pages; keep usage below its recorded scope. */
export function ActivityRecords({ events, pageStart, agent }: { events: ActivityEvent[]; pageStart: number; agent: string }) {
  const names = new Map<string, string>();
  const toolKey = (event: ActivityEvent) => JSON.stringify([event.agent, event.session, event.source.runtime, event.source.trace, event.call_id]);
  const usage = new Map<string, Map<string, ActivityEvent>>();
  for (const event of events) {
    if (event.kind === 'tool' && event.call_id && event.name) names.set(toolKey(event), event.name);
    if (event.kind === 'usage') {
      const key = scopeKey(event);
      if (!usage.has(key)) usage.set(key, new Map());
      // Replayed observations keep one entry; distinct counters remain distinct.
      usage.get(key)!.set(`${event.usage?.identity || event.id}:${event.usage?.phase}`, event);
    }
  }
  const visible = events.slice(pageStart, pageStart + 100);
  const last = new Map<string, string>();
  for (const event of visible) if (event.kind !== 'usage') last.set(scopeKey(event), event.id);
  const unattached = new Set(visible.filter(event => event.kind === 'usage').map(scopeKey));
  for (const key of last.keys()) unattached.delete(key);
  return <>{visible.filter(event => event.kind !== 'usage').map(event => {
    const key = scopeKey(event);
    const facts = usage.get(key);
    const resolved = event.kind === 'tool' && event.call_id && !event.name ? { ...event, name: names.get(toolKey(event)) } : event;
    return <React.Fragment key={event.id}><EventCard event={resolved}/>
      {last.get(key) === event.id && facts && <UsageSupplement events={[...facts.values()]} agent={agent} attached/>}
    </React.Fragment>;
  })}{[...unattached].map(key => <UsageSupplement key={key} events={[...usage.get(key)!.values()]} agent={agent} attached={false}/>)}</>;
}

/** Show only members returned by the native activity projection. */
export function MemberPills({ agents, onRead, focus }: { agents: Agent[]; onRead: (alias: string) => void; focus?: string | null }) {
  return <div className="member-pills">{agents.map(agent => <button key={agent.alias} title={agent.alias} className={`${agent.historical ? 'history' : ''} ${focus === agent.alias ? 'selected' : ''}`} onClick={() => onRead(agent.alias)}><Avatar name={agent.alias} small/><span><strong>{agent.alias}</strong><small>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · {agent.runtime || 'Runtime unknown'}</small></span><Icon name="right" size={13}/></button>)}</div>;
}

/** Keep each actual member in its own independently scrolling column. */
export function ActivityView({ projectId, ticketId, active = true, expanded = true, focusAgent, onActivity, onError, refreshKey = 0 }: {
  projectId: string; ticketId?: string; active?: boolean; expanded?: boolean; focusAgent?: string | null; onActivity?: (activity: Activity) => void;
  onError?: (message: string) => void; refreshKey?: number;
}) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const columns = useRef<HTMLDivElement>(null);
  const horizontal = useRef(0);
  useLayoutEffect(() => {
    if (active && expanded && columns.current) columns.current.scrollLeft = horizontal.current;
  }, [active, expanded]);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      setLoading(true);
      try {
        const next = await window.graphtraj.activity(projectId, ticketId ? { ticket_id: ticketId } : {});
        if (!ticketId) next.agents = next.agents.filter(agent => agent.kind === 'main');
        if (alive) { setActivity(next); setError(next.reason || ''); onError?.(next.reason || ''); onActivity?.(next); }
      } catch {
        if (alive) {
          const message = ticketId ? 'Could not load this task’s Agent sessions. Retrying automatically.' : 'Could not load Main sessions for this project. Retrying automatically.';
          setError(message); onError?.(message);
        }
      }
      finally { if (alive) { setLoading(false); timer = setTimeout(refresh, 3000); } }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, active, retry, refreshKey]);
  const [scroll, setScroll] = useState({ left: 0, max: 0, thumb: 0 });
  function updateEdges() {
    const element = columns.current;
    if (element) setScroll({ left: element.scrollLeft, max: element.scrollWidth - element.clientWidth,
      thumb: Math.max(44, element.clientWidth * element.clientWidth / Math.max(1, element.scrollWidth)) });
  }
  useEffect(() => { const observer = new ResizeObserver(updateEdges); if (columns.current) observer.observe(columns.current); return () => observer.disconnect(); }, []);
  useEffect(() => { const element = columns.current; if (!element || !focusAgent) return;
    const target = [...element.querySelectorAll<HTMLElement>('[data-agent-id]')].find(item => item.dataset.agentId === focusAgent);
    if (target) element.scrollLeft = target.offsetLeft - element.offsetLeft;
    updateEdges();
  }, [focusAgent]);
  const move = (direction: number) => columns.current?.scrollBy({ left: direction * 440, behavior: 'instant' });
  return <section className="activity" aria-label="Agent activity">
    {activity?.scope === 'self' && <p className="native-notice">This Agent connection shows only its own Session.</p>}
    {error && <div className="native-notice error" role="alert">{error} <Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Retry now</Button></div>}
    {activity?.notices?.map(notice => <p className="native-notice" key={notice}>{notice}</p>)}
    {!activity?.agents.length && !error && <p className="native-notice" role="status">{activity ? ticketId ? 'No participating Agents recorded.' : 'No associated Main sessions recorded for this project.' : loading ? ticketId ? 'Loading Agent sessions…' : 'Loading Main sessions…' : 'Session list unavailable.'}</p>}
    <div className="agent-columns" ref={columns} tabIndex={0} aria-label="Agent columns" role="region"
      onKeyDown={event => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); } }}
      onScroll={event => { if (active && expanded) horizontal.current = event.currentTarget.scrollLeft; updateEdges(); }}>
      {activity?.agents.map(agent => <AgentColumn key={agent.alias} projectId={projectId} ticketId={ticketId} agent={agent} active={active && expanded}/>)}
    </div>
    <input className="agent-horizontal-scrollbar" type="range" min={0} max={Math.max(1, scroll.max)} step={1} value={Math.min(scroll.left, Math.max(1, scroll.max))} disabled={scroll.max < 1} aria-label="Agent columns horizontal scrollbar" style={{ '--scroll-thumb-width': `${scroll.thumb}px` } as React.CSSProperties} onChange={event => { if (columns.current) columns.current.scrollLeft = Number(event.target.value); updateEdges(); }}/>
    <footer className="columns-footer"><span><Icon name="left" size={13}/><Icon name="right" size={13}/>{activity ? `Drag the bottom scrollbar to see all ${activity.agents.length} agents · ${new Date(activity.updated_at).toLocaleTimeString()}` : error ? 'Session list unavailable' : 'Loading Session list…'}</span><div><Button isIconOnly variant="ghost" aria-label="Previous agent columns" isDisabled={scroll.left < 2} onPress={() => move(-1)}><Icon name="left" size={16}/></Button><Button isIconOnly variant="ghost" aria-label="Next agent columns" isDisabled={scroll.left >= scroll.max - 2} onPress={() => move(1)}><Icon name="right" size={16}/></Button></div></footer>
  </section>;
}

function AgentColumn({ projectId, ticketId, agent, active }: {
  projectId: string; ticketId?: string; agent: Agent; active: boolean;
}) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [following, setFollowing] = useState(true);
  const [pageStart, setPageStart] = useState(0);
  const [pending, setPending] = useState(0);
  const followingRef = useRef(true);
  const history = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const pointerReading = useRef(false);
  const touchY = useRef<number | null>(null);
  const vertical = useRef(0);
  useLayoutEffect(() => {
    if (active && history.current && !followingRef.current) history.current.scrollTop = vertical.current;
  }, [active]);
  const loadRequested = useRef(false);
  const cursor = useRef<string | undefined>(undefined);
  const more = useRef(false);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await window.graphtraj.activity(projectId, {
          ...(ticketId ? { ticket_id: ticketId } : {}), alias: agent.alias, ...(cursor.current ? { cursor: cursor.current } : {}),
        });
        if (!alive) return;
        if (next.availability === 'cursor-expired' || next.availability === 'trace-changed') {
          cursor.current = undefined; more.current = false;
          setError('Observer reconnected or Trace changed. Replaying recorded events; existing content is retained.');
        } else {
          setActivity(next); setError(next.reason || (next.availability === 'unavailable' ? 'This Session’s recorded messages are unavailable. Retry after its source is restored.' : ''));
          cursor.current = next.cursor ?? undefined;
          more.current = Boolean(next.has_more && !next.waiting_for_record);
          const added = (next.events ?? []).filter(event => !seen.current.has(event.id));
          added.forEach(event => seen.current.add(event.id));
          if (added.length) {
            setEvents(previous => [...previous, ...added]);
            if (followingRef.current) setPageStart(Math.max(0, seen.current.size - 100));
            else setPending(value => value + added.length);
          }
        }
      } catch {
        if (alive) setError(seen.current.size
          ? 'Activity disconnected or access refused. Retrying; retained messages remain readable.'
          : 'Could not load this Session’s messages. Access may be unavailable. Retrying automatically.');
      } finally { if (alive) timer = setTimeout(tick, more.current && followingRef.current ? 0 : 3000); }
    }
    function tick() {
      if (more.current && !followingRef.current && !loadRequested.current) {
        timer = setTimeout(tick, 3000);
      } else { loadRequested.current = false; void refresh(); }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, agent.alias, active, retry]);

  useLayoutEffect(() => {
    if (active && following && history.current) history.current.scrollTop = history.current.scrollHeight;
  }, [events, pageStart, following, active]);

  useLayoutEffect(() => {
    if (!active) return;
    const observer = new ResizeObserver(() => {
      if (followingRef.current && history.current) history.current.scrollTop = history.current.scrollHeight;
    });
    if (content.current) observer.observe(content.current);
    if (history.current) observer.observe(history.current);
    return () => observer.disconnect();
  }, [active]);

  function follow(value: boolean) {
    followingRef.current = value; setFollowing(value);
    if (value) { setPageStart(Math.max(0, events.length - 100)); setPending(0); }
  }

  return <article className={`agent-chat-column agent-column ${agent.historical ? 'historical-column' : ''}`} data-agent-id={agent.alias} aria-label={agent.alias}>
    <header className="agent-column-heading"><Avatar name={agent.alias}/><div><h2 title={agent.alias}>{agent.kind === 'main' ? 'Main' : agent.alias}</h2><span>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · {agent.state}</span></div><Status value={agent.state}/></header>
    <div className="agent-column-parent"><Icon name="branch" size={13}/><span title={agent.parent ?? undefined}>{agent.kind === 'main' ? `Session: ${agent.session}` : `Parent: ${agent.parent ?? 'Not recorded / root'}`}</span></div>
    <div className="conversation-panel"><div className="agent-metadata"><span><Icon name="terminal" size={14}/>{agent.runtime || 'Runtime unknown'}</span><span>{agent.model || 'Model not recorded'}</span></div>
      {error && <div className="native-notice error" role="alert">{error} <Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Retry now</Button></div>}
      {agent.reason && <p className="native-notice">{agent.reason}</p>}
      <div className="transcript activity-history" ref={history} tabIndex={0} aria-label={`${agent.alias} messages`} role="region" style={{ overflowAnchor: following ? 'none' : 'auto' }}
        onWheel={event => { if (active && event.deltaY < 0) follow(false); }}
        onKeyDown={event => { if (active && event.target === event.currentTarget && (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || event.key === ' ' && event.shiftKey)) follow(false); }}
        onPointerDown={() => { pointerReading.current = true; }}
        onPointerUp={() => { pointerReading.current = false; }}
        onPointerCancel={() => { pointerReading.current = false; }}
        onPointerLeave={() => { pointerReading.current = false; }}
        onTouchStart={event => { touchY.current = event.touches[0]?.clientY ?? null; }}
        onTouchMove={event => { const y = event.touches[0]?.clientY; if (active && y != null && touchY.current != null && y > touchY.current) follow(false); touchY.current = y ?? null; }}
        onScroll={event => {
          const element = event.currentTarget;
          // Scroll events also come from anchoring, resizing and our own follow.
          // Only an upward input/scrollbar gesture changes the reading mode.
          if (active && pointerReading.current && element.scrollTop < vertical.current && element.scrollHeight - element.clientHeight - element.scrollTop > 32) follow(false);
          if (active) vertical.current = element.scrollTop;
        }}><div ref={content}><div className="day-divider"><span>Recorded Runtime output</span></div>
        <ActivityRecords events={events} pageStart={pageStart} agent={agent.alias}/>
        {!events.length && !error && <p>{!activity ? 'Loading Session messages…' : activity.availability === 'available' ? 'No readable activity recorded yet.' : activity.reason || 'Session messages unavailable.'}</p>}
        <div className="transcript-end">{events.length} events loaded · Missing usage stays unknown.</div>
      </div></div>
      <div className="reading-toolbar"><button className={following ? 'following' : ''} onClick={() => follow(!following)}><Icon name={following ? 'pause' : 'play'} size={14}/>{following ? 'Pause following' : `Follow new messages${pending ? ` (${pending})` : ''}`}</button><button disabled={pageStart === 0} onClick={() => { follow(false); setPageStart(value => Math.max(0, value - 100)); }}>Earlier</button><button disabled={pageStart + 100 >= events.length} onClick={() => { follow(false); setPageStart(value => value + 100); }}>Later</button>{activity?.has_more && !activity.waiting_for_record && <button onClick={() => { loadRequested.current = true; }}>Load next recorded page</button>}</div>
    </div></article>;
}
