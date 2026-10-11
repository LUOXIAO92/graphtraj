import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import Markdown from 'react-markdown';
import type { Activity, ActivityEvent, Agent } from '../electron/activity';
import { Avatar, Icon, Status } from './ui';

const readable = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

export function EventCard({ event }: { event: ActivityEvent }) {
  const [copied, setCopied] = useState('');
  const content = event.text ?? readable(event.result ?? event.arguments ?? event.usage) ?? '';
  const details = event.details === undefined ? '' : readable(event.details);
  const error = event.error ? readable(event.error) : '';
  const copyContent = [content, details, error].filter(Boolean).join('\n\n');
  const title = event.kind === 'tool' ? event.name || event.call_id || 'Tool' : event.role || event.kind;
  const time = event.time === null ? 'Time not recorded' : new Date(event.time).toLocaleString();
  const copy = <button aria-label="Copy record" onClick={() => {
    void window.graphtraj.copyText(copyContent).then(() => setCopied('Copied'), () => setCopied('Copy unavailable'));
  }}><Icon name={copied === 'Copied' ? 'check' : 'copy'} size={14}/>{copied || 'Copy'}</button>;
  if (event.kind === 'tool' || event.kind === 'usage' || event.details) return <div className="tool-message activity-event"><time>{time}</time>
    <details className={`tool-card ${event.error ? 'tool-error' : ''}`}><summary><span className="tool-icon"><Icon name="terminal" size={16}/></span><span><strong>{title}</strong><small>{event.phase || event.kind} · {event.source.runtime}</small></span><span className="tool-result">{event.error ? 'Error' : event.phase || 'Recorded'}<Icon name={event.error ? 'info' : 'check'} size={13}/></span><Icon name="down" size={14}/></summary>
      <div className="tool-details"><dl><dt>Source</dt><dd title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</dd></dl><pre>{content}</pre>{details && <pre>{details}</pre>}{error && <pre>{error}</pre>}{copy}</div></details></div>;
  return <article className="message activity-event"><div className="message-heading"><Avatar name={title}/><strong>{title}</strong><time>{time}</time></div><div className="message-body"><Markdown skipHtml components={{ a: ({ children }) => <span>{children}</span>, img: () => <span>[External image omitted]</span> }}>{content || 'No readable text in this record.'}</Markdown></div><div className="record-source">{copy}<span title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</span></div></article>;
}

/** Show only members returned by the native activity projection. */
export function MemberPills({ agents, onRead, focus }: { agents: Agent[]; onRead: (alias: string) => void; focus?: string | null }) {
  return <div className="member-pills">{agents.map(agent => <button key={agent.alias} title={agent.alias} className={`${agent.historical ? 'history' : ''} ${focus === agent.alias ? 'selected' : ''}`} onClick={() => onRead(agent.alias)}><Avatar name={agent.alias} small/><span><strong>{agent.alias}</strong><small>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · {agent.runtime || 'Runtime unknown'}</small></span><Icon name="right" size={13}/></button>)}</div>;
}

/** Keep each actual member in its own independently scrolling column. */
export function ActivityView({ projectId, ticketId, active = true, expanded = true, focusAgent, onActivity }: {
  projectId: string; ticketId?: string; active?: boolean; expanded?: boolean; focusAgent?: string | null; onActivity?: (activity: Activity) => void;
}) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState('');
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
      try {
        const next = await window.graphtraj.activity(projectId, ticketId ? { ticket_id: ticketId } : {});
        if (!ticketId) next.agents = next.agents.filter(agent => agent.kind === 'main');
        if (alive) { setActivity(next); setError(next.reason || ''); onActivity?.(next); }
      } catch { if (alive) setError('Member status disconnected; retained content remains readable.'); }
      finally { if (alive) timer = setTimeout(refresh, 3000); }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, active]);
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
    {error && <p className="native-notice error" role="alert">{error}</p>}
    {activity?.notices?.map(notice => <p className="native-notice" key={notice}>{notice}</p>)}
    {!activity?.agents.length && <p className="native-notice">{activity ? 'No participating Agents recorded.' : 'Loading members…'}</p>}
    <div className="agent-columns" ref={columns} tabIndex={0} aria-label="Agent columns" role="region"
      onKeyDown={event => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); } }}
      onScroll={event => { if (active && expanded) horizontal.current = event.currentTarget.scrollLeft; updateEdges(); }}>
      {activity?.agents.map(agent => <AgentColumn key={agent.alias} projectId={projectId} ticketId={ticketId} agent={agent} active={active && expanded}/>)}
    </div>
    <input className="agent-horizontal-scrollbar" type="range" min={0} max={Math.max(1, scroll.max)} step={1} value={Math.min(scroll.left, Math.max(1, scroll.max))} disabled={scroll.max < 1} aria-label="Agent columns horizontal scrollbar" style={{ '--scroll-thumb-width': `${scroll.thumb}px` } as React.CSSProperties} onChange={event => { if (columns.current) columns.current.scrollLeft = Number(event.target.value); updateEdges(); }}/>
    <footer className="columns-footer"><span><Icon name="left" size={13}/><Icon name="right" size={13}/>Drag the bottom scrollbar to see all {activity?.agents.length ?? 0} agents · {activity ? new Date(activity.updated_at).toLocaleTimeString() : 'Loading'}</span><div><Button isIconOnly variant="ghost" aria-label="Previous agent columns" isDisabled={scroll.left < 2} onPress={() => move(-1)}><Icon name="left" size={16}/></Button><Button isIconOnly variant="ghost" aria-label="Next agent columns" isDisabled={scroll.left >= scroll.max - 2} onPress={() => move(1)}><Icon name="right" size={16}/></Button></div></footer>
  </section>;
}

