import { useEffect, useState } from 'react';
import { Button, Card, Description, Form, Input, Label, TextArea, TextField } from '@heroui/react';
import type { RoleFields, Settings } from '../electron/types';
import { fieldLabels as labels, ownRole, roleChanges, roleName } from './settings-draft';
import './settings.css';

/** Edit a project-local draft; only the native save entry can persist it. */
export function SettingsView({ projectId }: { projectId: string }) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [roles, setRoles] = useState<Record<string, RoleFields>>({});
  const [renames, setRenames] = useState<Record<string, string>>({});
  const [edges, setEdges] = useState<[string, string][]>([]);
  const [selected, setSelected] = useState('');
  const [parent, setParent] = useState('');
  const [child, setChild] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  function reset(value: Settings): void {
    setSaved(value); setRoles(structuredClone(value.roles)); setEdges(value.edges); setRenames({});
    setSelected(current => Object.hasOwn(value.roles, current) ? current : Object.keys(value.roles)[0] ?? '');
  }
  useEffect(() => {
    let alive = true;
    setBusy(true);
    window.graphtraj.settings(projectId).then(value => { if (alive) reset(value); })
      .catch(error => { if (alive) setError(String(error)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [projectId]);

  const { edits, changes } = roleChanges(roles, saved?.roles);
  const names = Object.fromEntries(Object.entries(renames).filter(([old, name]) => old !== name));
  for (const [old, name] of Object.entries(names)) changes.push({ label: 'Role name', before: old, after: name });
  const same = (a: [string, string], b: [string, string]) => a[0] === b[0] && a[1] === b[1];
  const added = edges.filter(edge => !saved?.edges.some(previous => same(edge, previous)));
  const removed = (saved?.edges ?? []).filter(edge => !edges.some(next => same(edge, next)));
  for (const edge of added) changes.push({ label: 'Dispatch', before: '(not allowed)', after: edge.join(' → ') });
  for (const edge of removed) changes.push({ label: 'Dispatch', before: edge.join(' → '), after: '(removed)' });

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
        add_edges: added.map(([parent, child]) => ({ parent, child })),
        remove_edges: removed.map(([parent, child]) => ({ parent, child })),
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
    <header><h1>Settings</h1><p>{saved?.effect ?? 'Edit existing project roles and connections through native authorization.'}</p></header>
    {error && <div className="error" role="alert">{error}<p>Your draft is retained. Reload to resolve an external change.</p></div>}
    <div role="status">{busy ? 'Waiting for native settings / approval…' : message}</div>
    <div className="settings-actions">
      <Button type="submit" isDisabled={busy || !changes.length}>Save changes</Button>
      <Button variant="secondary" isDisabled={busy || !saved || !changes.length}
        onPress={() => { if (saved) reset(saved); setError(''); setMessage('Draft cancelled. Nothing saved.'); }}>Cancel draft</Button>
      <Button variant="tertiary" isDisabled={busy} onPress={() => { void reload(); }}>Reload and discard draft</Button>
    </div>
    {saved && <div className="settings-columns">
      <nav aria-label="Configured roles">{Object.keys(roles).map(reference => <Button key={reference}
        variant={selected === reference ? 'primary' : 'secondary'} isDisabled={busy}
        onPress={() => setSelected(reference)}>{roleName(renames, reference)}</Button>)}
        {!Object.keys(roles).length && <p>No existing role presets. Configure roles through the native project setup first.</p>}
      </nav>
      {selected && <div className="settings-fields">
        <Card><Card.Header><Card.Title>Connections and model</Card.Title></Card.Header><Card.Content>
          {field('runtime')}{field('model')}{field('base_url')}{field('api_key_env')}
          <details><summary>Runtime parameters</summary>{field('reasoning_effort')}</details>
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
    {saved && <Card><Card.Header><Card.Title>Dispatch relationships</Card.Title></Card.Header><Card.Content>
      <p>These are configured relationships, not running Agents. Removing an edge does not stop an existing Session.</p>
      <ul>{edges.map(([parent, child]) => <li key={`${parent}:${child}`}>
        {roleName(renames, parent)} → {roleName(renames, child)}{' '}
        <Button size="sm" variant="ghost" isDisabled={busy} aria-label={`Remove dispatch ${parent} to ${child}`}
          onPress={() => setEdges(current => current.filter(edge => !same(edge, [parent, child])))}>Remove</Button>
      </li>)}</ul>
      <div className="settings-actions">
        <label>Dispatch parent<select value={parent} disabled={busy} onChange={event => setParent(event.target.value)}>
          <option value="">Choose parent</option>{[...new Set([...Object.keys(roles), ...edges.map(edge => edge[0])])].map(ref => <option key={ref}>{ref}</option>)}
        </select></label>
        <label>Dispatch child<select value={child} disabled={busy} onChange={event => setChild(event.target.value)}>
          <option value="">Choose child</option>{Object.keys(roles).map(ref => <option key={ref}>{ref}</option>)}
        </select></label>
        <Button variant="secondary" isDisabled={busy || !parent || !child || edges.some(edge => same(edge, [parent, child]))}
          onPress={() => setEdges(current => [...current, [parent, child]])}>Add relationship</Button>
      </div>
    </Card.Content></Card>}
    <Card><Card.Header><Card.Title>Changes to review</Card.Title></Card.Header><Card.Content>
      {changes.length ? <table><thead><tr><th>Setting</th><th>Before</th><th>After</th></tr></thead>
        <tbody>{changes.map((change, index) => <tr key={index}><th>{change.label}</th><td>{change.before}</td><td>{change.after}</td></tr>)}</tbody>
      </table> : <p>No staged changes.</p>}
    </Card.Content></Card>
    <Card><Card.Header><Card.Title>Pricing information</Card.Title></Card.Header><Card.Content>
      <p>Official price data is unavailable in this version. No cost estimate is shown.</p>
    </Card.Content></Card>
  </Form>;
}
