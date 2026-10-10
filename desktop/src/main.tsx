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
import { SettingsView } from './Settings';
import { UsageView } from './UsageDashboard';
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

function GraphView({ projectId, active }: { projectId: string; active: boolean }) {
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [detailWidth, setDetailWidth] = useState(380);
  const [expanded, setExpanded] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<TicketNode>([]);
  const flow = useReactFlow<TicketNode>();

  useEffect(() => {
    if (!active) return;
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
  }, [projectId, retry, active]);

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
    <div className={`graph-workspace ${expanded && detail ? 'chat-expanded' : ''}`}>
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
      {detail && <aside className="details" style={{ '--column-width': `${detailWidth}px` } as React.CSSProperties} aria-label="Ticket details">
        <div className="detail-controls"><Button size="sm" variant="ghost" onPress={() => setSelected(null)}>Close details</Button>
          <Button size="sm" variant="secondary" onPress={() => setExpanded(value => !value)}>{expanded ? 'Collapse chat' : 'Expand chat'}</Button>
          <label>Column width<input aria-label="Detail width" type="range" min="280" max="640" value={detailWidth}
            onChange={event => setDetailWidth(Number(event.target.value))} /></label></div>
        <p className="eyebrow">Ticket #{detail.ticket_id}</p><h2>{detail.title}</h2>
        <span className={`status status-${detail.status}`}>{detail.status}</span>
        <details className="ticket-facts"><summary>Ticket facts</summary><dl><dt>Ticket name</dt><dd>{detail.ticket_name}</dd>
          <dt>Active</dt><dd>{detail.active ? 'Yes' : 'No — replaced / inactive'}</dd>
          <dt>Dependencies</dt><dd>{detail.dependencies.join(', ') || 'None'}</dd>
          <dt>Replaced by</dt><dd>{detail.replaced_by.join(', ') || 'None'}</dd>
          <dt>Dependency readiness</dt><dd>{detail.ready ? 'Ready' : 'Not ready to start'}</dd></dl></details>
        {!visible.has(detail.ticket_id) && <p>This ticket is hidden by the current filter.</p>}
        <ActivityView key={`${projectId}:${detail.ticket_id}`} projectId={projectId} ticketId={detail.ticket_id} active={active} expanded={expanded} />
        <p className="note">This is the recorded Ticket state. An execution finishing is not acceptance. A time notice is not an actual stop.</p>
      </aside>}
    </div>
  </>;
}

