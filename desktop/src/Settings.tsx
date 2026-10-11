import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button, Description, Input, Label, TextField } from '@heroui/react';
import type { Connections, RoleFields, RoleTree, Settings } from '../electron/types';
import { branchRoles, treeEdges, moveNode, removeNodes, fieldLabels as labels, ownRole, roleChanges, roleName } from './settings-draft';
import { Dialog, Field, Icon } from './ui';

/** Edit a project-local draft; only the native save entry can persist it. */
export function SettingsView({ projectId, active = true }: { projectId: string; active?: boolean }) {
  const [review, setReview] = useState(false);
  const [adding, setAdding] = useState<'team' | 'child' | 'root' | null>(null);
  const [deleting, setDeleting] = useState<'team' | 'agent' | null>(null);
  const [deleteMode, setDeleteMode] = useState<'branch' | 'keep'>('branch');
  const [promoted, setPromoted] = useState('');
  const canvas = useRef<HTMLDivElement>(null);
  const [saved, setSaved] = useState<Settings | null>(null);
  const [roles, setRoles] = useState<Record<string, RoleFields>>({});
  const [renames, setRenames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState('');
  const [tree, setTree] = useState<RoleTree>({});
  const [team, setTeam] = useState('');
  const [teamName, setTeamName] = useState('');
  const [teamRenames, setTeamRenames] = useState<Record<string, string>>({});
  const [nodeName, setNodeName] = useState('');
  const [newModel, setNewModel] = useState('');
  const [newRuntime, setNewRuntime] = useState('codex');
  const [connections, setConnections] = useState<Connections>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { if (!message) return; const timer = setTimeout(() => setMessage(''), 4500); return () => clearTimeout(timer); }, [message]);

  function reset(value: Settings): void {
    setSaved(value); setRoles(structuredClone(value.roles)); setTree(value.role_tree); setRenames({}); setTeamRenames({});
    setTeam(current => Object.keys(value.roles).some(ref => group(ref) === current) ? current : group(Object.keys(value.roles)[0] ?? ''));
    setSelected(current => Object.hasOwn(value.roles, current) ? current : Object.keys(value.roles).find(ref => group(ref) === team) ?? Object.keys(value.roles)[0] ?? '');
  }
  useEffect(() => {
    let alive = true;
    setBusy(true);
    window.graphtraj.settings(projectId).then(value => { if (alive) reset(value); })
      .catch(error => { if (alive) setError(String(error)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [projectId]);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    window.graphtraj.connections(projectId, { action: 'read' }).then(value => { if (alive) setConnections(value); }).catch(() => { /* Inline roles remain editable if the catalog is unavailable. */ });
    return () => { alive = false; };
  }, [projectId, active]);

  const { edits, changes } = roleChanges(roles, saved?.roles);
  const names = Object.fromEntries(Object.entries(renames).filter(([old, name]) => old !== name));
  for (const [old, name] of Object.entries(names)) changes.push({ label: 'Role name', before: old, after: name });
  const removed = Object.keys(saved?.roles ?? {}).filter(ref => !Object.hasOwn(roles, ref));
  for (const ref of removed) changes.push({ label: 'Delete role', before: ref, after: '(removed)' });
  if (JSON.stringify(tree) !== JSON.stringify(saved?.role_tree ?? {})) changes.push({ label: 'Organization tree', before: JSON.stringify(saved?.role_tree), after: JSON.stringify(tree) });
  const teams = [...new Set(Object.keys(roles).map(group))];
  const edges = treeEdges(tree);
  const availableConnections = Object.entries(connections?.catalog.runtimes ?? {}).flatMap(([runtime, entry]) =>
    Object.entries(entry.providers).flatMap(([provider, value]) => Object.entries(value.models).map(([model, metadata]) => ({
      reference: `${runtime}/${provider}/${model}`, metadata,
    }))));
  const selectedConnection = ownRole(roles, selected)?.connection;
  const selectedModel = availableConnections.find(item => item.reference === selectedConnection)?.metadata;
  const teamRoles = Object.keys(roles).filter(ref => group(ref) === team);
  function group(ref: string): string { return ref.includes('.') ? ref.split('.')[0] : ''; }
  function isTeamRoot(ref: string): boolean {
    const occurs = Object.hasOwn(tree, ref) || edges.some(edge => edge[1] === ref);
    return occurs && !edges.some(([parent, child]) => child === ref && group(parent) === group(ref));
  }
  function attempt(action: () => void): void {
    try { action(); setError(''); setMessage(''); } catch (error) { setError(String(error)); }
  }
  function addNode(newTeam: boolean, child: boolean): void {
    const targetTeam = newTeam ? teamName : team;
    if (newTeam && (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(targetTeam) || teams.some(name => name === targetTeam || ownRole(teamRenames, name) === targetTeam))) throw new Error('Choose a new lowercase team name.');
    if (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(nodeName) || !newModel.trim()) throw new Error('Enter a lowercase Agent name and a model.');
    if (!newTeam && !child && teamRoles.some(ref => isTeamRoot(ref))) throw new Error('This team already has a root. Add a child or adjust the parent.');
    const reference = targetTeam ? `${targetTeam}.${nodeName}` : nodeName;
    if (Object.hasOwn(roles, reference)) throw new Error('Agent name already exists.');
    setRoles(current => ({ ...current, [reference]: { runtime: newRuntime, model: newModel } }));
    if (newTeam) setTeamRenames(current => Object.fromEntries(Object.entries(current).filter(([name]) => name !== targetTeam)));
    else if (ownRole(teamRenames, team)) setRenames(current => ({ ...current, [reference]: `${teamRenames[team]}.${nodeName}` }));
    setTree(moveNode(tree, reference, child ? selected : '')); setSelected(reference); setTeam(targetTeam); setNodeName('');
  }
  function deleteNode(reconnect: boolean): void {
    const affected = reconnect ? new Set([selected]) : branchRoles(tree, selected);
    if (reconnect && isTeamRoot(selected) && new Set(edges.filter(edge => edge[0] === selected).map(edge => edge[1])).size > 1) throw new Error('A root with several children cannot be reconnected to one root. Reparent the children first or delete the whole branch.');
    setTree(removeNodes(tree, affected, reconnect));
    setRoles(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref))));
    setRenames(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref)))); setSelected('');
  }
  async function reload(): Promise<void> {
    setBusy(true); setError('');
    try { reset(await window.graphtraj.settings(projectId)); setMessage('Loaded current configuration. Draft discarded.'); }
    catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  async function save(): Promise<void> {
    if (!saved) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const next = await window.graphtraj.saveSettings(projectId, {
        revision: saved.revision, edits, renames: names,
        add_edges: [], remove_edges: [], remove_presets: removed, role_tree: tree,
      });
      reset(next); setReview(false); setMessage(next.applied ? 'Settings saved.' : 'No changes to save.');
    } catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  function field(name: keyof RoleFields, multiline = false) {
    const value = ownRole(roles, selected)?.[name] ?? '';
    if (multiline) return <label className="native-field" key={name}><span>{labels[name]}</span><textarea aria-label={labels[name]} rows={4} value={value} disabled={busy} onChange={event => { const text = event.target.value; setMessage(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), [name]: text } })); }}/>{name === 'developer_prompt' && <small>Supported by Codex. Clear this layer for Pi or DSH.</small>}</label>;
    return <TextField className="settings-field" key={name} value={value} isDisabled={busy}
      onChange={value => { setMessage(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), [name]: value } })); }}>
      <Label>{labels[name]}</Label>
      <Input autoComplete="off" spellCheck={false} />
      {name === 'api_key_env' && <Description>Environment variable NAME only, for example OPENAI_API_KEY. Set the secret in the environment used to launch your Runtime; this form never reads or saves its value.</Description>}
      {name === 'base_url' && <Description>Optional HTTP(S) endpoint. Leave blank for Runtime defaults. Pi uses its native provider configuration.</Description>}
      {name === 'runtime' && <Description>codex, pi or dsh. Pi models use provider/model-id.</Description>}
      {name === 'reasoning_effort' && <Description>Use a level supported by the selected Runtime, or leave blank for its default.</Description>}
      {name === 'instructions' && <Description>Existing UTF-8 file path, relative to the project or absolute. File contents are not edited here.</Description>}
      {name === 'developer_prompt' && <Description>Supported by Codex. Clear this layer for Pi or DSH.</Description>}
    </TextField>;
  }
  const selectedRole = ownRole(roles, selected);
  const route = (selectedRole?.connection ?? '').split('/');
  const runtimeEntries = connections?.catalog.runtimes ?? {};
  const routeRuntime = runtimeEntries[route[0]];
  const routeProvider = routeRuntime?.providers[route[1]];
  function chooseConnection(connection: string): void {
    setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), connection: connection || null,
      runtime: connection ? null : 'codex', model: connection ? null : '', base_url: null, api_key_env: null } }));
  }
  function drawNode(ref: string, ancestors = new Set<string>()): ReactNode {
    if (ancestors.has(ref)) return null;
    const nextAncestors = new Set([...ancestors, ref]);
    const children = [...new Set(edges.filter(edge => edge[0] === ref && group(edge[1]) === team).map(edge => edge[1]))];
    const value = ownRole(roles, ref);
    const binding = availableConnections.find(item => item.reference === value?.connection);
    return <li key={ref}><button data-config-agent={ref} className={`d-org-node ${selected === ref ? 'selected' : ''}`} aria-label={`Configure agent ${roleName(renames, ref)}`} aria-pressed={selected === ref} onClick={() => setSelected(ref)}><span className="d-org-role"><Icon name={isTeamRoot(ref) ? 'branch' : 'terminal'} size={15}/>{isTeamRoot(ref) ? 'Team root' : 'Agent'}</span><strong>{roleName(renames, ref).split('.').at(-1)}</strong><small title={value?.connection ?? undefined}>{value?.connection ? `${routeFor(value.connection)} · ${binding?.metadata.alias || binding?.metadata.id || 'Missing model'}` : `${value?.runtime || 'Runtime default'} · ${value?.model || 'Model not recorded'}`}</small><span className="d-org-child-count">{value?.reasoning_effort || 'Default'} effort · {children.length} children</span></button>{children.length > 0 && <ul>{children.map(child => drawNode(child, nextAncestors))}</ul>}</li>;
  }
  function routeFor(connection: string): string { return connection.split('/')[0]; }
  useEffect(() => { const node = [...(canvas.current?.querySelectorAll<HTMLElement>('[data-config-agent]') ?? [])].find(item => item.dataset.configAgent === selected); node?.scrollIntoView?.({ block: 'nearest', inline: 'center' }); }, [selected, team]);
  const roots = teamRoles.filter(ref => !edges.some(([parent, child]) => child === ref && group(parent) === team));
  function removeConfiguration(): void {
    if (deleting === 'team') {
      const affected = new Set(teamRoles);
      setTree(removeNodes(tree, affected, true));
      setRoles(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref))));
      setRenames(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref)))); setSelected('');
      setTeam(teams.find(name => name !== team) ?? '');
    } else if (deleteMode === 'keep' && isTeamRoot(selected)) {
      const children = [...new Set(edges.filter(([parent]) => parent === selected).map(([, child]) => child))];
      if (children.length > 1) {
        if (!children.includes(promoted)) throw new Error('Choose a direct child to become the new root.');
        let next = tree;
        for (const child of children.filter(ref => ref !== promoted)) next = moveNode(next, child, promoted);
        setTree(removeNodes(next, new Set([selected]), true));
        setRoles(current => Object.fromEntries(Object.entries(current).filter(([ref]) => ref !== selected)));
        setRenames(current => Object.fromEntries(Object.entries(current).filter(([ref]) => ref !== selected))); setSelected(promoted);
      } else deleteNode(true);
    } else deleteNode(deleteMode === 'keep');
    setDeleting(null);
  }
  return <section className="d-team-editor" aria-label="Project settings"><header className="d-config-heading"><div><h1>Teams &amp; roles</h1><p>Configure this project’s organization. Running agents are unchanged.</p></div><span className="memory-badge"><Icon name="shield" size={15}/>Configuration draft</span></header>
    {error && <div className="native-notice error" role="alert">{error}<p>Your draft is retained. Reload to resolve an external change.</p></div>}
    {busy && <p className="native-notice" role="status">Waiting for native settings / approval…</p>}{message && <div className="toast" role="status"><Icon name="check"/>{message}</div>}
    <nav className="d-team-tabs" aria-label="Project teams">{teams.map(name => <button key={name} aria-current={team === name ? 'true' : undefined} onClick={() => { setTeam(name); setSelected(Object.keys(roles).find(ref => group(ref) === name) ?? ''); }}><Icon name="branch" size={15}/><span>{ownRole(teamRenames, name) ?? (name || 'Ungrouped roles')}</span><small>{Object.keys(roles).filter(ref => group(ref) === name).length}</small></button>)}<Button variant="ghost" isDisabled={busy || !saved} onPress={() => { setAdding('team'); setTeamName(''); }}><Icon name="plus" size={15}/>Add team</Button>{teamRoles.length > 0 && <Button variant="ghost" className="d-delete-team" isDisabled={busy} onPress={() => setDeleting('team')}><Icon name="trash" size={15}/>Delete team</Button>}</nav>
    {!teams.length ? <div className="d-empty-configuration"><Icon name="branch" size={30}/><h2>{busy ? 'Loading teams…' : 'No teams configured'}</h2><p>Add a team and start with one root agent. Build its organization one child at a time.</p><Button variant="primary" isDisabled={busy || !saved} onPress={() => setAdding('team')}>Add first team</Button></div> : <div className="d-team-editor-body"><div className="d-org-workspace"><header><div><label>Team name<input aria-label="Team name" disabled={busy || !team} value={ownRole(teamRenames, team) ?? (team || 'Ungrouped roles')} onChange={event => {
      const value = event.target.value; setTeamRenames(current => ({ ...current, [team]: value }));
      setRenames(current => ({ ...current, ...Object.fromEntries(teamRoles.map(ref => [ref, `${value}.${roleName(renames, ref).split('.').pop()}`])) }));
    }}/></label></div><Button variant="secondary" isDisabled={busy} onPress={() => setAdding(selectedRole ? 'child' : 'root')}><Icon name="plus" size={15}/>{selectedRole ? 'Add child agent' : 'Add root agent'}</Button></header><div ref={canvas} className="d-org-canvas" role="region" aria-label="Team organization tree" tabIndex={0}><div className="d-org-tree"><ul>{roots.map(ref => drawNode(ref))}</ul></div></div><footer><Icon name="info" size={15}/><span>Select a parent to add a child. Reconnect an existing agent using its parent field.</span></footer></div>
      {selectedRole ? <aside className="d-agent-properties"><header><div><h2>{roleName(renames, selected).split('.').at(-1)}</h2><span>{isTeamRoot(selected) ? 'Root agent configuration' : 'Child agent configuration'}</span></div><Button isIconOnly variant="ghost" aria-label="Delete selected agent configuration" isDisabled={busy} onPress={() => { setDeleting('agent'); setDeleteMode('branch'); setPromoted(edges.find(([parent]) => parent === selected)?.[1] ?? ''); }}><Icon name="trash" size={16}/></Button></header><fieldset disabled={busy} className="config-property-scroll"><div className="new-config-fields"><TextField className="settings-field" value={roleName(renames, selected)} onChange={name => setRenames(current => ({ ...current, [selected]: name }))}><Label>Role reference</Label><Input/><Description>Name or group.name. Renaming updates dispatch references.</Description></TextField>
        <fieldset className="d-agent-model-fields"><legend>Model for this agent</legend><div className="d-agent-route-row"><label className="native-field"><span>Runtime</span><select aria-label="Agent Runtime" value={selectedRole.connection ? route[0] : ''} onChange={event => { const next = availableConnections.find(item => item.reference.startsWith(event.target.value + '/')); chooseConnection(event.target.value && next ? next.reference : ''); }}><option value="">Inline Runtime</option>{Object.entries(runtimeEntries).map(([id, value]) => <option key={id} value={id} disabled={!Object.values(value.providers).some(provider => Object.keys(provider.models).length)}>{id}</option>)}</select></label><label className="native-field"><span>Provider</span><select aria-label="Agent provider" value={route[1] ?? ''} disabled={!selectedRole.connection} onChange={event => { const next = availableConnections.find(item => item.reference.startsWith(`${route[0]}/${event.target.value}/`)); if (next) chooseConnection(next.reference); }}><option value="">Runtime default</option>{Object.entries(routeRuntime?.providers ?? {}).map(([id, value]) => <option key={id} value={id} disabled={!Object.keys(value.models).length}>{id}</option>)}</select></label></div>
          {selectedRole.connection ? <label className="native-field"><span>Model</span><select aria-label="Global connection" value={selectedRole.connection} onChange={event => chooseConnection(event.target.value)}>{Object.entries(routeProvider?.models ?? {}).map(([id, value]) => <option key={id} value={`${route[0]}/${route[1]}/${id}`}>{value.alias || value.id}</option>)}{!selectedModel && <option value={selectedRole.connection}>{selectedRole.connection} · unavailable</option>}</select><small>{selectedModel?.source || 'Unknown source'} · Supported efforts: {selectedModel?.supported_efforts?.join(' · ') || 'Unknown'}</small></label> : <>{field('runtime')}{field('model')}<details className="d-prompt-layers"><summary>Inline provider route</summary>{field('base_url')}{field('api_key_env')}</details></>}
          {field('reasoning_effort')}
        </fieldset><label className="native-field"><span>Parent agent</span><select aria-label="Agent parent" value={edges.find(edge => edge[1] === selected)?.[0] ?? ''} onChange={event => attempt(() => {
          const parent = event.target.value; if (!parent && teamRoles.some(ref => ref !== selected && isTeamRoot(ref))) throw new Error('A team must have one clear root. Move this Agent below the existing root.'); setTree(moveNode(tree, selected, parent));
        })}><option value="">Root</option>{[...new Set([...Object.keys(roles), ...edges.map(edge => edge[0])])].filter(ref => !branchRoles(tree, selected).has(ref)).map(ref => <option key={ref} value={ref}>{roleName(renames, ref)}</option>)}</select><small>Self and descendants are excluded. Existing native parents are retained.</small></label>{field('instructions')}<details className="d-prompt-layers"><summary>Prompt layers</summary>{field('system_prompt', true)}{field('developer_prompt', true)}</details><details className="d-prompt-layers"><summary>Codex approval route</summary><p>Blank fields retain project defaults. These configure native review, not execution approval.</p>{field('approval_model')}{field('approval_base_url')}{field('approval_api_key_env')}</details>
      </div></fieldset></aside> : <aside className="d-agent-properties d-empty-properties"><Icon name="terminal" size={26}/><p>Select an agent to edit its role and model.</p></aside>}
    </div>}
    <footer className="new-draft-footer"><div><span className={`draft-dot ${changes.length ? 'dirty' : ''}`}/><strong>{changes.length ? `${changes.length} unsaved changes` : 'Draft matches saved configuration'}</strong><span>Running agents are unchanged</span></div><div><Button variant="ghost" isDisabled={busy} onPress={() => void reload()}>Reload</Button><Button variant="ghost" isDisabled={busy || !changes.length} onPress={() => { if (saved) reset(saved); setError(''); }}>Cancel changes</Button><Button variant="primary" isDisabled={busy || !changes.length} onPress={() => setReview(true)}>Review changes<Icon name="right" size={14}/></Button></div></footer>
    {adding && <Dialog title={adding === 'team' ? 'Add team' : 'Add Agent'} onClose={() => setAdding(null)}><div className="new-config-fields">{adding === 'team' && <Field label="Team name for new team" value={teamName} onChange={setTeamName}/>}<Field label="New Agent name" value={nodeName} onChange={setNodeName}/><label className="native-field"><span>New Agent Runtime</span><select aria-label="New Agent Runtime" value={newRuntime} onChange={event => setNewRuntime(event.target.value)}><option>codex</option><option>pi</option><option>dsh</option></select></label><Field label="New Agent model" value={newModel} onChange={setNewModel}/><p>Choose the initial Runtime and model. The properties panel can then reference a global connection.</p>{error && <p role="alert">{error}</p>}</div><div className="dialog-footer"><Button variant="secondary" onPress={() => setAdding(null)}>Keep editing</Button><Button variant="primary" onPress={() => attempt(() => { addNode(adding === 'team', adding === 'child'); setAdding(null); })}>{adding === 'team' ? 'Add team with root' : 'Add Agent'}</Button></div></Dialog>}
    {deleting && <Dialog title={deleting === 'team' ? `Delete ${team || 'ungrouped roles'}?` : `Remove ${roleName(renames,selected)}?`} onClose={() => setDeleting(null)}><p>This changes the configuration draft only. It does not stop, retire or remove a running Agent.</p>{deleting === 'agent' && <fieldset className="d-delete-options"><legend>What should happen to the children?</legend><label><input type="radio" name="delete-mode" checked={deleteMode === 'keep'} onChange={() => setDeleteMode('keep')}/><span><strong>Keep descendants</strong><small>Reconnect direct children to the parent, or promote a child for a root.</small></span></label><label><input type="radio" name="delete-mode" checked={deleteMode === 'branch'} onChange={() => setDeleteMode('branch')}/><span><strong>Delete the entire branch</strong><small>Remove this Agent and all configured descendants.</small></span></label>{deleteMode === 'keep' && isTeamRoot(selected) && <label className="native-field"><span>New root</span><select aria-label="New root" value={promoted} onChange={event => setPromoted(event.target.value)}>{edges.filter(([parent]) => parent === selected).map(([,child]) => <option key={child}>{child}</option>)}</select></label>}</fieldset>}<div className="d-delete-scope"><strong>Configuration nodes to remove</strong><p>{(deleting === 'team' ? teamRoles : deleteMode === 'branch' ? [...branchRoles(tree,selected)] : [selected]).join(' · ')}</p></div>{error && <p role="alert">{error}</p>}<div className="dialog-footer"><Button variant="secondary" onPress={() => setDeleting(null)}>Keep configuration</Button><Button className="destructive-button" onPress={() => attempt(removeConfiguration)}>Remove from draft</Button></div></Dialog>}
    {review && <Dialog title="Review configuration draft" onClose={() => setReview(false)}><p>Saving requests native authorization and checks the saved revision. Existing Sessions retain their configuration.</p><div className="change-list">{changes.map((change,index) => <div className="change-item" key={index}><h3>{change.label}</h3><div><span className="diff-before"><small>BEFORE</small>{change.before || '(empty)'}</span><span className="diff-after"><small>AFTER</small>{change.after || '(empty)'}</span></div></div>)}</div>{error && <p role="alert">{error}</p>}<div className="dialog-footer"><Button variant="secondary" isDisabled={busy} onPress={() => setReview(false)}>Keep editing</Button><Button variant="primary" isDisabled={busy} onPress={() => void save()}>Save changes</Button></div></Dialog>}
  </section>;
}
