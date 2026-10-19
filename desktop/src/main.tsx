import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button } from '@heroui/react';
import type { DesktopAPI, Observation, Preferences, Project, Task } from '../electron/types';
import type { Activity } from '../electron/activity';
import { taskChildren, taskFocus, taskRelations, taskStatus } from './monitor-graph';
import { TaskCanvas, type TaskCanvasHandle } from './TaskCanvas';
import { ActivityView, MemberPills, MemberTree } from './Activity';
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
const projectName = (project?: Project) => project?.root.split(/[\\/]/).filter(Boolean).at(-1) || 'No project selected';

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
  const [mainExpanded, setMainExpanded] = useState(false);
  const [membersExpanded, setMembersExpanded] = useState(false);
  const [focusAgent, setFocusAgent] = useState<string | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [activityError, setActivityError] = useState('');
  const [activityRetry, setActivityRetry] = useState(0);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const canvas = useRef<TaskCanvasHandle>(null);
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
  const tasks = observation?.graph.tasks;
  const nativeGraph = observation?.graph ?? { tasks: [] };
  const children = taskChildren(nativeGraph);
  const groups = (tasks ?? []).filter(task => children.get(task.task_id)?.length);
  const graphActive = active && !mainExpanded && !membersExpanded && !(expanded && selected);
  function fitGraph(): void { canvas.current?.fit(); }
  const visible = new Set((tasks ?? []).filter(task => status === 'all' || (status === 'inactive' ? !task.active : taskStatus(task) === status)).map(task => task.task_id));
  const matches = (tasks ?? []).filter(task => visible.has(task.task_id) && `${task.task_id} ${task.title} ${task.task_name}`.toLowerCase().includes(query.toLowerCase()));
  const matchIds = new Set(matches.map(task => task.task_id));
  const detail = tasks?.find(task => task.task_id === selected);
  const focus = taskFocus(nativeGraph, selected);
  const focusedEdges = selected ? taskRelations(nativeGraph)
    .filter(edge => focus.has(edge.source) && focus.has(edge.target)) : [];
  function select(id: string | null): void { if (id !== selected) { setActivity(null); setActivityError(''); } setSelected(id); setFocusAgent(null); }
  function toggleSummary(id: string): void {
    setOpenGroups(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  function locate(task: Task): void {
    // Search is an explicit reveal action. Ordinary card selection never opens ancestors.
    const ancestors: string[] = [];
    let parent = task.parent_id;
    while (parent) { ancestors.push(parent); parent = tasks?.find(item => item.task_id === parent)?.parent_id; }
    setOpenGroups(previous => new Set([...previous, ...ancestors]));
    select(task.task_id);
    canvas.current?.locate(task.task_id);
  }
  function read(alias?: string): void { setFocusAgent(alias ?? null); setExpanded(true); }
  const members = activity?.agents ?? [];
  return <>
    <header className="d-monitor-caption"><div>{sidebarButton}<span className="project-avatar">{projectName(project).slice(0, 2)}</span><strong title={project.root}>{projectName(project)}</strong><span>{mainExpanded ? 'Main conversations' : membersExpanded ? 'Agent members' : expanded ? 'Agent conversations' : 'Task graph'}</span></div>
      <Button variant="ghost" aria-pressed={membersExpanded} onPress={() => setMembersExpanded(true)}>Members</Button><Button variant="ghost" aria-pressed={mainExpanded} onPress={() => setMainExpanded(true)}>Main sessions</Button><span role="status">{error ? 'Offline / query error' : loading ? 'Refreshing…' : 'Connected'} · {observation ? new Date(observation.updatedAt).toLocaleTimeString() : 'No graph received'}</span></header>
    {error && <div className="native-notice error" role="alert">{error}<p>{observation ? 'Showing the last successful graph. Retrying automatically.' : 'Check the directory and native GraphTraj installation.'}</p><Button variant="ghost" onPress={() => setRetry(value => value + 1)}>Refresh now</Button></div>}
    <div className="d-monitor-content"><div className="d-monitor-views">
      <div className={`d-monitor-view ${mainExpanded || membersExpanded || expanded && detail ? 'concealed' : ''}`} aria-hidden={mainExpanded || membersExpanded || expanded && !!detail} inert={mainExpanded || membersExpanded || expanded && !!detail}>
        <section className={`d-map-workspace ${detail ? 'has-shelf' : ''}`}>
          <div className="d-floating-tools"><div className="new-graph-controls"><label><Icon name="search" size={15}/><input type="search" aria-label="Search tasks" placeholder="Find task or number" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && matches[0]) locate(matches[0]); }}/></label>
            <select aria-label="Task status" value={status} onChange={event => setStatus(event.target.value)}><option value="all">All statuses</option><option value="inactive">Replaced / inactive</option>{[...new Set(tasks?.map(task => taskStatus(task)))].sort().map(value => <option key={value}>{value}</option>)}</select></div>
            <span className="canvas-readonly"><Button variant="ghost" onPress={() => { select(null); setOpenGroups(new Set()); requestAnimationFrame(fitGraph); }}>Overview</Button><Button variant="ghost" onPress={fitGraph}><Icon name="fit" size={14}/>Fit graph</Button><Icon name="eye" size={14}/>Read-only graph</span></div>
          <div className="d-canvas-title"><h1>Task summaries and dependencies</h1><p>{tasks?.length ?? 0} tasks · {groups.length} summaries · {matches.length} matching tasks</p>
            {!!groups.length && <select aria-label="Selected summary" value={groups.some(task => task.task_id === selected) ? selected! : ''} onChange={event => select(event.target.value || null)}><option value="">Select a summary</option>{groups.map(task => <option key={task.task_id} value={task.task_id}>{task.title} · #{task.task_id}</option>)}</select>}</div>
          <div className="d-map-surface"><div className="map-canvas" aria-label="Task dependency graph">
            <TaskCanvas ref={canvas} projectName={projectName(project)} graph={nativeGraph} expanded={openGroups} selected={selected} matches={matchIds} active={graphActive} select={select} toggle={toggleSummary}/>
            <div className="map-caption"><span className="map-caption-line"/>Boundary = membership · Solid = dependency · Dashed = replacement · Arc = crossing · Hover for real endpoints <Icon name="arrow" size={14}/></div>
            {query && <div className="map-search-results" aria-label="Search results"><strong>{matches.length} matching tasks</strong>{matches.map(task => <button key={task.task_id} onClick={() => locate(task)}>#{task.task_id} {task.title}</button>)}</div>}
            {!tasks?.length && <div className="d-empty-configuration"><Icon name="graph" size={30}/><h2>{!observation ? loading ? 'Loading task graph…' : 'Graph unavailable' : 'No tasks registered'}</h2></div>}
            {!!tasks?.length && !matches.length && <div className="graph-filter-empty" role="status">No tasks match these filters. <Button variant="ghost" onPress={() => { setQuery(''); setStatus('all'); }}>Clear filters</Button></div>}
          </div></div>
          {detail ? <aside className="d-task-shelf" aria-label="Task details"><div><h2><span className="shelf-task-id">#{detail.task_id}</span>{detail.title}</h2><p>{detail.task_name}</p><Status value={taskStatus(detail)}/><span className="shelf-deps">Depends on {detail.dependencies.map(id => `#${id}`).join(', ') || 'no tasks'}</span><details className="native-delivery-facts"><summary>Delivery evidence · {detail.delivery?.length ?? 0} records</summary>{detail.delivery?.map(fact => <div key={fact.event_id}><p>{fact.task_id !== detail.task_id ? <button onClick={() => select(fact.task_id)}>Accepted in #{fact.task_id} · {tasks?.find(task => task.task_id === fact.task_id)?.title}</button> : fact.dev_commit ? `Integrated commit ${fact.dev_commit}` : 'Own acceptance recorded'}</p><p>{fact.event_id}<br/>{fact.reason}{fact.accepted_definition && <><br/>Accepted definition: {fact.accepted_definition}</>}</p><ul>{fact.evidence_refs.map(ref => <li key={ref}>{ref}</li>)}</ul></div>)}{!detail.delivery?.length && <p>No current delivery evidence available.</p>}</details><p>Parent: {detail.parent_id ? <button onClick={() => select(detail.parent_id!)}>#{detail.parent_id}</button> : 'Project'}</p><details className="native-task-facts"><summary>Task facts</summary><p>{detail.active ? 'Active' : 'Replaced / inactive'} · {detail.ready ? 'Ready' : 'Not ready'}<br/>Historical execution: {detail.status}.<br/>Replaced by: {detail.replaced_by.join(', ') || 'None'}. Execution finishing is not acceptance.</p></details>{!!focusedEdges.length && <details className="native-dependency-list"><summary>{focusedEdges.length} related relationships · real endpoints</summary>{focusedEdges.map(edge => <div key={`${edge.kind}:${edge.source}:${edge.target}`}>#{edge.source} {tasks?.find(task => task.task_id === edge.source)?.title} {edge.kind === 'replacement' ? 'replaced by' : edge.kind === 'acceptance' ? 'accepted into' : '→'} #{edge.target} {tasks?.find(task => task.task_id === edge.target)?.title}</div>)}</details>}</div>
            <div><div className="shelf-team-heading"><span className="section-label">TEAM &amp; RETAINED HISTORY</span><Button variant="primary" onPress={() => read()}><Icon name="expand" size={14}/>Expand chat</Button><Button isIconOnly variant="ghost" aria-label="Close details" onPress={() => setSelected(null)}><Icon name="close" size={14}/></Button></div><MemberPills agents={members} onRead={read}/>{activityError ? <div role="alert">{activityError} <Button variant="ghost" onPress={() => setActivityRetry(value => value + 1)}>Retry now</Button></div> : !members.length && <p>{activity ? activity.reason || 'No participating Agents recorded.' : 'Loading members…'}</p>}</div></aside>
            : null}
        </section>
      </div>
      {detail && <div className={`d-monitor-view ${expanded && !mainExpanded && !membersExpanded ? '' : 'concealed'}`} aria-hidden={!expanded || mainExpanded || membersExpanded} inert={!expanded || mainExpanded || membersExpanded}><section className="new-reader d-reader" aria-label="Expanded agent conversations"><header className="d-reading-head"><Button variant="ghost" aria-label="Collapse chat" onPress={() => setExpanded(false)}><Icon name="left" size={16}/>Back to task graph</Button><span>#{detail.task_id}</span><h1>{detail.title}</h1><Status value={taskStatus(detail)}/></header><div className="d-reading-index"><span>JUMP TO AGENT</span><MemberPills agents={members} onRead={setFocusAgent} focus={focusAgent}/></div><ActivityView key={`${projectId}:${detail.task_id}`} projectId={projectId} taskId={detail.task_id} active={active && !mainExpanded && !membersExpanded} expanded={expanded} focusAgent={focusAgent} onActivity={setActivity} onError={setActivityError} refreshKey={activityRetry}/></section></div>}
      <div className={`d-monitor-view ${membersExpanded && !mainExpanded ? '' : 'concealed'}`} aria-hidden={!membersExpanded || mainExpanded} inert={!membersExpanded || mainExpanded}><section className="new-reader d-reader" aria-label="Agent members"><header className="d-reading-head"><Button variant="ghost" aria-label="Collapse members" onPress={() => setMembersExpanded(false)}><Icon name="left" size={16}/>{expanded && detail ? 'Back to agent conversations' : 'Back to task graph'}</Button><h1>Agent members</h1></header><MemberTree projectId={projectId} summaries={groups} active={active && membersExpanded && !mainExpanded} onRead={member => { select(member.task_id); setFocusAgent(member.alias); setExpanded(true); setMembersExpanded(false); }}/></section></div>
      <div className={`d-monitor-view ${mainExpanded ? '' : 'concealed'}`} aria-hidden={!mainExpanded} inert={!mainExpanded}><section className="new-reader d-reader" aria-label="Main conversations"><header className="d-reading-head"><Button variant="ghost" aria-label="Collapse Main chat" onPress={() => setMainExpanded(false)}><Icon name="left" size={16}/>{expanded && detail ? 'Back to agent conversations' : 'Back to task graph'}</Button><h1>Main sessions</h1></header><ActivityView projectId={projectId} active={active && mainExpanded}/></section></div>
    </div></div>
  </>;
}

function ProjectIndexEditor({ preferences, busy, change, onOpen }: { preferences: Preferences; busy: boolean; change: (operation: () => Promise<Preferences>) => Promise<void>; onOpen: (id: string) => void }) {
  const [removing, setRemoving] = useState<Project | null>(null);
  return <section className="d-project-index"><header className="d-config-heading"><div><h1>Projects</h1><p>Index paths for monitoring. Removing an entry never deletes project files.</p></div><span className="memory-badge">{preferences.projects.length} indexed</span></header><div className="d-project-index-scroll"><div className="d-project-add-form"><div className="d-index-form-heading"><Icon name="folder" size={20}/><h2>Add a project</h2></div><p>Select an existing GraphTraj directory using the system folder picker.</p><Button variant="primary" isDisabled={busy} onPress={() => void change(() => window.graphtraj.addProject())}><Icon name="plus" size={15}/>Add project</Button><Button variant="ghost" isDisabled={busy} onPress={() => void change(() => window.graphtraj.projects(true))}>Check paths</Button></div>
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
  const [modelsVisited, setModelsVisited] = useState(false);
  const [teamsVisited, setTeamsVisited] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({ projects: [], selected: null });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(operation: () => Promise<Preferences>): Promise<void> {
    setBusy(true);
    try { const next = await operation(); setPreferences(next); setError(''); if (next.selected) setVisited(previous => [...new Set([...previous, next.selected!])]); }
    catch (error) { setError(String(error)); } finally { setBusy(false); }
  }
  useEffect(() => {
    let alive = true;
    void change(() => window.graphtraj.projects()).then(() => {
      if (alive) void window.graphtraj.projects(true).then(next => {
        if (alive) setPreferences(next);
      }).catch(error => { if (alive) setError(String(error)); });
    });
    return () => { alive = false; };
  }, []);
  const project = preferences.projects.find(item => item.id === preferences.selected);
  const open = (id: string) => { void change(() => window.graphtraj.selectProject(id)); setDestination('monitor'); };
  const sidebarButton = <Button isIconOnly={!sidebarHidden} variant="ghost" aria-expanded={!sidebarHidden} aria-controls="d-project-sidebar" aria-label={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'} onPress={() => setSidebarHidden(value => !value)}><Icon name="sidebar" size={19}/>{sidebarHidden && <span>Show sidebar</span>}</Button>;
  useEffect(() => {
    if (destination === 'models') setModelsVisited(true);
    if (destination === 'teams' && project) setTeamsVisited(previous => [...new Set([...previous, project.id])]);
  }, [destination, project?.id]);
  const monitor = destination === 'monitor';
  const returnHeader = (context: string) => <header className="d-return-header">{sidebarButton}<Button variant="ghost" onPress={() => setDestination('monitor')}><Icon name="left" size={16}/>Back to task graph</Button><span>{context}</span></header>;
  return <div className="desktop-d"><a href="#main-content" className="skip-link">Skip to workspace</a><div className={`new-workbench d-focused-layout ${sidebarHidden ? 'sidebar-hidden' : ''}`}>
    <aside id="d-project-sidebar" className="d-focused-sidebar" aria-label="Projects" aria-hidden={sidebarHidden} inert={sidebarHidden}><header><Logo/><strong>GraphTraj</strong></header>
      <div className="d-global-navigation"><button className="d-sidebar-group-toggle" aria-expanded={globalExpanded} aria-controls="d-global-items" onClick={() => setGlobalExpanded(value => !value)}><span>GLOBAL</span><Icon name={globalExpanded ? 'down' : 'right'} size={13}/></button><div id="d-global-items" className="d-global-items" hidden={!globalExpanded}><button aria-current={destination === 'global-usage' ? 'page' : undefined} onClick={() => setDestination('global-usage')}><Icon name="usage" size={17}/><span>All project usage</span><small>{preferences.projects.length}</small></button><button className={destination === 'models' ? 'has-active-page' : ''} aria-expanded={settingsExpanded} aria-controls="d-settings-items" onClick={() => setSettingsExpanded(value => !value)}><Icon name="settings" size={17}/><span>Settings</span><Icon name={settingsExpanded ? 'down' : 'right'} size={13}/></button><div id="d-settings-items" className="d-settings-items" hidden={!settingsExpanded}><button aria-current={destination === 'models' ? 'page' : undefined} onClick={() => setDestination('models')}><Icon name="layers" size={15}/><span>Agents &amp; models</span></button></div></div></div>
      <div className="d-project-navigation"><div className="d-project-section-heading"><button className="d-sidebar-group-toggle" aria-expanded={projectsExpanded} aria-controls="d-project-items d-project-manage" onClick={() => setProjectsExpanded(value => !value)}><span>PROJECTS</span><Icon name={projectsExpanded ? 'down' : 'right'} size={13}/></button><button id="d-project-manage" className="d-project-manage" hidden={!projectsExpanded} aria-label="Manage project index" onClick={() => setDestination('projects')}><Icon name="settings" size={15}/></button></div><div id="d-project-items" hidden={!projectsExpanded}><div className="new-project-picker"><label className="new-project-search"><Icon name="search" size={14}/><input type="search" aria-label="Search projects" placeholder="Find project" value={search} onChange={event => setSearch(event.target.value)}/></label><div className="new-project-list">{preferences.projects.filter(item => item.root.toLowerCase().includes(search.toLowerCase())).map(item => <button key={item.id} className={`project-button ${project?.id === item.id ? 'selected' : ''}`} aria-current={project?.id === item.id ? 'true' : undefined} disabled={busy} title={item.root} onClick={() => open(item.id)}><span className="project-avatar">{projectName(item).slice(0, 2)}</span><span><strong>{projectName(item)}</strong><small className={item.unavailable ? 'path-unavailable' : ''}>{item.unavailable ? 'Path unavailable' : item.root}</small></span></button>)}</div>{!preferences.projects.length && <p className="sidebar-empty">{busy ? 'Loading project index…' : 'No projects indexed yet.'}</p>}<button className="new-add-project" onClick={() => setDestination('projects')}><Icon name="plus" size={15}/>Add or manage projects</button></div></div></div>
      {project && <nav className="d-current-project-nav" aria-label="Current project"><span className="section-label" title={project.root}>{projectName(project)}</span>{([['monitor','graph','Monitor'],['teams','branch','Teams & roles'],['project-usage','usage','Project usage']] as const).map(([value, icon, label]) => <button key={value} aria-current={destination === value ? 'page' : undefined} onClick={() => setDestination(value)}><Icon name={icon} size={17}/><span>{label}</span></button>)}</nav>}
      <footer><Icon name="eye" size={17}/><div><strong>Optional workspace monitor</strong><span>Closing this window does not stop tasks.</span></div></footer></aside>
    <main id="main-content" className="d-focused-stage">{error && <div className="native-notice error" role="alert">{error}</div>}
      {preferences.projects.filter(item => visited.includes(item.id)).map(item => <div className={`d-preserved-monitor monitor-page ${monitor && project?.id === item.id ? '' : 'concealed'}`} key={`${item.id}:${item.root}`} aria-hidden={!monitor || project?.id !== item.id} inert={!monitor || project?.id !== item.id}><GraphView project={item} active={monitor && project?.id === item.id} sidebarButton={sidebarButton}/></div>)}
      {monitor && !project && <div className="d-preserved-monitor"><header className="d-monitor-caption"><div>{sidebarButton}<strong>GraphTraj</strong></div></header><div className="d-empty-configuration"><Icon name="folder" size={30}/><h2>Add a project to start monitoring</h2><p>Choose an existing GraphTraj directory. Native tasks continue independently of this window.</p><Button variant="primary" onPress={() => setDestination('projects')}>Manage projects</Button></div></div>}
      {modelsVisited && <div className={`d-auxiliary-page ${destination === 'models' ? '' : 'concealed'}`} aria-hidden={destination !== 'models'} inert={destination !== 'models'}>{returnHeader('Global')}<ConnectionsView/></div>}
      {preferences.projects.filter(item => teamsVisited.includes(item.id)).map(item => <div key={`${item.id}:${item.root}`} className={`d-auxiliary-page ${destination === 'teams' && project?.id === item.id ? '' : 'concealed'}`} aria-hidden={destination !== 'teams' || project?.id !== item.id} inert={destination !== 'teams' || project?.id !== item.id}>{returnHeader(projectName(item))}<SettingsView projectId={item.id} onModels={() => { setDestination('models'); setSettingsExpanded(true); }} active={destination === 'teams' && project?.id === item.id}/></div>)}
      {!monitor && destination !== 'models' && destination !== 'teams' && <div className="d-auxiliary-page">{returnHeader(destination === 'project-usage' ? projectName(project) : 'Global')}
        {destination === 'projects' ? <ProjectIndexEditor preferences={preferences} busy={busy} change={change} onOpen={open}/> : destination === 'global-usage' ? <UsageView projects={preferences.projects}/> : project && <UsageView key={project.id} projectId={project.id}/>}
      </div>}
    </main></div></div>;
}
createRoot(document.getElementById('root')!).render(<FocusedDWorkbench/>);