function App() {
  const [view, setView] = useState<'graph' | 'settings' | 'usage' | 'models'>('graph');
  const [sidebar, setSidebar] = useState(true);
  const [globalOpen, setGlobalOpen] = useState(true);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [visited, setVisited] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(operation: () => Promise<Preferences>): Promise<void> {
    setBusy(true);
    try {
      const next = await operation();
      setPreferences(next); setError('');
      if (next.selected) setVisited(previous => [...new Set([...previous, next.selected!])]);
    }
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
  const selected = preferences?.projects.find(project => project.id === preferences.selected);
  const projectName = selected?.root.split(/[\\/]/).filter(Boolean).at(-1);
  return <div className="app">
    {sidebar && <nav className="projects" aria-label="Projects">
      <div className="brand">GraphTraj<span>Project monitor</span></div>
      <section className="sidebar-group">
        <Button className="group-toggle" variant="ghost" aria-expanded={globalOpen} onPress={() => setGlobalOpen(value => !value)}>GLOBAL <span>{globalOpen ? '⌄' : '›'}</span></Button>
        {globalOpen && <>
          <Button variant="ghost" aria-expanded={settingsOpen} onPress={() => setSettingsOpen(value => !value)}>Settings <span aria-hidden="true">{settingsOpen ? '⌄' : '›'}</span></Button>
          {settingsOpen && <Button className="submenu" variant={view === 'models' ? 'secondary' : 'ghost'} onPress={() => setView('models')}>Agents &amp; models</Button>}
        </>}
      </section>
      <section className="sidebar-group project-group">
        <Button className="group-toggle" variant="ghost" aria-expanded={projectsOpen} onPress={() => setProjectsOpen(value => !value)}>PROJECTS <span>{projectsOpen ? '⌄' : '›'}</span></Button>
        {projectsOpen && <>
          <div className="project-list">{preferences?.projects.map(project => <div className="project-entry" key={project.id}>
            <button className={`project-button ${preferences.selected === project.id ? 'current' : ''}`}
              aria-current={preferences.selected === project.id ? 'page' : undefined} disabled={busy}
              onClick={() => { void change(() => window.graphtraj.selectProject(project.id)); }}>
              <strong>{project.root.split(/[\\/]/).filter(Boolean).at(-1)}</strong><span>{project.root}</span>
              {project.unavailable && <span className="path-unavailable" title={project.unavailable}>Path unavailable</span>}
            </button>
            <div className="project-actions">
              <Button size="sm" variant="ghost" isDisabled={busy} aria-label={`Relocate ${project.root}`}
                onPress={() => { void change(() => window.graphtraj.relocateProject(project.id)); }}>Relocate</Button>
              <Button size="sm" variant="ghost" isDisabled={busy} aria-label={`Remove ${project.root}`}
                onPress={() => { void change(() => window.graphtraj.removeProject(project.id)); }}>Remove</Button>
            </div>
          </div>)}</div>
          <Button variant="ghost" isDisabled={busy} onPress={() => { void change(() => window.graphtraj.addProject()); }}>Add project</Button>
          <Button size="sm" variant="ghost" isDisabled={busy} onPress={() => { void change(() => window.graphtraj.projects()); }}>Check paths</Button>
        </>}
      </section>
      {selected && <nav className="current-project" aria-label="Project views">
        <h2 title={selected.root}>{projectName}</h2>
        <Button variant={view === 'graph' ? 'secondary' : 'ghost'} onPress={() => setView('graph')}>Monitor</Button>
        <Button variant={view === 'settings' ? 'secondary' : 'ghost'} onPress={() => setView('settings')}>Teams &amp; roles</Button>
        <Button variant={view === 'usage' ? 'secondary' : 'ghost'} onPress={() => setView('usage')}>Project usage</Button>
      </nav>}
      <p className="note sidebar-note">Optional project monitor. Removing an index entry or closing this window does not stop tasks.</p>
    </nav>}
    <main>
      <header className="workspace-heading"><Button size="sm" variant="ghost" aria-label={sidebar ? 'Hide sidebar' : 'Show sidebar'}
        aria-expanded={sidebar} onPress={() => setSidebar(value => !value)}>☰</Button>
        <strong>{projectName || 'GraphTraj'}</strong><span>{view === 'graph' ? 'Monitor' : view === 'usage' ? 'Project usage' : view === 'models' ? 'Agents & models' : 'Teams & roles'}</span>
        <span className="read-only">Optional desktop companion</span>
      </header>
      {error && <div className="error" role="alert">{error}</div>}
      {preferences?.projects.filter(project => visited.includes(project.id)).map(project =>
        <div className="monitor-page" key={`${project.id}:${project.root}`} hidden={view !== 'graph' || project.id !== preferences.selected}>
          <ReactFlowProvider><GraphView projectId={project.id} active={view === 'graph' && project.id === preferences.selected} /></ReactFlowProvider>
        </div>)}
      {selected && view === 'usage' && <UsageView key={selected.id} projectId={selected.id} />}
      {selected && view === 'settings' && <SettingsView key={selected.id} projectId={selected.id} />}
      {view === 'models' && <div className="welcome"><p className="eyebrow">Settings</p><h1>Agents &amp; models</h1>
        <p>Global connection editing is not available in this version. Existing project Runtime and model settings remain available in Teams &amp; roles.</p>
        {selected && <Button onPress={() => setView('settings')}>Open Teams &amp; roles</Button>}</div>}
      {!selected && view !== 'models' && <div className="welcome"><p className="eyebrow">Optional desktop companion</p>
        <h1>Your projects, in view.</h1><p>Add an existing GraphTraj project directory to see its complete task graph.</p>
        <p>GraphTraj continues to work through its native CLI when this window is closed.</p></div>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
