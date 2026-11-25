import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import Markdown from 'react-markdown';
import type { Activity, ActivityEvent, Agent, Member, Members } from '../electron/activity';
import { ToolContent } from './ToolContent';
import { aliasRole, compactNumber, middle } from './usage.ts';
import { Icon, StateMessage, Status } from './ui';

const readable = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

/** Show only active or standby for a member; retirement stays a history label. */
export const visibleState = (state?: string | null) => state === 'retired' ? 'retired'
  : state === 'running' || state === 'unreachable' || state === 'active' ? 'active' : 'standby';


/** Two-letter initials for a role: 'team_leader' → 'TL', 'engineer' → 'EN'. */
const initials = (name: string) => {
  const words = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? '?').slice(0, 2)).toUpperCase();
};
function RoleAvatar({ name, small = false, historical = false }: { name: string; small?: boolean; historical?: boolean }) {
  return <span className={`avatar role-avatar ${small ? 'small' : ''} ${historical ? 'historical' : ''}`} aria-hidden="true">{initials(name)}</span>;
}

/** Name the direction of a recorded message by the role of the Agent whose Session holds it. */
const messageTitle = (event: ActivityEvent) => event.kind !== 'message' || !event.agent ? event.role || event.kind
  : event.role === 'user' ? `Message to ${aliasRole(event.agent)}` : event.role === 'assistant' ? `Message from ${aliasRole(event.agent)}` : event.role || event.kind;

/** First non-empty line of the recorded arguments, or of the text; never a generated summary. */
const argumentLine = (event: ActivityEvent) => {
  const value = event.arguments !== undefined ? typeof event.arguments === 'string' ? event.arguments : JSON.stringify(event.arguments) : event.text ?? '';
  return (value.split('\n').map(line => line.trim()).find(Boolean) ?? '').slice(0, 240);
};
const clock = (time: ActivityEvent['time']) => time === null ? 'Time not recorded' : new Date(time).toLocaleTimeString();

export function EventCard({ event }: { event: ActivityEvent }) {
  const [copied, setCopied] = useState('');
  const content = event.text ?? readable(event.result ?? event.arguments ?? event.usage) ?? '';
  const details = event.details === undefined ? '' : readable(event.details);
  const error = event.error ? readable(event.error) : '';
  const parts = event.kind === 'tool' ? event.content ?? [] : [];
  const rawResult = event.kind === 'tool' && event.result !== undefined ? readable(event.result) : '';
  const copyContent = [content, details, error].filter(Boolean).join('\n\n');
  const title = event.kind === 'tool' ? `Tool · ${event.name || 'Name not recorded'}`
    : event.role === 'reasoning' ? 'Reasoning' : event.kind === 'work' ? 'Execution event' : messageTitle(event);
  const time = event.time === null ? 'Time not recorded' : new Date(event.time).toLocaleString();
  const copy = <button aria-label="Copy record" onClick={() => {
    void window.graphtraj.copyText(copyContent).then(() => setCopied('Copied'), () => setCopied('Copy unavailable'));
  }}><Icon name={copied === 'Copied' ? 'check' : 'copy'} size={14}/>{copied || 'Copy'}</button>;
  if (event.kind === 'usage') return null;
  // V6.4: one line per tool record: icon, name, the argument's first line, phase or result, time.
  // The visible terminal icon stands for 'Tool'; the words stay in the name for assistive technology.
  const argument = event.kind === 'tool' ? argumentLine(event) : '';
  if (event.kind === 'tool' || event.details) return <div className="tool-message activity-event">
    <details className={`tool-card ${event.error ? 'tool-error' : ''}`}><summary><span className="tool-icon"><Icon name="terminal" size={15}/></span><strong>{event.kind === 'tool' ? <><span className="sr-only">Tool · </span>{event.name || 'Name not recorded'}</> : title}</strong>{argument && <small className="tool-argument" title={argument}>{argument}</small>}<span className={event.error ? 'tool-result error' : event.phase === 'call' ? 'tool-result call' : 'tool-result'}>{event.error ? 'Error' : event.phase || 'Recorded'}<Icon name={event.error ? 'info' : event.phase === 'call' ? 'right' : 'check'} size={13}/></span><time title={time}>{clock(event.time)}</time><Icon name="down" size={14}/></summary>
      <div className="tool-details">{parts.length ? <ToolContent parts={parts}/> : <pre>{content}</pre>}<details className="tool-technical"><summary>Technical details<Icon name="down" size={12}/></summary><dl><dt>Source</dt><dd title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</dd>{event.call_id && <><dt>Call ID</dt><dd>{event.call_id}</dd></>}{event.tool_type && <><dt>Record type</dt><dd>{event.tool_type}</dd></>}{rawResult && <><dt>Raw result</dt><dd><pre>{rawResult}</pre></dd></>}{details && <><dt>Record details</dt><dd><pre>{details}</pre></dd></>}{error && <><dt>Error flag</dt><dd><pre>{error}</pre></dd></>}</dl>{copy}</details></div></details></div>;
  const tone = event.role === 'reasoning' ? 'message-reasoning' : event.kind === 'message' && event.role === 'user' ? 'message-in' : '';
  return <article className={`message activity-event ${tone}`.trim()}><div className="message-heading"><strong title={event.agent}>{title}</strong>{tone === 'message-in' && <span>received</span>}<time title={time}>{time}</time></div><div className="message-body"><Markdown skipHtml components={{ a: ({ children }) => <span>{children}</span>, img: () => <span>[External image omitted]</span> }}>{content || 'No readable text in this record.'}</Markdown></div><div className="record-source">{copy}<span title={event.source.trace}>{event.source.runtime} · byte {event.source.offset}</span></div></article>;
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
  const count = (value?: number) => value === undefined ? 'Unknown' : compactNumber(value);
  // V6.5: one compact line; the alias stays in aria-label, exact values in the details.
  return <footer className="usage-supplement" aria-label={`Usage for ${agent}`}>
    <details><summary><Icon name="usage" size={13}/><b>Usage</b> in {count(tokens?.input)} · out {count(tokens?.output)} · {scope} · {latest.source.runtime} · {latest.usage?.scope === 'latest-response' ? 'Latest response observation' : 'Native usage observation'}<Icon name="right" size={13}/></summary>
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
  return <div className="member-pills">{agents.map(agent => <button key={agent.alias} title={agent.alias} className={`${agent.historical ? 'history' : ''} ${focus === agent.alias ? 'selected' : ''}`} onClick={() => onRead(agent.alias)}><RoleAvatar name={agent.kind === 'main' ? 'Main' : aliasRole(agent.alias)} small historical={agent.historical}/><span><strong>{agent.kind === 'main' ? middle(agent.alias) : aliasRole(agent.alias)}</strong><small>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · {agent.runtime || 'Runtime unknown'}</small></span><Icon name="right" size={13}/></button>)}</div>;
}

