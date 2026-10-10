import { useEffect, useState } from 'react';
import { Button, Card, Description, Form, Input, Label, TextArea, TextField } from '@heroui/react';
import type { Connections, RoleFields, RoleTree, Settings } from '../electron/types';
import { branchRoles, treeEdges, moveNode, removeNodes, fieldLabels as labels, ownRole, roleChanges, roleName } from './settings-draft';
import './settings.css';
import { PriceInformation } from './UsageDashboard';

/** Edit a project-local draft; only the native save entry can persist it. */
export function SettingsView({ projectId }: { projectId: string }) {
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

  function reset(value: Settings): void {
    setSaved(value); setRoles(structuredClone(value.roles)); setTree(value.role_tree); setRenames({}); setTeamRenames({});
    setTeam(current => Object.keys(value.roles).some(ref => group(ref) === current) ? current : group(Object.keys(value.roles)[0] ?? ''));
    setSelected(current => Object.hasOwn(value.roles, current) ? current : Object.keys(value.roles).find(ref => group(ref) === team) ?? Object.keys(value.roles)[0] ?? '');
  }
  useEffect(() => {
    let alive = true;
    setBusy(true);
    window.graphtraj.connections(projectId, { action: 'read' }).then(value => { if (alive) setConnections(value); }).catch(() => { /* Inline roles remain editable if the catalog is unavailable. */ });
    window.graphtraj.settings(projectId).then(value => { if (alive) reset(value); })
      .catch(error => { if (alive) setError(String(error)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [projectId]);

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
  function renderTree(nodes: RoleTree) {
    return Object.entries(nodes).map(([ref, children]) => <li key={ref}>
      {Object.keys(children).length ? <details><summary>{roleName(renames, ref)}</summary>
        {Object.hasOwn(roles, ref) && <Button size="sm" isDisabled={busy} aria-pressed={selected === ref} variant={selected === ref ? 'primary' : 'secondary'} onPress={() => { setSelected(ref); setTeam(group(ref)); }}>Select {roleName(renames, ref)}</Button>}
        <ul>{renderTree(children)}</ul>
      </details> : Object.hasOwn(roles, ref) ? <Button size="sm" isDisabled={busy} aria-pressed={selected === ref} variant={selected === ref ? 'primary' : 'secondary'} onPress={() => { setSelected(ref); setTeam(group(ref)); }}>{roleName(renames, ref)}</Button> : <span>{ref} · inline dispatch role</span>}
    </li>);
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
      reset(next); setMessage(next.applied ? 'Settings saved.' : 'No changes to save.');
    } catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  function field(name: keyof RoleFields, multiline = false) {
    const value = ownRole(roles, selected)?.[name] ?? '';
    return <TextField key={name} value={value} isDisabled={busy}
      onChange={value => { setMessage(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), [name]: value } })); }}>
      <Label>{labels[name]}</Label>
      {multiline ? <TextArea rows={4} /> : <Input autoComplete="off" spellCheck={false} />}
      {name === 'api_key_env' && <Description>Environment variable NAME only, for example OPENAI_API_KEY. Set the secret in the environment used to launch your Runtime; this form never reads or saves its value.</Description>}
      {name === 'base_url' && <Description>Optional HTTP(S) endpoint. Leave blank for Runtime defaults. Pi uses its native provider configuration.</Description>}
      {name === 'runtime' && <Description>codex, pi or dsh. Pi models use provider/model-id.</Description>}
      {name === 'reasoning_effort' && <Description>Use a level supported by the selected Runtime, or leave blank for its default.</Description>}
      {name === 'instructions' && <Description>Existing UTF-8 file path, relative to the project or absolute. File contents are not edited here.</Description>}
      {name === 'developer_prompt' && <Description>Supported by Codex. Clear this layer for Pi or DSH.</Description>}
    </TextField>;
  }
  return <Form className="settings" aria-label="Project settings" onSubmit={event => { event.preventDefault(); if (!busy && changes.length) void save(); }}>
    <header><h1>Teams &amp; roles</h1><p>{saved?.effect ?? 'Edit project teams and roles through native authorization.'}</p></header>
    <PriceInformation />
    {error && <div className="error" role="alert">{error}<p>Your draft is retained. Reload to resolve an external change.</p></div>}
    <div role="status">{busy ? 'Waiting for native settings / approval…' : message}</div>
    <div className="settings-actions">
      <Button type="submit" isDisabled={busy || !changes.length}>Save changes</Button>
      <Button variant="secondary" isDisabled={busy || !saved || !changes.length}
        onPress={() => { if (saved) reset(saved); setError(''); setMessage('Draft cancelled. Nothing saved.'); }}>Cancel draft</Button>
      <Button variant="tertiary" isDisabled={busy} onPress={() => { void reload(); }}>Reload and discard draft</Button>
    </div>
    {saved && <div className="settings-columns">
      <nav aria-label="Configured roles">
        <label>Team<select aria-label="Team" value={team} disabled={busy} onChange={event => { const value = event.target.value; setTeam(value); setSelected(Object.keys(roles).find(ref => group(ref) === value) ?? ''); }}>{teams.map(name => <option key={name} value={name}>{ownRole(teamRenames, name) ?? (name || 'Ungrouped roles')}</option>)}</select></label>
        {teamRoles.map(reference => <Button key={reference} aria-pressed={selected === reference} variant={selected === reference ? 'primary' : 'secondary'} isDisabled={busy} onPress={() => setSelected(reference)}>{roleName(renames, reference)}</Button>)}
        {!teamRoles.length && <p>No configured Agents. Add a team and root below.</p>}
        {team && <><TextField value={teamName} onChange={setTeamName} isDisabled={busy}><Label>New team name</Label><Input /></TextField>
          <Button isDisabled={busy} onPress={() => attempt(() => {
            if (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(teamName) || teams.some(name => name === teamName || ownRole(teamRenames, name) === teamName)) throw new Error('Choose a new lowercase team name.');
            setTeamRenames(current => ({ ...current, [team]: teamName }));
            setRenames(current => ({ ...current, ...Object.fromEntries(teamRoles.map(ref => [ref, `${teamName}.${roleName(renames, ref).split('.').pop()}`])) }));
          })}>Rename team</Button>
          <Button variant="danger" isDisabled={busy} onPress={() => attempt(() => {
            const affected = new Set(teamRoles);
            setTree(removeNodes(tree, affected, true));
            setRoles(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref))));
            setRenames(current => Object.fromEntries(Object.entries(current).filter(([ref]) => !affected.has(ref)))); setSelected('');
          })}>Delete team</Button><p>Deletes this team's presets. Other teams' descendants reconnect to the nearest surviving parent. Review the resulting tree before saving.</p></>}
      </nav>
      {selected && Object.hasOwn(roles, selected) && <div className="settings-fields">
        <Card><Card.Header><Card.Title>Connections and model</Card.Title></Card.Header><Card.Content>
          <label>Global connection<select aria-label="Global connection" value={ownRole(roles, selected)?.connection ?? ''} disabled={busy} onChange={event => {
            const connection = event.target.value;
            setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), connection: connection || null,
              runtime: connection ? null : 'codex', model: connection ? null : '', base_url: null, api_key_env: null } }));
          }}><option value="">Inline Runtime and model</option>
            {availableConnections.map(({ reference, metadata }) => <option key={reference} value={reference}>{reference} · {metadata.alias || metadata.id} · {metadata.source}</option>)}
            {selectedConnection && !selectedModel && <option value={selectedConnection}>{selectedConnection} · unavailable</option>}
          </select></label>
          {!ownRole(roles, selected)?.connection && <>{field('runtime')}{field('model')}{field('base_url')}{field('api_key_env')}</>}

          <details><summary>Runtime parameters</summary>{field('reasoning_effort')}
            {selectedConnection && <p>Model-supported efforts: {selectedModel?.supported_efforts?.join(', ') || 'unknown'}.</p>}
            <p>Supported model efforts describe capabilities; this role's effort is selected for later dispatches. Existing Sessions retain their choice.</p>
            <details><summary>Codex approval route</summary><p>Custom Codex providers require a role or project approval route. Blank role fields retain project defaults. These fields configure the existing native review mechanism; they do not approve execution.</p>
              {field('approval_model')}{field('approval_base_url')}{field('approval_api_key_env')}
              <p>HTTPS endpoint and environment variable NAME only. No credential values.</p>
            </details>
          </details>
        </Card.Content></Card>
        <Card><Card.Header><Card.Title>Role</Card.Title></Card.Header><Card.Content>
          <TextField value={roleName(renames, selected)} isDisabled={busy}
            onChange={name => setRenames(current => ({ ...current, [selected]: name }))}>
            <Label>Role reference</Label><Input /><Description>Existing name or group.name. Renaming updates its dispatch references.</Description>
          </TextField>
          {field('instructions')}{field('system_prompt', true)}{field('developer_prompt', true)}
        </Card.Content></Card>
      </div>}
    </div>}
    {saved && <Card><Card.Header><Card.Title>Team organization</Card.Title></Card.Header><Card.Content>
      <p>Configuration only. Deleting teams or Agents never stops a running Session. Expand an arrow independently from selecting its Agent.</p>
      <ul aria-label="Organization tree">{renderTree(tree)}</ul>
      {!Object.keys(tree).length && <p>Empty organization. Add a root Agent to recover.</p>}
      <fieldset disabled={busy}><legend>Add team or Agent</legend>
        <TextField value={teamName} onChange={setTeamName}><Label>Team name for new team</Label><Input /></TextField>
        <TextField value={nodeName} onChange={setNodeName}><Label>New Agent name</Label><Input /></TextField>
        <label>New Agent Runtime<select aria-label="New Agent Runtime" value={newRuntime} onChange={event => setNewRuntime(event.target.value)}><option>codex</option><option>pi</option><option>dsh</option></select></label>
        <TextField value={newModel} onChange={setNewModel}><Label>New Agent model</Label><Input /></TextField>
        <div className="settings-actions"><Button onPress={() => attempt(() => addNode(true, false))}>Add team with root</Button>
          <Button onPress={() => attempt(() => addNode(false, false))}>Add root Agent</Button>
          <Button isDisabled={!selected || busy} onPress={() => attempt(() => addNode(false, true))}>Add child Agent</Button></div>
      </fieldset>
      {selected && Object.hasOwn(roles, selected) && <fieldset disabled={busy}><legend>Selected Agent: {roleName(renames, selected)}</legend>
        <label>Agent parent<select aria-label="Agent parent" value={edges.find(edge => edge[1] === selected)?.[0] ?? ''} onChange={event => attempt(() => {
          const parent = event.target.value;
          if (!parent && teamRoles.some(ref => ref !== selected && isTeamRoot(ref))) throw new Error('A team must have one clear root. Move this Agent below the existing root.');
          const next = moveNode(tree, selected, parent); setTree(next);
        })}><option value="">Root</option>{[...new Set([...Object.keys(roles), ...edges.map(edge => edge[0])])].filter(ref => !branchRoles(tree, selected).has(ref)).map(ref => <option key={ref} value={ref}>{roleName(renames, ref)}</option>)}</select></label>
        {new Set(edges.filter(edge => edge[1] === selected).map(edge => edge[0])).size > 1 && <p>This native role has several parents. Choosing a parent moves all occurrences and retains their children.</p>}
        <p>Delete branch removes this Agent and all descendants: {[...branchRoles(tree, selected)].join(', ')}. Reconnect removes only this Agent and keeps its children under its parent; a root needs at most one child.</p>
        <div className="settings-actions"><Button variant="danger" onPress={() => attempt(() => deleteNode(false))}>Delete Agent and branch</Button>
          <Button variant="secondary" onPress={() => attempt(() => deleteNode(true))}>Delete Agent, reconnect children</Button></div>
      </fieldset>}
    </Card.Content></Card>}
    <Card><Card.Header><Card.Title>Changes to review</Card.Title></Card.Header><Card.Content>
      {changes.length ? <table><thead><tr><th>Setting</th><th>Before</th><th>After</th></tr></thead>
        <tbody>{changes.map((change, index) => <tr key={index}><th>{change.label}</th><td>{change.before}</td><td>{change.after}</td></tr>)}</tbody>
      </table> : <p>No staged changes.</p>}
    </Card.Content></Card>
  </Form>;
}
