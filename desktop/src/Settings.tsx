import { useEffect, useState } from 'react';
import { Button, Description, Input, Label, TextField } from '@heroui/react';
import type { ArchiveChoices, Connections, RoleFields, RoleTree, Settings } from '../electron/types';
import { branchRoles, treeEdges, moveNode, removeNodes, fieldLabels as labels, ownRole, roleChanges, roleName, runtimeLabel } from './settings-draft';
import { Dialog, Field, Icon } from './ui';
import { TeamGraph } from './TeamGraph';

/** Edit project settings; only the native save entry can persist it. */
export function SettingsView({ projectId, active = true, onModels }: { projectId: string; active?: boolean; onModels?: () => void }) {
  const [adding, setAdding] = useState<'team' | 'child' | 'root' | null>(null);
  const [deleting, setDeleting] = useState<'team' | 'agent' | null>(null);
  const [deleteMode, setDeleteMode] = useState<'branch' | 'keep'>('branch');
  const [promoted, setPromoted] = useState('');
  const [saved, setSaved] = useState<Settings | null>(null);
  const [roles, setRoles] = useState<Record<string, RoleFields>>({});
  const [renames, setRenames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState('');
  const [tree, setTree] = useState<RoleTree>({});
  const [team, setTeam] = useState('');
  const [teamName, setTeamName] = useState('');
  const [teamRenames, setTeamRenames] = useState<Record<string, string>>({});
  const [nodeName, setNodeName] = useState('');
  const [newConnection, setNewConnection] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [connections, setConnections] = useState<Connections>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { if (!message) return; const timer = setTimeout(() => setMessage(''), 4500); return () => clearTimeout(timer); }, [message]);

  useEffect(() => { setError(''); }, [selected, team, adding, deleting]);

  function reset(value: Settings): void {
    setSaved(value); setRoles(structuredClone(value.roles)); setTree(value.role_tree); setRenames({}); setTeamRenames({});
    setTeam(current => Object.keys(value.roles).some(ref => group(ref) === current) ? current : group(Object.keys(value.roles)[0] ?? ''));
    setSelected(current => Object.hasOwn(value.roles, current) ? current : Object.keys(value.roles).find(ref => group(ref) === team) ?? Object.keys(value.roles)[0] ?? '');
  }
  useEffect(() => {
    let alive = true;
    setBusy(true); setError('');
    window.graphtraj.settings(projectId).then(value => { if (alive) reset(value); })
      .catch(error => { if (alive) setError(String(error)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [projectId]);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    setConnections(undefined); setCatalogError('');
    window.graphtraj.connections(projectId, { action: 'read' })
      .then(value => { if (alive) setConnections(value); })
      .catch(error => { if (alive) setCatalogError(String(error)); });
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
  const approvalConnections = availableConnections.filter(item => {
    const [runtime, provider] = item.reference.split('/');
    const entry = connections?.catalog.runtimes[runtime];
    const route = entry?.providers[provider];
    return entry?.runtime !== 'dsh' && route?.base_url?.startsWith('https://') && route.api_key_env
      && (!route.api || route.api === 'openai-completions');
  });
  const selectedConnection = ownRole(roles, selected)?.connection;
  const selectedModel = availableConnections.find(item => item.reference === selectedConnection)?.metadata;
  const teamRoles = Object.keys(roles).filter(ref => group(ref) === team);
  function group(ref: string): string { return ref.includes('.') ? ref.split('.')[0] : ''; }
  function isTeamRoot(ref: string): boolean {
    return !edges.some(([, child]) => child === ref);
  }
  function attempt(action: () => void): void {
    try { action(); setError(''); setMessage(''); } catch (error) { setError(String(error)); }
  }
  function addNode(newTeam: boolean, child: boolean): void {
    const targetTeam = newTeam ? teamName : team;
    if (newTeam && (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(targetTeam) || teams.some(name => name === targetTeam || ownRole(teamRenames, name) === targetTeam))) throw new Error('Choose a new lowercase team name.');
    if (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(nodeName)) throw new Error('Enter a lowercase Agent name.');
    if (!availableConnections.some(item => item.reference === newConnection)) throw new Error('Choose an available global model.');
    const reference = targetTeam ? `${targetTeam}.${nodeName}` : nodeName;
    if (Object.hasOwn(roles, reference)) throw new Error('Agent name already exists.');
    setRoles(current => ({ ...current, [reference]: { connection: newConnection } }));
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
    try { reset(await window.graphtraj.settings(projectId)); setMessage('Loaded current configuration.'); }
    catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  /** Save one agents-tool switch immediately; role drafts are unaffected. */
  async function saveArchive(choices: Partial<ArchiveChoices>): Promise<void> {
    setBusy(true); setError(''); setMessage('');
    try {
      const { archive } = await window.graphtraj.saveArchive(projectId, choices);
      setSaved(current => current && { ...current, archive }); setMessage('Saved Session archive settings.');
    } catch (error) { setError(String(error)); }
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
    if (multiline) return <label className="native-field" key={name}><span>{labels[name]}</span><textarea aria-label={labels[name]} rows={4} value={value} disabled={busy} onChange={event => { const text = event.target.value; setError(''); setMessage(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), [name]: text } })); }}/></label>;
    return <TextField className="settings-field" key={name} value={value} isDisabled={busy}
      onChange={value => { setError(''); setMessage(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), [name]: value } })); }}>
      <Label>{name === 'instructions' ? `${selectedRuntime === 'codex' ? 'Developer' : 'System'} prompt file` : labels[name]}</Label>
      <Input autoComplete="off" spellCheck={false} />
      {name === 'api_key_env' && <Description>Environment variable NAME only, for example OPENAI_API_KEY. Set the secret in the environment used to launch your Runtime; this form never reads or saves its value.</Description>}
      {name === 'base_url' && <Description>Optional HTTP(S) endpoint. Leave blank for Runtime defaults. Pi uses its native provider configuration.</Description>}
      {name === 'runtime' && <Description>codex, pi or dsh. Pi models use provider/model-id.</Description>}
      {name === 'reasoning_effort' && <Description>Use a level supported by the selected Runtime, or leave blank for its default.</Description>}
      {name === 'instructions' && <Description>Optional UTF-8 file, relative to the project or absolute. Its text is added before the inline text for this layer; blank keeps the default. File contents are not edited here.</Description>}

    </TextField>;
  }
  const selectedRole = ownRole(roles, selected);
  const runtimeEntries = connections?.catalog.runtimes ?? {};
  const catalogNotice = catalogError ? `Global model catalog unavailable: ${catalogError}`
    : !connections ? 'Loading global model catalog…'
    : !availableConnections.length ? 'No global models configured.' : '';
  /** Prefer declared model capabilities; otherwise expose native Runtime request values. */
  function effortOptions(connection?: string | null, runtime?: string | null): string[] | undefined {
    const model = availableConnections.find(item => item.reference === connection)?.metadata;
    const kind = connection ? ownRole(runtimeEntries, connection.split('/')[0])?.runtime : runtime;
    return model?.supported_efforts ?? (kind ? connections?.capabilities.reasoning_efforts?.[kind] : undefined);
  }
  const selectedEfforts = effortOptions(selectedRole?.connection, selectedRole?.runtime) ?? [];
  function chooseConnection(connection: string): void {
    const model = availableConnections.find(item => item.reference === connection)?.metadata;
    if (!model || selectedRole?.connection === connection) return;
    const effort = selectedRole?.reasoning_effort;
    const supported = effortOptions(connection);
    // Missing metadata is not evidence that a retained effort is unsupported.
    const nextEffort = !effort || !supported || supported.includes(effort) ? effort : null;
    if (effort && nextEffort === null) setMessage('The previous effort is not available for this selection. Runtime default selected.');
    setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), connection,
      runtime: null, model: null, base_url: null, api_key_env: null,
      reasoning_effort: nextEffort,
    } }));
  }
  function modelFields(reference: string, choose: (connection: string) => void, prefix: string, legacy?: RoleFields) {
    const [runtime, provider] = reference.split('/');
    const entry = ownRole(runtimeEntries, runtime);
    const models = ownRole(entry?.providers, provider)?.models ?? {};
    const metadata = availableConnections.find(item => item.reference === reference)?.metadata;
    return <>
      {catalogNotice && <p role="status">{catalogNotice}</p>}
      <div className="d-agent-route-row">
        <label className="native-field"><span>Runtime</span><select aria-label={`${prefix} Runtime`} value={runtime || ''} disabled={!availableConnections.length} onChange={event => {
          const next = availableConnections.find(item => item.reference.startsWith(event.target.value + '/'));
          if (next) choose(next.reference);
        }}>
          {!reference && <option value="" disabled>{legacy ? runtimeLabel(legacy.runtime || 'Runtime not recorded') : 'Choose Runtime'}</option>}
          {reference && !entry && <option value={runtime}>{runtime} · unavailable</option>}
          {Object.entries(runtimeEntries).map(([id, value]) => <option key={id} value={id} disabled={!Object.values(value.providers).some(item => Object.keys(item.models).length)}>{runtimeLabel(value.runtime, id)}</option>)}
        </select></label>
        <label className="native-field"><span>Provider</span><select aria-label={`${prefix} provider`} value={provider || ''} disabled={!entry || !availableConnections.length} onChange={event => {
          const next = availableConnections.find(item => item.reference.startsWith(`${runtime}/${event.target.value}/`));
          if (next) choose(next.reference);
        }}>
          {!reference && <option value="">{legacy ? 'Saved project configuration' : 'Choose provider'}</option>}
          {reference && !ownRole(entry?.providers, provider) && <option value={provider}>{provider} · unavailable</option>}
          {Object.entries(entry?.providers ?? {}).map(([id, value]) => <option key={id} value={id} disabled={!Object.keys(value.models).length}>{id}</option>)}
        </select></label>
      </div>
      <label className="native-field"><span>Model</span><select aria-label={`${prefix} model`} value={reference} disabled={!entry || !availableConnections.length} onChange={event => choose(event.target.value)}>
        {!reference && <option value="">{legacy?.model || 'Choose model'}</option>}
        {reference && !metadata && <option value={reference}>{reference} · unavailable</option>}
        {Object.entries(models).map(([id, value]) => <option key={id} value={`${runtime}/${provider}/${id}`}>{value.alias || value.id}</option>)}
      </select><small>{metadata ? `${metadata.source} · Supported efforts: ${metadata.supported_efforts?.join(' · ') || 'Unknown'}` : legacy ? 'Source: saved project role. Retained until you select a global model.' : reference ? 'Saved connection unavailable. Retained; choose a replacement explicitly.' : 'Select a global Runtime, provider and model.'}</small></label>
      <Button variant="ghost" onPress={() => { setAdding(null); onModels?.(); }}>Agents &amp; models</Button>
    </>;
  }
  const selectedRuntime = selectedRole?.connection ? ownRole(runtimeEntries, selectedRole.connection.split('/')[0])?.runtime : selectedRole?.runtime;
  const hasChildren = edges.some(([parent]) => parent === selected);
  function graphModel(ref: string): string {
    const value = ownRole(roles, ref);
    const model = availableConnections.find(item => item.reference === value?.connection)?.metadata;
    const kind = value?.connection ? ownRole(runtimeEntries, value.connection.split('/')[0])?.runtime : value?.runtime;
    return `${runtimeLabel(kind || 'Runtime default')} · ${model?.alias || model?.id || value?.model || 'Model unavailable'}`;
  }
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
  return <section className="d-team-editor" aria-label="Project settings"><header className="d-config-heading"><div><h1>Teams &amp; roles</h1><p>Configure this project’s organization. Running agents are unchanged.</p></div><span className="memory-badge"><Icon name="shield" size={15}/>Project configuration</span></header>
    {error && !adding && !deleting && <div className="native-notice error" role="alert">{error}<p>Your unsaved changes are retained.</p></div>}
    {busy && <p className="native-notice" role="status">Loading or saving settings…</p>}{message && <div className="toast" role="status"><Icon name="check"/>{message}</div>}
    {saved?.archive && <fieldset className="d-archive-settings" disabled={busy}><legend>Session archive · agents tool (.graphtraj/swarm/config.yml)</legend>
      {([['save_normalized_sessions', 'Save normalized Sessions'], ['backfill_history', 'Backfill history of associated Sessions']] as const).map(([name, label]) =>
        <label key={name}><input type="checkbox" checked={saved.archive![name]} onChange={event => void saveArchive({ [name]: event.target.checked })}/><span>{label}</span></label>)}
      <small>Saved immediately. Turning saving off keeps saved history and never affects native Sessions, messages, stopping or continuing.</small></fieldset>}
    <nav className="d-team-tabs" aria-label="Project teams">{teams.map(name => <button key={name} aria-current={team === name ? 'true' : undefined} onClick={() => { setError(''); setTeam(name); setSelected(Object.keys(roles).find(ref => group(ref) === name) ?? ''); }}><Icon name="branch" size={15}/><span>{ownRole(teamRenames, name) ?? (name || 'Ungrouped roles')}</span><small>{Object.keys(roles).filter(ref => group(ref) === name).length}</small></button>)}<Button variant="ghost" isDisabled={busy || !saved} onPress={() => { setError(''); setAdding('team'); setTeamName(''); }}><Icon name="plus" size={15}/>Add team</Button>{teamRoles.length > 0 && <Button variant="ghost" className="d-delete-team" isDisabled={busy} onPress={() => setDeleting('team')}><Icon name="trash" size={15}/>Delete team</Button>}</nav>
    {!teams.length ? <div className="d-empty-configuration"><Icon name="branch" size={30}/><h2>{busy ? 'Loading teams…' : 'No teams configured'}</h2><p>Add a team and start with one root agent. Build its organization one child at a time.</p><Button variant="primary" isDisabled={busy || !saved} onPress={() => setAdding('team')}>Add first team</Button></div> : <div className="d-team-editor-body"><div className="d-org-workspace"><header><div><label>Team name<input aria-label="Team name" disabled={busy || !team} value={ownRole(teamRenames, team) ?? (team || 'Ungrouped roles')} onChange={event => {
      const value = event.target.value; setTeamRenames(current => ({ ...current, [team]: value }));
      setRenames(current => ({ ...current, ...Object.fromEntries(teamRoles.map(ref => [ref, `${value}.${roleName(renames, ref).split('.').pop()}`])) }));
    }}/></label></div><Button variant="secondary" isDisabled={busy} onPress={() => setAdding(selectedRole ? 'child' : 'root')}><Icon name="plus" size={15}/>{selectedRole ? 'Add child agent' : 'Add root agent'}</Button>{selectedRole && <Button variant="ghost" isDisabled={busy} onPress={() => setAdding('root')}>Add root agent</Button>}</header><TeamGraph key={team} tree={tree} references={teamRoles} roles={roles} renames={renames} selected={selected} busy={busy}
          onSelect={ref => { setSelected(ref); setError(''); }} onChange={next => { setTree(next); setError(''); setMessage(''); }} onError={setError} modelLabel={graphModel}/>
        <footer><Icon name="info" size={15}/><span>Drag from a parent’s lower handle to a child’s upper handle. Drag the parent end of an existing line to reconnect it. Select a line to disconnect its parent. Self-connections and cycles are rejected.</span></footer></div>
      {selectedRole ? <aside className="d-agent-properties"><header><div><h2>{roleName(renames, selected).split('.').at(-1)}</h2><span>{isTeamRoot(selected) ? 'Root agent configuration' : 'Child agent configuration'}</span></div><Button isIconOnly variant="ghost" aria-label="Delete selected agent configuration" isDisabled={busy} onPress={() => { setDeleting('agent'); setDeleteMode('branch'); setPromoted(edges.find(([parent]) => parent === selected)?.[1] ?? ''); }}><Icon name="trash" size={16}/></Button></header><fieldset disabled={busy} className="config-property-scroll"><div className="new-config-fields"><TextField className="settings-field" value={roleName(renames, selected).split('.').at(-1)} onChange={name => setRenames(current => ({ ...current, [selected]: group(roleName(renames, selected)) ? `${group(roleName(renames, selected))}.${name}` : name }))}><Label>Agent name</Label><Input/><Description>Renaming updates this team’s dispatch references.</Description></TextField>
        <fieldset className="d-agent-prompts"><legend>Prompts</legend>
          <p>Leave text and file references blank to keep Runtime defaults and the existing Harness instructions.</p>
          {field('system_prompt', true)}
          <small>{selectedRuntime === 'codex' ? 'Optional inline override of the native system prompt. Blank keeps the Codex default.' : 'Appended to the Runtime system prompt; its defaults remain.'}</small>
          {selectedRuntime !== 'codex' && field('instructions')}
          {field('developer_prompt', true)}
          {selectedRuntime === 'codex' ? field('instructions') : <small>This Runtime has no separate developer layer. The Adapter merges this text into its system prompt, without separate priority.</small>}
        </fieldset>
        <fieldset className="d-agent-model-fields"><legend>Model for this agent</legend>
          {modelFields(selectedRole.connection ?? '', chooseConnection, 'Agent', selectedRole.connection ? undefined : selectedRole)}
          {!selectedRole.connection && <details className="d-prompt-layers"><summary>Saved project model settings</summary><p>These existing settings are preserved. Selecting a global model replaces this role’s Runtime, model and provider settings when saved.</p>{field('runtime')}{field('model')}{field('base_url')}{field('api_key_env')}</details>}
          <label className="native-field"><span>This agent’s effort</span><select aria-label="This agent's effort" value={selectedRole.reasoning_effort || ''} onChange={event => setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), reasoning_effort: event.target.value || null } }))}>
            <option value="">Runtime default</option>
            {selectedRole.reasoning_effort && !selectedEfforts.includes(selectedRole.reasoning_effort) && <option value={selectedRole.reasoning_effort} disabled>{selectedRole.reasoning_effort} · saved; support unconfirmed</option>}
            {selectedEfforts.map(effort => <option key={effort} value={effort}>{effort}</option>)}
          </select><small>{selectedModel?.supported_efforts !== undefined ? 'Source: saved model capabilities. Changing models retains an available effort.' : selectedEfforts.length ? 'Source: native Runtime configuration options. Model support is not reported; the provider may restrict these values.' : 'Model capabilities and Runtime options unavailable. Saved effort is retained.'}</small></label>
        </fieldset>
        {selectedRuntime === 'codex' && <details className="d-prompt-layers"><summary>Codex approval model</summary>
          <p>Inherit the existing project review settings unless you select a model. Custom work providers require a review route before an Agent can start.</p>
          <label className="native-field"><span>Approval model</span><select aria-label="Codex approval model" value={selectedRole.approval_connection || (selectedRole.approval_model ? '__saved__' : '')} onChange={event => {
            const connection = event.target.value || null;
            setError(''); setRoles(current => ({ ...current, [selected]: { ...ownRole(current, selected), approval_connection: connection,
              approval_model: null, approval_base_url: null, approval_api_key_env: null } }));
          }}><option value="">Inherit project / Runtime review</option>
            {selectedRole.approval_model && <option value="__saved__" disabled>Saved route: {selectedRole.approval_model}</option>}
            {selectedRole.approval_connection && !approvalConnections.some(item => item.reference === selectedRole.approval_connection) && <option value={selectedRole.approval_connection}>{selectedRole.approval_connection} · unavailable</option>}
            {approvalConnections.map(item => <option key={item.reference} value={item.reference}>{item.metadata.alias || item.metadata.id} · {item.reference}</option>)}
          </select><small>Uses the selected provider’s HTTPS endpoint and API-key environment variable name for Chat Completions review. No credentials are copied.</small></label>
          {selectedRole.approval_model && <p>The saved explicit approval route is retained until you choose a replacement.</p>}
          {!approvalConnections.length && <p>No compatible global review models. Configure a Chat Completions provider with HTTPS and an API-key environment variable in Agents &amp; models.</p>}
        </details>}
      </div></fieldset></aside> : <aside className="d-agent-properties d-empty-properties"><Icon name="terminal" size={26}/><p>Select an agent to edit its role and model.</p></aside>}
    </div>}
    <footer className="new-draft-footer"><div><span className={`draft-dot ${changes.length ? 'dirty' : ''}`}/><strong>{changes.length ? `${changes.length} unsaved changes` : 'All changes saved'}</strong><span>Running agents are unchanged</span></div><div><Button variant="ghost" isDisabled={busy} onPress={() => void reload()}>Reload</Button><Button variant="ghost" isDisabled={busy || !changes.length} onPress={() => { if (saved) reset(saved); setError(''); }}>Cancel</Button><Button variant="primary" isDisabled={busy || !changes.length} onPress={() => void save()}>Save</Button></div></footer>
    {adding && <Dialog title={adding === 'team' ? 'Add team' : 'Add Agent'} onClose={() => { setAdding(null); setError(''); }}><div className="new-config-fields">{adding === 'team' && <Field label="Team name for new team" value={teamName} onChange={setTeamName}/>}<Field label="New Agent name" value={nodeName} onChange={setNodeName}/>{modelFields(newConnection, setNewConnection, 'New Agent')}{error && <p role="alert">{error}</p>}</div><div className="dialog-footer"><Button variant="secondary" onPress={() => { setAdding(null); setError(''); }}>Keep editing</Button><Button variant="primary" isDisabled={busy || !availableConnections.some(item => item.reference === newConnection)} onPress={() => attempt(() => { addNode(adding === 'team', adding === 'child'); setAdding(null); })}>{adding === 'team' ? 'Add team with root' : 'Add Agent'}</Button></div></Dialog>}
    {deleting && <Dialog title={deleting === 'team' ? `Delete ${team || 'ungrouped roles'}?` : `Remove ${roleName(renames,selected)}?`} onClose={() => { setDeleting(null); setError(''); }}><p>Changes apply when you click Save. It does not stop, retire or remove a running Agent.</p>{deleting === 'agent' && hasChildren && <fieldset className="d-delete-options"><legend>What should happen to the children?</legend><label><input type="radio" name="delete-mode" checked={deleteMode === 'keep'} onChange={() => setDeleteMode('keep')}/><span><strong>Keep descendants</strong><small>Reconnect direct children to the parent, or promote a child for a root.</small></span></label><label><input type="radio" name="delete-mode" checked={deleteMode === 'branch'} onChange={() => setDeleteMode('branch')}/><span><strong>Delete the entire branch</strong><small>Remove this Agent and all configured descendants.</small></span></label>{deleteMode === 'keep' && isTeamRoot(selected) && edges.filter(([parent]) => parent === selected).length > 1 && <label className="native-field"><span>New root</span><select aria-label="New root" value={promoted} onChange={event => setPromoted(event.target.value)}>{edges.filter(([parent]) => parent === selected).map(([,child]) => <option key={child}>{child}</option>)}</select></label>}</fieldset>}<div className="d-delete-scope"><strong>Configuration nodes to remove</strong><p>{(deleting === 'team' ? teamRoles : deleteMode === 'branch' ? [...branchRoles(tree,selected)] : [selected]).join(' · ')}</p></div>{error && <p role="alert">{error}</p>}<div className="dialog-footer"><Button variant="secondary" onPress={() => { setDeleting(null); setError(''); }}>Keep configuration</Button><Button className="destructive-button" onPress={() => attempt(removeConfiguration)}>Remove configuration</Button></div></Dialog>}

  </section>;
}
