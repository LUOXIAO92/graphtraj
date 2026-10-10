import { useEffect, useState } from 'react';
import { Button, Input, Label, TextField } from '@heroui/react';
import type { Catalog, CatalogModel, CatalogRuntime, Connections } from '../electron/types';
import './settings.css';

/** Edit the shared native catalog; authentication stays in the Runtime client. */
export function ConnectionsView({ projectId }: { projectId?: string }) {
  const [saved, setSaved] = useState<Connections>();
  const [catalog, setCatalog] = useState<Catalog>({ version: 1, runtimes: {} });
  const [runtimeId, setRuntimeId] = useState('');
  const [providerId, setProviderId] = useState('');
  const [runtimeName, setRuntimeName] = useState('');
  const [kind, setKind] = useState<CatalogRuntime['runtime']>('codex');
  const [providerName, setProviderName] = useState('');
  const [modelName, setModelName] = useState('');
  const [model, setModel] = useState<CatalogModel>({ id: '', source: 'manual' });
  const [discovery, setDiscovery] = useState<Connections['discovery']>();
  const [preview, setPreview] = useState<Catalog>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const runtime = catalog.runtimes[runtimeId];
  const provider = runtime?.providers[providerId];
  const dirty = JSON.stringify(catalog) !== JSON.stringify(saved?.catalog);

  function reset(value: Connections): void {
    setSaved(value); setCatalog(structuredClone(value.catalog)); setPreview(undefined);
    setRuntimeId(current => Object.hasOwn(value.catalog.runtimes, current) ? current : Object.keys(value.catalog.runtimes)[0] ?? '');
    setProviderId(''); setDiscovery(undefined);
  }
  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (error) { setError(String(error)); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let alive = true;
    {
      setBusy(true);
      window.graphtraj.connections(projectId ?? null, { action: 'read' }).then(value => { if (alive) reset(value); })
        .catch(error => { if (alive) setError(String(error)); }).finally(() => { if (alive) setBusy(false); });
    }
    return () => { alive = false; };
  }, [projectId]);
  function edit(update: (draft: Catalog) => void): void {
    const next = structuredClone(catalog); update(next); setCatalog(next); setPreview(undefined); setMessage('');
  }
  function text(label: string, value: string, change: (value: string) => void) {
    return <TextField value={value} onChange={change} isDisabled={busy}><Label>{label}</Label><Input autoComplete="off" spellCheck={false} /></TextField>;
  }
  function validName(name: string): boolean {
    if (/^[A-Za-z0-9_-]+$/.test(name)) return true;
    setError('Use letters, digits, underscores or hyphens for catalog names.'); return false;
  }
  return <section className="settings" aria-label="Agents and models">
    <header><h1>Agents &amp; models</h1><p>Global Runtime → Provider → Model connections. Providers share their Runtime Home. Saving affects later dispatches; existing Agents keep their captured settings.</p></header>
    <p>Log in using the original Runtime client, then refresh discovery. This app does not log in or read credentials. Catalog metadata does not verify account access.</p>
    {error && <div role="alert" className="error">{error}<p>Draft retained. Reload to resolve an external change.</p></div>}
    <div role="status">{busy ? 'Waiting for native configuration / approval…' : message}</div>
    {saved && <>
      <div className="settings-actions">
        <Button isDisabled={busy || !dirty} onPress={() => void run(async () => {
          const result = await window.graphtraj.connections(projectId ?? null, { action: 'preview', catalog }); setPreview(result.catalog);
        })}>Preview connections</Button>
        <Button isDisabled={busy || !preview} onPress={() => void run(async () => {
          const result = await window.graphtraj.connections(projectId ?? null, { action: 'save', catalog: preview, expected_revision: saved.revision });
          reset(result); setMessage(result.applied ? 'Connections saved.' : 'No changes to save.');
        })}>Save connections</Button>
        <Button variant="secondary" isDisabled={busy || !dirty} onPress={() => { reset(saved); setError(''); setMessage('Draft cancelled. Nothing saved.'); }}>Cancel connections draft</Button>
        <Button variant="tertiary" isDisabled={busy} onPress={() => void run(async () => { reset(await window.graphtraj.connections(projectId ?? null, { action: 'read' })); setMessage('Connections reloaded.'); })}>Reload connections</Button>
      </div>
      <div className="settings-columns">
        <nav aria-label="Runtime provider model catalog">
          {Object.entries(catalog.runtimes).map(([name, entry]) => <details key={name}>
            <summary>{name} · {entry.runtime}</summary>
            <Button size="sm" isDisabled={busy} aria-pressed={runtimeId === name && !providerId} variant={runtimeId === name && !providerId ? 'primary' : 'secondary'} onPress={() => { setRuntimeId(name); setProviderId(''); setDiscovery(undefined); }}>Select Runtime {name}</Button>
            {Object.entries(entry.providers).map(([providerName, value]) => <details key={providerName}>
              <summary>{providerName}</summary>
              <Button size="sm" isDisabled={busy} aria-pressed={runtimeId === name && providerId === providerName} variant={runtimeId === name && providerId === providerName ? 'primary' : 'secondary'} onPress={() => { setRuntimeId(name); setProviderId(providerName); setDiscovery(undefined); }}>Select Provider {providerName}</Button>
              <ul>{Object.entries(value.models).map(([key, model]) => <li key={key}>{model.alias ? `${model.alias} · ${model.id}` : model.id} · {model.source}<br /><code>{name}/{providerName}/{key}</code><br />Efforts: {model.supported_efforts?.join(', ') || 'unknown'}</li>)}</ul>
            </details>)}
          </details>)}
          {!Object.keys(catalog.runtimes).length && <p>No saved Runtime connections.</p>}
        </nav>
        <div className="settings-fields">
          <fieldset disabled={busy}><legend>Add Runtime</legend>
            {text('Runtime entry name', runtimeName, setRuntimeName)}
            <label>Runtime type<select value={kind} onChange={event => setKind(event.target.value as CatalogRuntime['runtime'])}><option>codex</option><option>pi</option><option>dsh</option></select></label>
            <Button onPress={() => {
              if (!validName(runtimeName)) return;
              if (Object.hasOwn(catalog.runtimes, runtimeName)) { setError('Runtime entry already exists.'); return; }
              edit(draft => { draft.runtimes = { ...draft.runtimes, [runtimeName]: { runtime: kind, providers: {} } }; }); setRuntimeId(runtimeName); setProviderId(''); setRuntimeName('');
            }}>Add Runtime</Button>
          </fieldset>
          {runtime && <fieldset disabled={busy}><legend>Runtime: {runtimeId}</legend>
            {text('Shared Runtime Home', runtime.home ?? '', value => edit(draft => { if (value) draft.runtimes[runtimeId].home = value; else delete draft.runtimes[runtimeId].home; }))}
            <p>Absolute directory, or blank for the Runtime default. No copied login files. Discovery: {saved.capabilities.model_discovery[runtime.runtime]}. Provider APIs: {saved.capabilities.custom_api[runtime.runtime].join(', ')}.</p>
            <Button isDisabled={busy || dirty} onPress={() => void run(async () => {
              const result = await window.graphtraj.connections(projectId ?? null, { action: 'discover', runtime: runtimeId }); setDiscovery(result.discovery);
            })}>Refresh native models</Button>
            {dirty && <p>Save the Runtime Home before discovery.</p>}
            {discovery && <div><p>{discovery.status} · account access: {discovery.account_access}. {discovery.message}</p>
              {Object.entries(discovery.provider_status ?? {}).map(([name, status]) => <p key={name}>{name}: {status}</p>)}
              <ul>{discovery.models.map((value, index) => <li key={index}>{value.provider} / {value.alias || value.id} · native · efforts: {value.supported_efforts?.join(', ') || 'unknown'} <Button size="sm" onPress={() => {
                const { provider: name, supported_efforts, ...fields } = value;
                if (!Object.hasOwn(runtime.providers, name)) edit(draft => { draft.runtimes[runtimeId].providers = { ...draft.runtimes[runtimeId].providers, [name]: { models: {} } }; });
                setProviderId(name); setModel({ ...fields, ...(supported_efforts ? { supported_efforts } : {}) }); setModelName(value.id.replace(/[^A-Za-z0-9_-]/g, '_'));
              }}>Use {value.id}</Button></li>)}</ul>
            </div>}
            {text('Provider name', providerName, setProviderName)}
            <Button onPress={() => {
              if (!validName(providerName)) return;
              if (Object.hasOwn(runtime.providers, providerName)) { setError('Provider already exists.'); return; }
              edit(draft => { draft.runtimes[runtimeId].providers = { ...draft.runtimes[runtimeId].providers, [providerName]: { models: {} } }; }); setProviderId(providerName); setProviderName('');
            }}>Add Provider</Button>
          </fieldset>}
          {provider && <fieldset disabled={busy}><legend>Provider: {providerId}</legend>
            {text('Provider Base URL', provider.base_url ?? '', value => edit(draft => { if (value) draft.runtimes[runtimeId].providers[providerId].base_url = value; else delete draft.runtimes[runtimeId].providers[providerId].base_url; for (const model of Object.values(draft.runtimes[runtimeId].providers[providerId].models)) { model.source = 'manual'; delete model.supported_efforts; } }))}
            {text('Provider api_key_env name', provider.api_key_env ?? '', value => edit(draft => { if (value) draft.runtimes[runtimeId].providers[providerId].api_key_env = value; else delete draft.runtimes[runtimeId].providers[providerId].api_key_env; }))}
            <p>Environment variable NAME only, for example OPENROUTER_API_KEY. Set its value outside this app in the Runtime launch environment. Third-party endpoints require their own authentication; no official login fallback.</p>
            {runtime.runtime === 'pi' && <label>Provider API<select value={provider.api ?? ''} onChange={event => edit(draft => { if (event.target.value) draft.runtimes[runtimeId].providers[providerId].api = event.target.value; else delete draft.runtimes[runtimeId].providers[providerId].api; })}><option value="">Native default</option>{saved.capabilities.custom_api.pi.map(api => <option key={api}>{api}</option>)}</select></label>}
            {text('Model entry name', modelName, setModelName)}
            {text('Model identifier', model.id, id => setModel({ ...model, id, source: 'manual', supported_efforts: undefined }))}
            {text('Model alias', model.alias ?? '', alias => setModel({ ...model, alias: alias || undefined }))}
            <p>Source: {model.source}. Supported efforts: {model.supported_efforts?.join(', ') || 'unknown; choose a Runtime-supported effort on the role'}.</p>
            <Button onPress={() => {
              if (!validName(modelName) || !model.id.trim()) { setError('Model needs a name and identifier.'); return; }
              if (Object.hasOwn(provider.models, modelName)) { setError('Model entry already exists.'); return; }
              edit(draft => { draft.runtimes[runtimeId].providers[providerId].models = { ...draft.runtimes[runtimeId].providers[providerId].models, [modelName]: model }; }); setModelName(''); setModel({ id: '', source: 'manual' });
            }}>Add Model</Button>
          </fieldset>}
        </div>
      </div>
      {preview && <details open><summary>Connection changes to approve</summary><h3>Before</h3><pre>{JSON.stringify(saved.catalog, null, 2)}</pre><h3>After</h3><pre>{JSON.stringify(preview, null, 2)}</pre></details>}
    </>}
  </section>;
}