/** Current summary members by default, or one chosen summary's history, as the real parent tree.
 * Changing the scope only re-queries; it never stops, retires or reparents an Agent. */
export function MemberTree({ projectId, summaries, active, onRead }: {
  projectId: string; summaries: { task_id: string; title: string }[]; active: boolean; onRead: (member: Member) => void;
}) {
  const [scope, setScope] = useState('');
  const [result, setResult] = useState<Members | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try { const next = await window.graphtraj.members(projectId, scope || undefined); if (alive) { setResult(next); setError(''); } }
      catch (failure) { if (alive) setError(`Could not read members: ${String(failure)}. Retrying automatically.`); }
      finally { if (alive) timer = setTimeout(refresh, 3000); }
    }
    setResult(null); void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, scope, active]);
  const members = result?.members ?? [];
  const aliases = new Set(members.map(member => member.alias));
  const rows: [Member, number][] = [];
  const visit = (parent: string | null, depth: number) => members
    .filter(member => parent === null ? !member.parent || !aliases.has(member.parent) : member.parent === parent)
    .forEach(member => { rows.push([member, depth]); if (depth < 32) visit(member.alias, depth + 1); });
  visit(null, 0);
  return <section className="member-tree" aria-label="Agent members">
    <label className="native-field"><span>Member scope</span><select aria-label="Member scope" value={scope} onChange={event => setScope(event.target.value)}>
      <option value="">Current summaries</option>{summaries.map(task => <option key={task.task_id} value={task.task_id}>History · #{task.task_id} {task.title}</option>)}</select></label>
    <p className="native-notice">{scope ? 'History of one summary, including completed and retired members.' : `Members of current summaries ${result?.scope.map(id => `#${id}`).join(', ') || ''} and their child tasks.`} Changing scope does not stop, retire or reparent any Agent.</p>
    {error && <StateMessage kind="error">{error}</StateMessage>}
    {!members.length && !error && <StateMessage kind={result ? 'empty' : 'loading'}>{result ? 'No members in this scope.' : 'Loading members…'}</StateMessage>}
    {/* V7: a tree table over the existing Member fields; guide lines show depth, the full alias stays in title. */}
    {rows.length > 0 && <table className="member-tree-table">
      <thead><tr><th scope="col">Agent</th><th scope="col">Task</th><th scope="col">State</th><th scope="col">Runtime</th><th scope="col">Parent</th></tr></thead>
      <tbody>{rows.map(([member, depth]) => <tr key={member.alias} data-alias={member.alias} data-depth={depth} className={member.historical ? 'history' : ''}>
        <td className="member-agent"><span className="member-guides" style={{ width: depth * 20 }} aria-hidden="true">{Array.from({ length: depth }, (_, level) => <i key={level}/>)}</span>
          <button title={member.alias} onClick={() => onRead(member)}><RoleAvatar name={member.role || aliasRole(member.alias)} small historical={member.historical}/><span><strong>{member.role || aliasRole(member.alias)}</strong><small>{middle(member.alias, 18)}</small></span></button></td>
        <td className="member-task">#{member.task_id}</td>
        <td className="member-state"><span className={`status status-${member.retired ? 'retired' : member.state === 'active' ? 'active' : 'standby'}`}><span className="status-dot"/>{member.retired ? 'Retired · history' : `${member.state === 'active' ? 'Active' : 'Standby'}${member.historical ? ' · history' : ''}`}</span>{member.diagnostic && <small>{member.diagnostic}</small>}</td>
        <td className="member-runtime">{member.runtime}</td>
        <td className="member-parent" title={member.parent ?? undefined}>{member.parent ? aliasRole(member.parent) : 'Not recorded / root'}</td>
      </tr>)}</tbody>
    </table>}
  </section>;
}

/** Keep each actual member in its own independently scrolling column. */
export function ActivityView({ projectId, taskId, active = true, expanded = true, focusAgent, onActivity, onError, refreshKey = 0 }: {
  projectId: string; taskId?: string; active?: boolean; expanded?: boolean; focusAgent?: string | null; onActivity?: (activity: Activity) => void;
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
        const next = await window.graphtraj.activity(projectId, taskId ? { task_id: taskId } : {});
        if (!taskId) next.agents = next.agents.filter(agent => agent.kind === 'main');
        if (alive) { setActivity(next); setError(next.reason || ''); onError?.(next.reason || ''); onActivity?.(next); }
      } catch {
        if (alive) {
          const message = taskId ? 'Could not load this task’s Agent sessions. Retrying automatically.' : 'Could not load Main sessions for this project. Retrying automatically.';
          setError(message); onError?.(message);
        }
      }
      finally { if (alive) { setLoading(false); timer = setTimeout(refresh, 3000); } }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, taskId, active, retry, refreshKey]);
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
  // Step by one column: columns stretch between 400 and 760 px (V6.6).
  const move = (direction: number) => columns.current?.scrollBy({ left: direction * (columns.current.querySelector<HTMLElement>('.agent-column')?.offsetWidth || 440), behavior: 'instant' });
  return <section className="activity" aria-label="Agent activity">
    {activity?.scope === 'self' && <p className="native-notice">This Agent connection shows only its own Session.</p>}
    {error && <StateMessage kind="error" action={<Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Retry now</Button>}>{error}</StateMessage>}
    {activity?.notices?.map(notice => <p className="native-notice" key={notice}>{notice}</p>)}
    {!activity?.agents.length && !error && <StateMessage kind={activity ? 'empty' : loading ? 'loading' : 'error'} role="status">{activity ? taskId ? 'No participating Agents recorded.' : 'No associated Main sessions recorded for this project.' : loading ? taskId ? 'Loading Agent sessions…' : 'Loading Main sessions…' : 'Session list unavailable.'}</StateMessage>}
    <div className="agent-columns" ref={columns} tabIndex={0} aria-label="Agent columns" role="region"
      onKeyDown={event => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); } }}
      onScroll={event => { if (active && expanded) horizontal.current = event.currentTarget.scrollLeft; updateEdges(); }}>
      {activity?.agents.map(agent => <AgentColumn key={agent.alias} projectId={projectId} taskId={taskId} agent={agent} active={active && expanded}/>)}
    </div>
    {/* V6.7: one footer row: previous, the draggable slider (disabled when every column fits), next, count and update time. */}
    <footer className="columns-footer"><Button isIconOnly variant="ghost" aria-label="Previous agent columns" isDisabled={scroll.left < 2} onPress={() => move(-1)}><Icon name="left" size={16}/></Button>
      <input className="agent-horizontal-scrollbar" type="range" min={0} max={Math.max(1, scroll.max)} step={1} value={Math.min(scroll.left, Math.max(1, scroll.max))} disabled={scroll.max < 1} aria-label="Agent columns horizontal scrollbar" style={{ '--scroll-thumb-width': `${scroll.thumb}px` } as React.CSSProperties} onChange={event => { if (columns.current) columns.current.scrollLeft = Number(event.target.value); updateEdges(); }}/>
      <Button isIconOnly variant="ghost" aria-label="Next agent columns" isDisabled={scroll.left >= scroll.max - 2} onPress={() => move(1)}><Icon name="right" size={16}/></Button>
      <span>{activity ? `${activity.agents.length} ${activity.agents.length === 1 ? 'agent' : 'agents'} · updated ${new Date(activity.updated_at).toLocaleTimeString()}` : error ? 'Session list unavailable' : 'Loading Session list…'}</span></footer>
  </section>;
}

