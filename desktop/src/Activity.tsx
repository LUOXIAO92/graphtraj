import React, { useEffect, useRef, useState } from 'react';
import { Button, Card } from '@heroui/react';
import Markdown from 'react-markdown';
import type { Activity, ActivityEvent } from '../electron/activity';
import './activity.css';

const readable = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

function EventCard({ event }: { event: ActivityEvent }) {
  const [copied, setCopied] = useState('');
  const content = event.text ?? readable(event.result ?? event.arguments ?? event.details ?? event.usage) ?? '';
  return <Card className="activity-event">
    <Card.Header><Card.Title>{event.kind === 'tool' ? event.name || event.call_id || 'Tool' : event.role || event.kind}</Card.Title>
      <Card.Description>{event.time === null ? 'Time not recorded' : new Date(event.time).toLocaleString()}
        {' · '}<span title={event.source.trace}>{event.source.runtime} byte {event.source.offset}</span>{event.phase && ` · ${event.phase}`}
        {event.error ? ' · Error' : ''}</Card.Description></Card.Header>
    <Card.Content>
      {event.kind === 'tool' && <p>{content.split('\n')[0].slice(0, 160)}</p>}
      {event.kind === 'tool' || event.kind === 'usage' || event.details ? <details>
        <summary>{event.kind === 'usage' ? 'Recorded usage' : event.phase === 'call' ? 'Arguments / command' : 'Result / details'}</summary>
        <pre>{content}</pre>{Boolean(event.error) && <pre>{readable(event.error)}</pre>}
        {Boolean(event.details) && event.result !== undefined && <pre>{readable(event.details)}</pre>}
      </details> : <Markdown skipHtml components={{ a: ({ children }) => <span>{children}</span>,
        img: () => <span>[External image omitted]</span> }}>{content || 'No readable text in this record.'}</Markdown>}
      <Button size="sm" variant="ghost" onPress={() => {
        void window.graphtraj.copyText(content).then(() => setCopied('Copied'), () => setCopied('Copy unavailable'));
      }}>{copied || 'Copy'}</Button>
    </Card.Content>
  </Card>;
}

export function ActivityView({ projectId, ticketId }: { projectId: string; ticketId: string }) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [alias, setAlias] = useState('');
  const [error, setError] = useState('');
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [following, setFollowing] = useState(true);
  const [pageStart, setPageStart] = useState(0);
  const [pending, setPending] = useState(0);
  const followingRef = useRef(true);
  const bottom = useRef<HTMLDivElement>(null);
  const history = useRef<HTMLDivElement>(null);
  const loadRequested = useRef(false);

  useEffect(() => {
    let alive = true;
    let cursor: string | undefined;
    let more = false;
    let timer: ReturnType<typeof setTimeout>;
    const seen = new Set<string>();
    setEvents([]); setPageStart(0); setPending(0); loadRequested.current = false;
    async function refresh() {
      try {
        const next = await window.graphtraj.activity(projectId, {
          ticket_id: ticketId, ...(alias ? { alias } : {}), ...(cursor ? { cursor } : {}),
        });
        if (!alive) return;
        if (next.availability === 'cursor-expired' || next.availability === 'trace-changed') {
          cursor = undefined; more = false;
          setError('Observer reconnected or Trace changed. Replaying recorded events; existing content is retained.');
        } else {
          setActivity(next); setError(next.reason || '');
          cursor = next.cursor ?? undefined;
          more = Boolean(next.has_more && !next.waiting_for_record);
          const added = (next.events ?? []).filter(event => !seen.has(event.id));
          added.forEach(event => seen.add(event.id));
          if (added.length) {
            setEvents(previous => [...previous, ...added]);
            if (followingRef.current) setPageStart(Math.max(0, seen.size - 100));
            if (!followingRef.current) setPending(value => value + added.length);
          }
        }
      } catch {
        if (alive) setError('Activity disconnected or access refused. Retrying; retained messages remain readable.');
      } finally { if (alive) timer = setTimeout(tick, 3000); }
    }
    function tick() {
      if (more && !loadRequested.current) {
        void window.graphtraj.activity(projectId, { ticket_id: ticketId }).then(next => {
          if (alive) setActivity(previous => ({ ...previous, ...next }));
        }, () => { if (alive) setError('Member status disconnected; retained content remains readable.'); })
          .finally(() => { if (alive) timer = setTimeout(tick, 3000); });
      } else { loadRequested.current = false; void refresh(); }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, ticketId, alias]);

  useEffect(() => {
    if (following) bottom.current?.scrollIntoView({ block: 'nearest' });
  }, [events, following]);

  function follow(value: boolean) {
    followingRef.current = value; setFollowing(value);
    if (value) { setPageStart(Math.max(0, events.length - 100)); setPending(0); }
  }

  return <section className="activity" aria-label="Agent activity">
    <h3>Agents</h3>
    {(['Current', 'Historical'] as const).map(group => <div key={group}>
      <h4>{group} members</h4>
      {activity?.agents.filter(agent => agent.historical === (group === 'Historical')).map(agent =>
        <div className="activity-member" key={agent.alias}>
          <Button size="sm" variant={alias === agent.alias ? 'primary' : 'secondary'} onPress={() => setAlias(agent.alias)}>{agent.alias}</Button>
          <p>{agent.runtime || 'Runtime unknown'} · {agent.model || 'Model not recorded'} · {agent.state}
            {agent.last_outcome && ` · ${agent.last_outcome}`}<br />Parent: {agent.parent ?? 'Not recorded / root'}
            {agent.reason && <><br />{agent.reason}</>}</p>
        </div>)}
    </div>)}
    {activity?.agents.length === 0 && <p>No participating Agents recorded.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <p className="note">{activity ? `Last update ${new Date(activity.updated_at).toLocaleTimeString()}` : 'Loading members…'}</p>
    {alias && <>
      <div className="activity-controls"><h3>Chat · Read only</h3>
        <Button size="sm" variant="secondary" onPress={() => follow(!following)}>{following ? 'Pause following' : `Follow new messages${pending ? ` (${pending})` : ''}`}</Button>
        <Button size="sm" variant="ghost" isDisabled={pageStart === 0} onPress={() => { follow(false); setPageStart(value => Math.max(0, value - 100)); }}>Earlier</Button>
        <Button size="sm" variant="ghost" isDisabled={pageStart + 100 >= events.length} onPress={() => { follow(false); setPageStart(value => value + 100); }}>Later</Button>
      </div>
      <div className="activity-history" ref={history} onScroll={() => {
        const node = history.current;
        if (node && node.scrollHeight - node.scrollTop - node.clientHeight > 80) follow(false);
      }}>
        {events.slice(pageStart, pageStart + 100).map(event => <EventCard key={event.id} event={event} />)}
        {!events.length && <p>{activity?.availability === 'available' ? 'No readable activity recorded yet.' : 'Activity is unavailable or loading.'}</p>}
        <div ref={bottom} />
      </div>
      {activity?.has_more && !activity.waiting_for_record && <Button size="sm" variant="secondary" onPress={() => { loadRequested.current = true; }}>Load next recorded page</Button>}
      <p className="note">{events.length} events loaded · Missing usage stays unknown. Stream and final usage retain their native identity; values are not summed here.</p>
    </>}
  </section>;
}
