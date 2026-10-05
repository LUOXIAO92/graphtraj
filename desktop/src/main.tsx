import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Card } from '@heroui/react';
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle,
  Position, MarkerType, useNodesState, useReactFlow, type NodeProps, type Node,
} from '@xyflow/react';
import type { DesktopAPI, Observation, Preferences, Ticket } from '../electron/types';
import { layout } from './layout';
import { ActivityView } from './Activity';
import '@xyflow/react/dist/style.css';
import './style.css';

declare global { interface Window { graphtraj: DesktopAPI } }
type TicketNode = Node<{ ticket: Ticket }>;

function TicketCard({ data, selected }: NodeProps<TicketNode>) {
  const ticket = data.ticket;
  return <Card className={`ticket ${selected ? 'selected' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <Card.Header>
      <Card.Description>#{ticket.ticket_id}{!ticket.active ? ' · Replaced / inactive' : ''}</Card.Description>
      <Card.Title>{ticket.title}</Card.Title>
    </Card.Header>
    <Card.Content>
      <span className={`status status-${ticket.status}`}>{ticket.status}</span>
      {ticket.ready && <span className="ready"> · Ready to start</span>}
      <p className="dependencies">Depends on: {ticket.dependencies.map(id => `#${id}`).join(', ') || 'none'}</p>
    </Card.Content>
    <Handle type="source" position={Position.Right} />
  </Card>;
}
const nodeTypes = { ticket: TicketCard };

function GraphView({ projectId }: { projectId: string }) {
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [detailWidth, setDetailWidth] = useState(340);
  const [nodes, setNodes, onNodesChange] = useNodesState<TicketNode>([]);
  const flow = useReactFlow<TicketNode>();

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      setLoading(true);
      try {
        const next = await window.graphtraj.graph(projectId);
        if (alive && next.projectId === projectId) { setObservation(next); setError(''); }
      } catch (error) {
        if (alive) setError(String(error));
      } finally {
        if (alive) { setLoading(false); timer = setTimeout(refresh, 3000); }
      }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, retry]);

  const tickets = observation?.graph.tickets;
  const positions = useMemo(() => layout(tickets ?? []), [tickets]);
  useEffect(() => {
    if (!tickets) return;
    setNodes(previous => tickets.map(ticket => ({
      id: ticket.ticket_id, type: 'ticket', data: { ticket },
      position: previous.find(node => node.id === ticket.ticket_id)?.position ?? positions[ticket.ticket_id],
    })));
  }, [tickets, positions, setNodes]);

  const visible = new Set((tickets ?? []).filter(ticket =>
    status === 'all' || (status === 'inactive' ? !ticket.active : ticket.status === status)
  ).map(ticket => ticket.ticket_id));
  const matches = (tickets ?? []).filter(ticket => visible.has(ticket.ticket_id) &&
    `${ticket.ticket_id} ${ticket.title} ${ticket.ticket_name}`.toLowerCase().includes(query.toLowerCase()));
  const edges = (tickets ?? []).flatMap(ticket => ticket.dependencies.map(dependency => ({
    id: `${dependency}-${ticket.ticket_id}`, source: dependency, target: ticket.ticket_id,
    hidden: !visible.has(dependency) || !visible.has(ticket.ticket_id),
    markerEnd: { type: MarkerType.ArrowClosed },
  })));
  const detail = tickets?.find(ticket => ticket.ticket_id === selected);

  function locate(ticket: Ticket): void {
    setSelected(ticket.ticket_id);
    void flow.fitView({ nodes: [{ id: ticket.ticket_id }], duration: 200, maxZoom: 1.1 });
  }

  return <>
    <header className="toolbar">
      <div><h1>Task graph</h1><p>Native delivery state · Read only</p></div>
      <label>Find ticket<input type="search" placeholder="Number or title" value={query}
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter' && matches[0]) locate(matches[0]); }} /></label>
      <label>Status<select value={status} onChange={event => setStatus(event.target.value)}>
        <option value="all">All tickets</option><option value="inactive">Replaced / inactive</option>
        {[...new Set(tickets?.map(ticket => ticket.status))].sort().map(value =>
          <option key={value} value={value}>{value}</option>)}
      </select></label>
      <Button variant="secondary" onPress={() => {
        setNodes(previous => previous.map(node => ({ ...node, position: positions[node.id] })));
        requestAnimationFrame(() => { void flow.fitView({ duration: 200 }); });
      }}>Auto layout</Button>
    </header>
    <div className="observation" role="status">
      {error ? 'Offline / query error' : loading ? 'Refreshing…' : 'Connected'}
      {' · '}{visible.size} / {tickets?.length ?? 0} tickets
      {' · '}{observation ? `Last update ${new Date(observation.updatedAt).toLocaleTimeString()}` : 'No graph received yet'}
      <Button size="sm" variant="ghost" isDisabled={loading} onPress={() => setRetry(value => value + 1)}>Refresh now</Button>
    </div>
    {error && <div className="error" role="alert">{error}<p>{observation
      ? 'Showing the last successful graph. Retrying automatically.' : 'Retrying automatically. Check the directory and native GraphTraj installation.'}</p></div>}
    {query && <div className="search-results" aria-label="Search results">
      {matches.length ? matches.map(ticket => <Button key={ticket.ticket_id} size="sm" variant="secondary"
        onPress={() => locate(ticket)}>#{ticket.ticket_id} {ticket.title}</Button>) : 'No matching visible tickets'}
    </div>}
    <div className="graph-workspace">
      <div className="graph" aria-label="Task dependency graph">
        {!observation && <div className="empty">{loading ? 'Loading native task graph…' : 'Graph unavailable'}</div>}
        {observation && tickets?.length === 0 && <div className="empty">No tickets registered in this project.</div>}
        <ReactFlow nodes={nodes.map(node => ({ ...node, hidden: !visible.has(node.id), selected: selected === node.id }))}
          edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
          onNodeClick={(_event, node) => setSelected(node.id)}
          nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null}
          fitView minZoom={0.05} maxZoom={2} colorMode="system">
          <Background /><Controls showInteractive={false} /><MiniMap pannable zoomable />
        </ReactFlow>
      </div>
      {detail && <aside className="details" style={{ width: detailWidth }} aria-label="Ticket details">
        <div className="detail-controls"><Button size="sm" variant="ghost" onPress={() => setSelected(null)}>Close details</Button>
          <label>Width<input aria-label="Detail width" type="range" min="280" max="640" value={detailWidth}
            onChange={event => setDetailWidth(Number(event.target.value))} /></label></div>
        <p className="eyebrow">Ticket #{detail.ticket_id}</p><h2>{detail.title}</h2>
        <span className={`status status-${detail.status}`}>{detail.status}</span>
        <dl><dt>Ticket name</dt><dd>{detail.ticket_name}</dd>
          <dt>Active</dt><dd>{detail.active ? 'Yes' : 'No — replaced / inactive'}</dd>
          <dt>Dependencies</dt><dd>{detail.dependencies.join(', ') || 'None'}</dd>
          <dt>Replaced by</dt><dd>{detail.replaced_by.join(', ') || 'None'}</dd>
          <dt>Dependency readiness</dt><dd>{detail.ready ? 'Ready' : 'Not ready to start'}</dd></dl>
        {!visible.has(detail.ticket_id) && <p>This ticket is hidden by the current filter.</p>}
        <ActivityView key={`${projectId}:${detail.ticket_id}`} projectId={projectId} ticketId={detail.ticket_id} />
        <p className="note">This is the recorded Ticket state. An execution finishing is not acceptance. A time notice is not an actual stop.</p>
      </aside>}
    </div>
  </>;
}