function AgentColumn({ projectId, ticketId, agent, active }: {
  projectId: string; ticketId?: string; agent: Agent; active: boolean;
}) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState('');
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [following, setFollowing] = useState(true);
  const [pageStart, setPageStart] = useState(0);
  const [pending, setPending] = useState(0);
  const followingRef = useRef(true);
  const history = useRef<HTMLDivElement>(null);
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
          setActivity(next); setError(next.reason || '');
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
        if (alive) setError('Activity disconnected or access refused. Retrying; retained messages remain readable.');
      } finally { if (alive) timer = setTimeout(tick, more.current && followingRef.current ? 0 : 3000); }
    }
    function tick() {
      if (more.current && !followingRef.current && !loadRequested.current) {
        timer = setTimeout(tick, 3000);
      } else { loadRequested.current = false; void refresh(); }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, agent.alias, active]);

  useEffect(() => {
    if (active && following && history.current) history.current.scrollTop = history.current.scrollHeight;
  }, [events, following, active]);

  function follow(value: boolean) {
    followingRef.current = value; setFollowing(value);
    if (value) { setPageStart(Math.max(0, events.length - 100)); setPending(0); }
  }

  return <article className={`agent-chat-column agent-column ${agent.historical ? 'historical-column' : ''}`} data-agent-id={agent.alias} aria-label={agent.alias}>
    <header className="agent-column-heading"><Avatar name={agent.alias}/><div><h2 title={agent.alias}>{agent.kind === 'main' ? 'Main' : agent.alias}</h2><span>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · {agent.state}</span></div><Status value={agent.state}/></header>
    <div className="agent-column-parent"><Icon name="branch" size={13}/><span title={agent.parent ?? undefined}>{agent.kind === 'main' ? `Session: ${agent.session}` : `Parent: ${agent.parent ?? 'Not recorded / root'}`}</span></div>
    <div className="conversation-panel"><div className="agent-metadata"><span><Icon name="terminal" size={14}/>{agent.runtime || 'Runtime unknown'}</span><span>{agent.model || 'Model not recorded'}</span></div>
      {error && <p className="native-notice error" role="alert">{error}</p>}
      {agent.reason && <p className="native-notice">{agent.reason}</p>}
      <div className="transcript activity-history" ref={history} tabIndex={0} aria-label={`${agent.alias} messages`} role="region" onScroll={event => {
        const element = event.currentTarget; if (active) vertical.current = element.scrollTop;
        if (active && followingRef.current && element.scrollHeight - element.clientHeight - element.scrollTop > 32) follow(false);
      }}><div className="day-divider"><span>Recorded Runtime output</span></div>
        {events.slice(pageStart, pageStart + 100).map(event => <EventCard key={event.id} event={event}/>)}
        {!events.length && <p>{activity?.availability === 'available' ? 'No readable activity recorded yet.' : 'Activity is unavailable or loading.'}</p>}
        <div className="transcript-end">{events.length} events loaded · Missing usage stays unknown.</div>
      </div>
      <div className="reading-toolbar"><button className={following ? 'following' : ''} onClick={() => follow(!following)}><Icon name={following ? 'pause' : 'play'} size={14}/>{following ? 'Pause following' : `Follow new messages${pending ? ` (${pending})` : ''}`}</button><button disabled={pageStart === 0} onClick={() => { follow(false); setPageStart(value => Math.max(0, value - 100)); }}>Earlier</button><button disabled={pageStart + 100 >= events.length} onClick={() => { follow(false); setPageStart(value => value + 100); }}>Later</button>{activity?.has_more && !activity.waiting_for_record && <button onClick={() => { loadRequested.current = true; }}>Load next recorded page</button>}</div>
    </div></article>;
}