function AgentColumn({ projectId, taskId, agent, active }: {
  projectId: string; taskId?: string; agent: Agent; active: boolean;
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
          ...(taskId ? { task_id: taskId } : {}), alias: agent.alias, ...(cursor.current ? { cursor: cursor.current } : {}),
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
  }, [projectId, taskId, agent.alias, active, retry]);

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

  const role = agent.kind === 'main' ? 'Main' : aliasRole(agent.alias);
  const state = agent.kind === 'main' ? agent.state : visibleState(agent.state);
  const shown = events.length ? `${pageStart + 1}–${Math.min(pageStart + 100, events.length)} of ${events.length}` : '0 of 0';
  // V6.1–2: the role as the heading (full alias in title and the article's name); one state chip,
  // kept inside the 'Current|Historical · <state>' text; Runtime, model and parent on one meta line.
  return <article className={`agent-chat-column agent-column ${agent.historical ? 'historical-column' : ''}`} data-agent-id={agent.alias} aria-label={agent.alias}>
    <header className="agent-column-heading"><RoleAvatar name={role} historical={agent.historical}/><div><h2 title={agent.alias}>{role}</h2><span className="agent-column-state" title={agent.state}>{agent.kind === 'main' ? 'Associated Main' : agent.historical ? 'Historical' : 'Current'} · <Status value={state}/></span></div></header>
    <div className="agent-column-meta"><span className="agent-runtime" title={agent.model ?? undefined}><Icon name="terminal" size={13}/>{agent.runtime || 'Runtime unknown'} · {agent.model || 'Model not recorded'}</span><span className="agent-column-parent"><Icon name="branch" size={13}/><span title={agent.kind === 'main' ? agent.session : agent.parent ?? undefined}>{agent.kind === 'main' ? `Session: ${agent.session}` : `Parent: ${agent.parent ? aliasRole(agent.parent) : 'Not recorded / root'}`}</span></span></div>
    <div className="conversation-panel">
      {error && <StateMessage kind="error" action={<Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Retry now</Button>}>{error}</StateMessage>}
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
        {!events.length && !error && <StateMessage kind={!activity ? 'loading' : activity.availability === 'available' ? 'empty' : 'error'} role={null}>{!activity ? 'Loading Session messages…' : activity.availability === 'available' ? 'No readable activity recorded yet.' : activity.reason || 'Session messages unavailable.'}</StateMessage>}
        <div className="transcript-end">{events.length} events loaded · Missing usage stays unknown.</div>
      </div></div>
      {/* V6.8: the follow switch on the left; the shown range with Earlier / Later on the right. */}
      <div className="reading-toolbar"><button className={following ? 'following' : 'paused'} onClick={() => follow(!following)}><Icon name={following ? 'pause' : 'play'} size={13}/>{following ? 'Pause following' : `Follow new messages${pending ? ` (${pending})` : ''}`}</button><span className="reading-pager"><span className="reading-position">{shown}</span><button disabled={pageStart === 0} onClick={() => { follow(false); setPageStart(value => Math.max(0, value - 100)); }}>Earlier</button><button disabled={pageStart + 100 >= events.length} onClick={() => { follow(false); setPageStart(value => value + 100); }}>Later</button>{activity?.has_more && !activity.waiting_for_record && <button onClick={() => { loadRequested.current = true; }}>Load next recorded page</button>}</span></div>
    </div></article>;
}