function App() {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(operation: () => Promise<Preferences>): Promise<void> {
    setBusy(true);
    try { setPreferences(await operation()); setError(''); }
    catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void change(() => window.graphtraj.projects()); }, []);
  useEffect(() => {
    const theme = matchMedia('(prefers-color-scheme: dark)');
    const update = () => { document.documentElement.classList.toggle('dark', theme.matches); };
    update(); theme.addEventListener('change', update);
    return () => theme.removeEventListener('change', update);
  }, []);
  return <div className="app">
    <nav className="projects" aria-label="Projects">
      <div className="brand">GraphTraj<span>Project monitor</span></div>
      <Button isDisabled={busy} onPress={() => { void change(() => window.graphtraj.addProject()); }}>Add project</Button>
      <div className="project-list">{preferences?.projects.map(project => <div className="project-entry" key={project.id}>
        <button className={`project-button ${preferences.selected === project.id ? 'current' : ''}`}
          aria-current={preferences.selected === project.id ? 'page' : undefined} disabled={busy}
          onClick={() => { void change(() => window.graphtraj.selectProject(project.id)); }}>
          <strong>{project.root.split(/[\\/]/).filter(Boolean).at(-1)}</strong><span>{project.root}</span>
        </button>
        <Button size="sm" variant="ghost" isDisabled={busy} aria-label={`Remove ${project.root}`}
          onPress={() => { void change(() => window.graphtraj.removeProject(project.id)); }}>Remove from list</Button>
      </div>)}</div>
      <p className="note">Removing a project only changes this list. Projects and running tasks remain independent of this window.</p>
    </nav>
    <main>{error && <div className="error" role="alert">{error}</div>}
      {preferences?.selected ? <ReactFlowProvider key={preferences.selected}>
        <GraphView projectId={preferences.selected} />
      </ReactFlowProvider> : <div className="welcome"><p className="eyebrow">Optional desktop companion</p>
        <h1>Your projects, in view.</h1><p>Add an existing GraphTraj project directory to see its complete task graph.</p>
        <p>GraphTraj continues to work through its native CLI when this window is closed.</p></div>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
