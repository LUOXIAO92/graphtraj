import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button } from '@heroui/react';
import { ReactFlow, ReactFlowProvider, Background, Controls, Handle, Position, MarkerType,
  useNodesState, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import type { DesktopAPI, Observation, Preferences, Project, Ticket } from '../electron/types';
import type { Activity } from '../electron/activity';
import { layout } from './layout';
import { ActivityView, MemberPills } from './Activity';
import { SettingsView } from './Settings';
import { ConnectionsView } from './Connections';
import { UsageView } from './UsageDashboard';
import { Icon, Logo, Status, Dialog } from './ui';
import '@xyflow/react/dist/style.css';
import './style.css';
import './canvas.css';
import './d-refinement.css';
import './d-polish.css';
import './native.css';

declare global { interface Window { graphtraj: DesktopAPI } }
type TicketNode = Node<{ ticket: Ticket }>;
const projectName = (project?: Project) => project?.root.split(/[\\/]/).filter(Boolean).at(-1) || 'No project selected';

function TicketCard({ data, selected }: NodeProps<TicketNode>) {
  const ticket = data.ticket;
  return <div className={`task-node ${selected ? 'selected' : ''} ${!ticket.active ? 'replaced' : ticket.status}`}>
    <Handle type="target" position={Position.Left}/><div className="node-top"><span className="ticket-id">#{ticket.ticket_id}</span><Status value={ticket.status}/></div>
    <strong className="node-title">{ticket.title}</strong><p className="node-subtitle">{ticket.ticket_name}</p>
    <div className="node-bottom"><span><Icon name="branch" size={13}/>{ticket.dependencies.length} dependencies</span><span>{!ticket.active ? 'Replaced / inactive' : ticket.ready ? 'Ready' : 'Not ready'}</span></div>
    <Handle type="source" position={Position.Right}/></div>;
}
const nodeTypes = { ticket: TicketCard };

/** Keep each visited project's graph and reading workspace mounted independently. */
function GraphView({ project, active, sidebarButton }: { project: Project; active: boolean; sidebarButton: React.ReactNode }) {
  const projectId = project.id;
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [expanded, setExpanded] = useState(false);
  const [focusAgent, setFocusAgent] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
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
      } catch (error) { if (alive) setError(String(error)); }
      finally { if (alive) { setLoading(false); timer = setTimeout(refresh, 3000); } }
    }
    void refresh();
    return () => { alive = false; clearTimeout(timer); };
  }, [projectId, retry, active]);
  const tickets = observation?.graph.tickets;
  const positions = useMemo(() => layout(tickets ?? []), [tickets]);
  useEffect(() => {
    if (!tickets) return;
    setNodes(previous => tickets.map(ticket => ({ id: ticket.ticket_id, type: 'ticket', data: { ticket },
      position: previous.find(node => node.id === ticket.ticket_id)?.position ?? positions[ticket.ticket_id] })));
  }, [tickets, positions, setNodes]);
  const visible = new Set((tickets ?? []).filter(ticket => status === 'all' || (status === 'inactive' ? !ticket.active : ticket.status === status)).map(ticket => ticket.ticket_id));
  const matches = (tickets ?? []).filter(ticket => visible.has(ticket.ticket_id) && `${ticket.ticket_id} ${ticket.title} ${ticket.ticket_name}`.toLowerCase().includes(query.toLowerCase()));
  const matchIds = new Set(matches.map(ticket => ticket.ticket_id));
  const edges = (tickets ?? []).flatMap(ticket => ticket.dependencies.map(dependency => ({
    id: `${dependency}-${ticket.ticket_id}`, source: dependency, target: ticket.ticket_id, type: 'smoothstep',
    hidden: !visible.has(dependency) || !visible.has(ticket.ticket_id), markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 },
  })));
  const detail = tickets?.find(ticket => ticket.ticket_id === selected);
  function select(id: string): void { if (id !== selected) setActivity(null); setSelected(id); setFocusAgent(null); }
  function locate(ticket: Ticket): void { select(ticket.ticket_id); void flow.fitView({ nodes: [{ id: ticket.ticket_id }], duration: 200, maxZoom: 1.1 }); }
  function read(alias?: string): void { setFocusAgent(alias ?? null); setExpanded(true); }
  const members = activity?.agents ?? [];
  return <>
    <header className="d-monitor-caption"><div>{sidebarButton}<span className="project-avatar">{projectName(project).slice(0, 2)}</span><strong title={project.root}>{projectName(project)}</strong><span>{expanded ? 'Agent conversations' : 'Task graph'}</span></div>
      <span role="status">{error ? 'Offline / query error' : loading ? 'Refreshing…' : 'Connected'} · {observation ? new Date(observation.updatedAt).toLocaleTimeString() : 'No graph received'}</span></header>
    {error && <div className="native-notice error" role="alert">{error}<p>{observation ? 'Showing the last successful graph. Retrying automatically.' : 'Check the directory and native GraphTraj installation.'}</p><Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Refresh now</Button></div>}
    <div className="d-monitor-content"><div className="d-monitor-views">
      <div className={`d-monitor-view ${expanded && detail ? 'concealed' : ''}`} aria-hidden={expanded && !!detail} inert={expanded && !!detail}>
        <section className={`d-map-workspace ${detail ? 'has-shelf' : ''}`}>
          <div className="d-floating-tools"><div className="new-graph-controls"><label><Icon name="search" size={15}/><input type="search" aria-label="Search tasks" placeholder="Find task or number" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && matches[0]) locate(matches[0]); }}/></label>
            <select aria-label="Task status" value={status} onChange={event => setStatus(event.target.value)}><option value="all">All statuses</option><option value="inactive">Replaced / inactive</option>{[...new Set(tickets?.map(ticket => ticket.status))].sort().map(value => <option key={value}>{value}</option>)}</select></div>
            <span className="canvas-readonly"><Button variant="ghost" onPress={() => { setNodes(previous => previous.map(node => ({ ...node, position: positions[node.id] }))); requestAnimationFrame(() => { void flow.fitView({ duration: 200 }); }); }}><Icon name="fit" size={14}/>Auto layout</Button><Icon name="eye" size={14}/>Read-only graph</span></div>
          <div className="d-canvas-title"><h1>Follow the dependencies.</h1><p>{tickets?.length ?? 0} tasks · {tickets?.filter(ticket => ticket.active).length ?? 0} active · {tickets?.filter(ticket => ticket.status === 'accepted' || ticket.status === 'integrated').length ?? 0} accepted / integrated</p></div>
          <div className="d-map-surface"><div className="map-canvas" aria-label="Task dependency graph">
            <ReactFlow nodes={nodes.map(node => ({ ...node, hidden: !visible.has(node.id), selected: selected === node.id, style: { opacity: matchIds.has(node.id) ? 1 : .16 } }))} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onNodeClick={(_, node) => select(node.id)} nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null} panActivationKeyCode={active && !expanded ? 'Space' : null} fitView fitViewOptions={{ padding: .12, maxZoom: 1 }} minZoom={.05} maxZoom={2} colorMode="light"><Background color="#d7ddd9" gap={20} size={1}/><Controls showInteractive={false}/></ReactFlow>
            <div className="map-caption"><span className="map-caption-line"/>Dependency direction <Icon name="arrow" size={14}/></div>
            {query && <div className="map-search-results" aria-label="Search results"><strong>{matches.length} matching tasks</strong>{matches.map(ticket => <button key={ticket.ticket_id} onClick={() => locate(ticket)}>#{ticket.ticket_id} {ticket.title}</button>)}</div>}
            {!tickets?.length && <div className="d-empty-configuration"><Icon name="graph" size={30}/><h2>{!observation ? loading ? 'Loading task graph…' : 'Graph unavailable' : 'No tickets registered'}</h2></div>}
          </div></div>
          {detail ? <aside className="d-task-shelf" aria-label="Ticket details"><div><h2><span className="shelf-task-id">#{detail.ticket_id}</span>{detail.title}</h2><p>{detail.ticket_name}</p><Status value={detail.status}/><span className="shelf-deps">Depends on {detail.dependencies.map(id => `#${id}`).join(', ') || 'no tasks'}</span><details className="native-ticket-facts"><summary>Ticket facts</summary><p>{detail.active ? 'Active' : 'Replaced / inactive'} · {detail.ready ? 'Ready' : 'Not ready'}<br/>Replaced by: {detail.replaced_by.join(', ') || 'None'}. Execution finishing is not acceptance.</p></details></div>
            <div><div className="shelf-team-heading"><span className="section-label">TEAM &amp; RETAINED HISTORY</span><Button variant="primary" onPress={() => read()}><Icon name="expand" size={14}/>Expand chat</Button><Button isIconOnly variant="ghost" aria-label="Close details" onPress={() => setSelected(null)}><Icon name="close" size={14}/></Button></div><MemberPills agents={members} onRead={read}/>{!members.length && <p>{activity ? activity.reason || 'No participating Agents recorded.' : 'Loading members…'}</p>}</div></aside>
            : <div className="d-canvas-hint"><Icon name="graph"/><div><strong>Select a task in the map</strong><span>Inspect its team, then open a full reading workspace.</span></div></div>}
        </section>
      </div>
      {detail && <div className={`d-monitor-view ${expanded ? '' : 'concealed'}`} aria-hidden={!expanded} inert={!expanded}><section className="new-reader d-reader" aria-label="Expanded agent conversations"><header className="d-reading-head"><Button variant="ghost" aria-label="Collapse chat" onPress={() => setExpanded(false)}><Icon name="left" size={16}/>Back to task graph</Button><span>#{detail.ticket_id}</span><h1>{detail.title}</h1><Status value={detail.status}/></header><div className="d-reading-index"><span>JUMP TO AGENT</span><MemberPills agents={members} onRead={setFocusAgent} focus={focusAgent}/></div><ActivityView key={`${projectId}:${detail.ticket_id}`} projectId={projectId} ticketId={detail.ticket_id} active={active} expanded={expanded} focusAgent={focusAgent} onActivity={setActivity}/></section></div>}
    </div></div>
  </>;
}

function ProjectIndexEditor({ preferences, busy, change, onOpen }: { preferences: Preferences; busy: boolean; change: (operation: () => Promise<Preferences>) => Promise<void>; onOpen: (id: string) => void }) {
  const [removing, setRemoving] = useState<Project | null>(null);
  return <section className="d-project-index"><header className="d-config-heading"><div><h1>Projects</h1><p>Index paths for monitoring. Removing an entry never deletes project files.</p></div><span className="memory-badge">{preferences.projects.length} indexed</span></header><div className="d-project-index-scroll"><div className="d-project-add-form"><div className="d-index-form-heading"><Icon name="folder" size={20}/><h2>Add a project</h2></div><p>Select an existing GraphTraj directory using the system folder picker.</p><Button variant="primary" isDisabled={busy} onPress={() => void change(() => window.graphtraj.addProject())}><Icon name="plus" size={15}/>Add project</Button><Button variant="ghost" isDisabled={busy} onPress={() => void change(() => window.graphtraj.projects())}>Check paths</Button></div>
    <div className="d-project-index-table"><table><thead><tr><th>Project / indexed path</th><th>Availability</th><th>Actions</th></tr></thead><tbody>{preferences.projects.map(project => <tr key={project.id}><td><strong>{projectName(project)}</strong><code>{project.root}</code></td><td><span className={`index-status ${project.unavailable ? 'unavailable' : ''}`} title={project.unavailable}>{project.unavailable ? 'Path unavailable' : 'Available'}</span></td><td><div><Button variant="ghost" isDisabled={busy} onPress={() => onOpen(project.id)}>Open</Button><Button variant="ghost" isDisabled={busy} aria-label={`Relocate ${project.root}`} onPress={() => void change(() => window.graphtraj.relocateProject(project.id))}>Relocate</Button><Button isIconOnly variant="ghost" isDisabled={busy} aria-label={`Remove ${project.root}`} onPress={() => setRemoving(project)}><Icon name="trash" size={16}/></Button></div></td></tr>)}</tbody></table>{!preferences.projects.length && <div className="d-inline-empty"><Icon name="folder" size={28}/><h3>Your project list is empty</h3><p>Add a directory above. Models remain available globally.</p></div>}</div><details className="d-index-explanation"><summary>About this project index</summary><p>Paths are stored in HOME/.graphtraj. Removing a path does not modify project files or stop running Agents.</p></details></div>
    {removing && <Dialog title={`Remove ${projectName(removing)} from the index?`} onClose={() => setRemoving(null)}><p>Only this list entry is removed. Project files, team configuration and running Agents are unchanged.</p><div className="d-delete-scope"><strong>{projectName(removing)}</strong><code>{removing.root}</code></div><div className="dialog-footer"><Button variant="secondary" onPress={() => setRemoving(null)}>Keep project</Button><Button className="destructive-button" isDisabled={busy} onPress={() => { void change(() => window.graphtraj.removeProject(removing.id)); setRemoving(null); }}>Remove index entry</Button></div></Dialog>}</section>;
}

type Destination = 'monitor' | 'models' | 'teams' | 'global-usage' | 'project-usage' | 'projects';
function FocusedDWorkbench() {
  const [destination, setDestination] = useState<Destination>('monitor');
  const [sidebarHidden, setSidebarHidden] = useState(false);
  const [globalExpanded, setGlobalExpanded] = useState(true);
  const [projectsExpanded, setProjectsExpanded] = useState(true);
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [search, setSearch] = useState('');
  const [visited, setVisited] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({ projects: [], selected: null });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(operation: () => Promise<Preferences>): Promise<void> {
    setBusy(true);
    try { const next = await operation(); setPreferences(next); setError(''); if (next.selected) setVisited(previous => [...new Set([...previous, next.selected!])]); }
    catch (error) { setError(String(error)); } finally { setBusy(false); }
  }
  useEffect(() => { void change(() => window.graphtraj.projects()); }, []);
  const project = preferences.projects.find(item => item.id === preferences.selected);
  const open = (id: string) => { void change(() => window.graphtraj.selectProject(id)); setDestination('monitor'); };
  const sidebarButton = <Button isIconOnly={!sidebarHidden} variant="ghost" aria-expanded={!sidebarHidden} aria-controls="d-project-sidebar" aria-label={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'} onPress={() => setSidebarHidden(value => !value)}><Icon name="sidebar" size={19}/>{sidebarHidden && <span>Show sidebar</span>}</Button>;
  const monitor = destination === 'monitor';
  return <div className="desktop-d"><a href="#main-content" className="skip-link">Skip to workspace</a><div className={`new-workbench d-focused-layout ${sidebarHidden ? 'sidebar-hidden' : ''}`}>
    <aside id="d-project-sidebar" className="d-focused-sidebar" aria-label="Projects" aria-hidden={sidebarHidden} inert={sidebarHidden}><header><Logo/><strong>GraphTraj</strong></header>
      <div className="d-global-navigation"><button className="d-sidebar-group-toggle" aria-expanded={globalExpanded} aria-controls="d-global-items" onClick={() => setGlobalExpanded(value => !value)}><span>GLOBAL</span><Icon name={globalExpanded ? 'down' : 'right'} size={13}/></button><div id="d-global-items" className="d-global-items" hidden={!globalExpanded}><button aria-current={destination === 'global-usage' ? 'page' : undefined} onClick={() => setDestination('global-usage')}><Icon name="usage" size={17}/><span>All project usage</span><small>{preferences.projects.length}</small></button><button className={destination === 'models' ? 'has-active-page' : ''} aria-expanded={settingsExpanded} aria-controls="d-settings-items" onClick={() => setSettingsExpanded(value => !value)}><Icon name="settings" size={17}/><span>Settings</span><Icon name={settingsExpanded ? 'down' : 'right'} size={13}/></button><div id="d-settings-items" className="d-settings-items" hidden={!settingsExpanded}><button aria-current={destination === 'models' ? 'page' : undefined} onClick={() => setDestination('models')}><Icon name="layers" size={15}/><span>Agents &amp; models</span></button></div></div></div>
      <div className="d-project-navigation"><div className="d-project-section-heading"><button className="d-sidebar-group-toggle" aria-expanded={projectsExpanded} aria-controls="d-project-items d-project-manage" onClick={() => setProjectsExpanded(value => !value)}><span>PROJECTS</span><Icon name={projectsExpanded ? 'down' : 'right'} size={13}/></button><button id="d-project-manage" className="d-project-manage" hidden={!projectsExpanded} aria-label="Manage project index" onClick={() => setDestination('projects')}><Icon name="settings" size={15}/></button></div><div id="d-project-items" hidden={!projectsExpanded}><div className="new-project-picker"><label className="new-project-search"><Icon name="search" size={14}/><input type="search" aria-label="Search projects" placeholder="Find project" value={search} onChange={event => setSearch(event.target.value)}/></label><div className="new-project-list">{preferences.projects.filter(item => item.root.toLowerCase().includes(search.toLowerCase())).map(item => <button key={item.id} className={`project-button ${project?.id === item.id ? 'selected' : ''}`} aria-current={project?.id === item.id ? 'true' : undefined} disabled={busy} title={item.root} onClick={() => open(item.id)}><span className="project-avatar">{projectName(item).slice(0, 2)}</span><span><strong>{projectName(item)}</strong><small className={item.unavailable ? 'path-unavailable' : ''}>{item.unavailable ? 'Path unavailable' : item.root}</small></span></button>)}</div>{!preferences.projects.length && <p className="sidebar-empty">{busy ? 'Loading project index…' : 'No projects indexed yet.'}</p>}<button className="new-add-project" onClick={() => setDestination('projects')}><Icon name="plus" size={15}/>Add or manage projects</button></div></div></div>
      {project && <nav className="d-current-project-nav" aria-label="Current project"><span className="section-label" title={project.root}>{projectName(project)}</span>{([['monitor','graph','Monitor'],['teams','branch','Teams & roles'],['project-usage','usage','Project usage']] as const).map(([value, icon, label]) => <button key={value} aria-current={destination === value ? 'page' : undefined} onClick={() => setDestination(value)}><Icon name={icon} size={17}/><span>{label}</span></button>)}</nav>}
      <footer><Icon name="eye" size={17}/><div><strong>Optional workspace monitor</strong><span>Closing this window does not stop tasks.</span></div></footer></aside>
    <main id="main-content" className="d-focused-stage">{error && <div className="native-notice error" role="alert">{error}</div>}
      {preferences.projects.filter(item => visited.includes(item.id)).map(item => <div className={`d-preserved-monitor monitor-page ${monitor && project?.id === item.id ? '' : 'concealed'}`} key={`${item.id}:${item.root}`} aria-hidden={!monitor || project?.id !== item.id} inert={!monitor || project?.id !== item.id}><ReactFlowProvider><GraphView project={item} active={monitor && project?.id === item.id} sidebarButton={sidebarButton}/></ReactFlowProvider></div>)}
      {monitor && !project && <div className="d-preserved-monitor"><header className="d-monitor-caption"><div>{sidebarButton}<strong>GraphTraj</strong></div></header><div className="d-empty-configuration"><Icon name="folder" size={30}/><h2>Add a project to start monitoring</h2><p>Choose an existing GraphTraj directory. Native tasks continue independently of this window.</p><Button variant="primary" onPress={() => setDestination('projects')}>Manage projects</Button></div></div>}
      {!monitor && <div className="d-auxiliary-page"><header className="d-return-header">{sidebarButton}<Button variant="ghost" onPress={() => setDestination('monitor')}><Icon name="left" size={16}/>Back to task graph</Button><span>{['models','projects','global-usage'].includes(destination) ? 'Global' : projectName(project)}</span></header>
        {destination === 'projects' ? <ProjectIndexEditor preferences={preferences} busy={busy} change={change} onOpen={open}/> : destination === 'models' ? <ConnectionsView projectId={project?.unavailable ? undefined : project?.id}/> : destination === 'global-usage' ? <UsageView projects={preferences.projects}/> : project && destination === 'project-usage' ? <UsageView key={project.id} projectId={project.id}/> : project && <SettingsView key={project.id} projectId={project.id}/>}
      </div>}
    </main></div></div>;
}
createRoot(document.getElementById('root')!).render(<FocusedDWorkbench/>);
