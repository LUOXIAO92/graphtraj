import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button, Card } from '@heroui/react';
import Markdown from 'react-markdown';
import type { Activity, ActivityEvent, Agent } from '../electron/activity';
import './activity.css';

const readable = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

export function EventCard({ event }: { event: ActivityEvent }) {
  const [copied, setCopied] = useState('');
  const content = event.text ?? readable(event.result ?? event.arguments ?? event.usage) ?? '';
  const details = event.details === undefined ? '' : readable(event.details);
  const error = event.error ? readable(event.error) : '';
  const copyContent = [content, details, error].filter(Boolean).join('\n\n');
  return <Card className="activity-event">
    <Card.Header><Card.Title>{event.kind === 'tool' ? event.name || event.call_id || 'Tool' : event.role || event.kind}</Card.Title>
      <Card.Description>{event.time === null ? 'Time not recorded' : new Date(event.time).toLocaleString()}
        {' · '}<span title={event.source.trace}>{event.source.runtime} byte {event.source.offset}</span>{event.phase && ` · ${event.phase}`}
        {event.error ? ' · Error' : ''}</Card.Description></Card.Header>
    <Card.Content>
      {event.kind === 'tool' && <p>{content.split('\n')[0].slice(0, 160)}</p>}
      {event.kind === 'tool' || event.kind === 'usage' || event.details ? <details>
        <summary>{event.kind === 'usage' ? 'Recorded usage' : event.phase === 'call' ? 'Arguments / command' : 'Result / details'}</summary>
        <pre>{content}</pre>{details && <pre>{details}</pre>}{error && <pre>{error}</pre>}
      </details> : <Markdown skipHtml components={{ a: ({ children }) => <span>{children}</span>,
        img: () => <span>[External image omitted]</span> }}>{content || 'No readable text in this record.'}</Markdown>}
      <Button size="sm" variant="ghost" onPress={() => {
        void window.graphtraj.copyText(copyContent).then(() => setCopied('Copied'), () => setCopied('Copy unavailable'));
      }}>{copied || 'Copy'}</Button>
    </Card.Content>
  </Card>;
}

/** Keep each actual member in its own independently scrolling column. */
export function ActivityView({ projectId, ticketId, active = true, expanded = true }: {
  projectId: string; ticketId: string; active?: boolean; expanded?: boolean;
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
        const next = await window.graphtraj.activity(projectId, { ticket_id: ticketId });
        if (alive) { setActivity(next); setError(next.reason || ''); }
      } catch { if (alive) setError('Member status disconnected; retained content remains readable.'); }
      finally { if (alive) timer = setTimeout(refresh, 3000); }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, active]);
  return <section className="activity" aria-label="Agent activity">
    {activity?.scope === 'self' && <p className="note">This Agent connection shows only its own Session.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <p className="note">{activity ? `Last update ${new Date(activity.updated_at).toLocaleTimeString()}` : 'Loading members…'} · Chat · Read only</p>
    {activity?.agents.length === 0 && <p>No participating Agents recorded.</p>}
    {!expanded && <div className="agent-roster" aria-label="Participating Agents">{activity?.agents.map(agent =>
      <div className="roster-member" key={agent.alias}><strong>{agent.alias}</strong>
        <span>{agent.historical ? 'Historical' : 'Current'} · {agent.state}</span>
        <span>{agent.runtime || 'Runtime unknown'} · {agent.model || 'Model not recorded'}</span>
      </div>)}</div>}
    <div className="agent-columns" hidden={!expanded} ref={columns} tabIndex={0} aria-label="Agent columns"
      onScroll={event => { if (active && expanded) horizontal.current = event.currentTarget.scrollLeft; }}>
      {activity?.agents.map(agent => <AgentColumn key={agent.alias} projectId={projectId}
        ticketId={ticketId} agent={agent} active={active && expanded} />)}
    </div>
  </section>;
}

function AgentColumn({ projectId, ticketId, agent, active }: {
  projectId: string; ticketId: string; agent: Agent; active: boolean;
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
          ticket_id: ticketId, alias: agent.alias, ...(cursor.current ? { cursor: cursor.current } : {}),
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

  return <article className="agent-column" aria-label={agent.alias}>
    <header className="activity-member"><h3>{agent.alias}</h3>
      <span className="status">{agent.historical ? 'Historical' : 'Current'} · {agent.state}</span>
      <p>{agent.runtime || 'Runtime unknown'} · {agent.model || 'Model not recorded'}
        {agent.last_outcome && ` · ${agent.last_outcome}`}<br />Parent: {agent.parent ?? 'Not recorded / root'}
        {agent.reason && <><br />{agent.reason}</>}</p>
    </header>
    <div className="activity-controls">
      <Button size="sm" variant="secondary" onPress={() => follow(!following)}>{following ? 'Pause following' : `Follow new messages${pending ? ` (${pending})` : ''}`}</Button>
      <Button size="sm" variant="ghost" isDisabled={pageStart === 0} onPress={() => { follow(false); setPageStart(value => Math.max(0, value - 100)); }}>Earlier</Button>
      <Button size="sm" variant="ghost" isDisabled={pageStart + 100 >= events.length} onPress={() => { follow(false); setPageStart(value => value + 100); }}>Later</Button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="activity-history" ref={history} tabIndex={0} aria-label={`${agent.alias} messages`}
      onScroll={event => {
        const element = event.currentTarget;
        if (active) vertical.current = element.scrollTop;
        if (active && followingRef.current && element.scrollHeight - element.clientHeight - element.scrollTop > 32) follow(false);
      }}>
      {events.slice(pageStart, pageStart + 100).map(event => <EventCard key={event.id} event={event} />)}
      {!events.length && <p>{activity?.availability === 'available' ? 'No readable activity recorded yet.' : 'Activity is unavailable or loading.'}</p>}
    </div>
    {activity?.has_more && !activity.waiting_for_record && <Button size="sm" variant="secondary" onPress={() => { loadRequested.current = true; }}>Load next recorded page</Button>}
    <p className="note">{events.length} events loaded · Missing usage stays unknown.</p>
  </article>;
}
