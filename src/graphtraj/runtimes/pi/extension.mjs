/** Pi's session-local GraphTraj entry; loading this file is a native trust step. */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
/** Render the same successful MCP communication facts without model injection. */
export function registerAgentDisplay(pi, sdk) {
  const customType = 'graphtraj:agent-communication';
  pi.registerEntryRenderer(customType, entry => {
    const { sender, recipient, body } = entry.data;
    return new sdk.CustomMessageComponent({
      role: 'custom', customType: `agents · ${sender} → ${recipient}`,
      content: body, display: true, timestamp: 0,
    });
  });

  pi.on('tool_result', (event, ctx) => {
    if (!ctx.hasUI || event.isError || !['graphtraj', 'agents'].includes(event.details?.server)) return;
    const tool = event.details.tool;
    const input = tool === 'agents' && event.input.action === 'execute'
        ? {action: event.input.feature, ...event.input.arguments} : undefined;
    if (!input) return;
    const result = event.structuredContent?.structuredContent;
    if (!result || result.error || !result.agent) return;
    const record = result.result || {};
    const caller = record.parent || ctx.sessionManager.getSessionId();
    const child = record.name || result.agent;

    // ponytail: scan native display entries; index only if measured history
    // size warrants it. Persisted fact IDs also deduplicate after reload.
    const displayed = new Set(ctx.sessionManager.getEntries()
      .filter(entry => entry.type === 'custom' && entry.customType === customType)
      .map(entry => entry.data.fact));
    const append = (fact, sender, recipient, body, execution = result.execution) => {
      if (typeof body !== 'string' || !body || displayed.has(fact)) return;
      pi.appendEntry(customType, { fact, sender, recipient, body, agent: result.agent,
        session: result.session, execution, source: 'agents' });
      displayed.add(fact);
    };
    if (['create', 'send', 'resume'].includes(input.action) && record.resumed !== false) {
      append(`send:${event.toolCallId}`, caller, child, input.instruction ?? input.message);
    }
    const reply = record.last_result;
    if (reply?.id) append(`reply:${result.agent}:${reply.id}`, child, caller, reply.last_message, reply.id);
    // appendEntry is Pi's display/state-only path. Do not return a modified
    // tool result or use sendMessage: either would change the model input.
  });
}


/** Resolve the import-only public SDK export of the actual owning Pi CLI. */
export async function loadHostSdk(executable = process.argv[1]) {
  let directory = dirname(realpathSync(executable));
  while (dirname(directory) !== directory) {
    const manifest = join(directory, 'package.json');
    if (existsSync(manifest)) {
      const data = JSON.parse(readFileSync(manifest, 'utf8'));
      if (data.name === '@earendil-works/pi-coding-agent') {
        return import(pathToFileURL(resolve(directory, data.exports['.'].import)).href);
      }
    }
    directory = dirname(directory);
  }
  throw new Error('The owning Pi SDK public entry is unavailable.');
}

/** Capture plugin markers during session_start, before a shared host restores env. */
export function sessionEnvironment(ctx, environment) {
  return {
    GRAPHTRAJ_NATIVE_RUNTIME: 'pi',
    GRAPHTRAJ_NATIVE_SESSION: ctx.sessionManager.getSessionId(),
    GRAPHTRAJ_NATIVE_SESSION_FILE: ctx.sessionManager.getSessionFile() || '',
    PI_SUBAGENT_CHILD: environment.PI_SUBAGENT_CHILD || '',
    PI_SUBAGENT_DEPTH: environment.PI_SUBAGENT_DEPTH || '0',
  };
}

/** Use a child-process overlay; never change the shared host's process.env. */
export function nativeEntry(ctx, environment, event, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn('graphtraj-session', ['pi'], {
      cwd: ctx.cwd, env: { ...process.env, ...environment },
      stdio: ['pipe', 'pipe', 'pipe'], signal,
    });
    let output = '';
    let diagnostic = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', value => { output += value; });
    child.stderr.on('data', value => { diagnostic += value; });
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) reject(new Error(diagnostic || 'GraphTraj native entry failed'));
      else {
        try { resolve(JSON.parse(output)); } catch (error) { reject(error); }
      }
    });
    child.stdin.end(JSON.stringify(event));
  });
}

/** Keep one collector pipe per native Session; no per-token subprocess or log. */
export function startCollection(ctx, environment) {
  return new Promise((resolve, reject) => {
    const child = spawn('graphtraj-session', ['pi', '--collect'], {
      cwd: ctx.cwd, env: { ...process.env, ...environment }, stdio: ['pipe', 'pipe', 'pipe'],
    });
    let diagnostic = '';
    let failure;
    let ready = false;
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', value => { diagnostic = (diagnostic + value).slice(-8192); });
    const ended = new Promise(done => child.on('close', code => {
      if (code !== 0 || !ready) failure = new Error(diagnostic || 'Pi Session collection failed');
      if (failure) reject(failure);
      done();
    }));
    child.on('error', error => { failure = error; reject(error); });
    child.stdin.on('error', error => { failure = error; });
    child.stdin.write(JSON.stringify({header: ctx.sessionManager?.getHeader(),
      entries: ctx.sessionManager?.getEntries(), leafId: ctx.sessionManager?.getLeafId?.()}) + '\n');
    child.stdout.once('data', () => {
      ready = true;
      resolve({
        write(event) {
          if (failure) return Promise.reject(failure);
          return new Promise((done, failed) => child.stdin.write(JSON.stringify(event) + '\n',
            error => error ? failed(error) : done()));
        },
        async close() {
          child.stdin.end();
          await ended;
          if (failure) throw failure;
        },
      });
    });
  });
}

/** Quote an environment value for the existing POSIX bash tool backend. */
function quote(value) {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

/** Own the independent core until native shutdown; MCP only connects to it. */
export function startAgentHost(ctx, config) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.AGENT_SWARM_PYTHON,
      ['-I', '-m', 'graphtraj.runtimes.pi.host', '--config', config], {
        cwd: ctx.cwd, stdio: ['pipe', 'pipe', 'pipe'],
        env: {...process.env, ...sessionEnvironment(ctx, process.env),
          AGENT_SWARM_PI_NODE: process.execPath,
          AGENT_SWARM_PI_MODEL: ctx.model?.id || '',
          AGENT_SWARM_PI_PROVIDER: ctx.model?.provider || ''},
      });
    let diagnostic = '', output = '', failure, ready = false;
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', value => { diagnostic = (diagnostic + value).slice(-8192); });
    const ended = new Promise(done => child.on('close', code => {
      if (code !== 0 || !ready) failure = new Error(diagnostic || 'Independent Pi host failed.');
      if (failure) reject(failure);
      done();
    }));
    child.on('error', error => { failure = error; reject(error); });
    child.stdin.on('error', error => { failure = error; });
    child.stdout.on('data', value => {
      output += value;
      if (ready || !output.includes('\n')) return;
      try {
        const {connection} = JSON.parse(output.slice(0, output.indexOf('\n')));
        if (typeof connection !== 'string' || !connection) throw new Error('No independent host connection.');
        ready = true;
        resolve({connection, async close() {
          child.stdin.end();
          await ended;
          if (failure) throw failure;
        }});
      } catch (error) { child.stdin.end(); reject(error); }
    });
  });
}

export default function graphtraj(pi) {
  const sessions = new WeakMap();
  const collectors = new WeakMap();
  const independent = new WeakSet();
  let agentHost;
  let displayRegistered = false;
  pi.registerFlag('graphtraj-finish-check', { type: 'boolean', default: false,
    description: 'Check Main completion using the current native Session context.' });
  pi.registerFlag('agents-config', { type: 'string',
    description: 'Explicit independent agents host configuration with preflighted Pi settings.' });
  pi.on('session_start', async (event, ctx) => {
    await agentHost?.close();
    agentHost = undefined;
    independent.delete(ctx.sessionManager);
    await collectors.get(ctx.sessionManager)?.close();
    collectors.delete(ctx.sessionManager);
    if (ctx.hasUI && !displayRegistered) {
      registerAgentDisplay(pi, await loadHostSdk());
      displayRegistered = true;
    }
    if (process.env.AGENT_SWARM_CONNECTION) {
      independent.add(ctx.sessionManager);
      // This is the official MCP client wiring, not a native model tool.
      // Identity is verified by the owning host's kernel-authenticated pipe.
      pi.registerMcpServer('agents', {
        command: process.env.AGENT_SWARM_PYTHON, args: ['-I', '-m', 'agent_swarm.mcp'],
        cwd: ctx.cwd, env: {AGENT_SWARM_CONNECTION: process.env.AGENT_SWARM_CONNECTION}, exposure: 'direct',
      });
      return;
    }
    const agentsConfig = pi.getFlag?.('agents-config');
    if (agentsConfig) {
      if (!process.env.AGENT_SWARM_PYTHON) throw new Error('Independent agents requires its selected Python installation.');
      independent.add(ctx.sessionManager);
      agentHost = await startAgentHost(ctx, agentsConfig);
      try {
        pi.registerMcpServer('agents', {
          command: process.env.AGENT_SWARM_PYTHON,
          args: ['-I', '-m', 'agent_swarm.mcp'], cwd: ctx.cwd,
          env: {AGENT_SWARM_CONNECTION: agentHost.connection}, exposure: 'direct',
        });
      } catch (error) { await agentHost.close(); agentHost = undefined; throw error; }
      return;
    }
    const environment = sessionEnvironment(ctx, process.env);
    sessions.set(ctx.sessionManager, environment);
    const result = await nativeEntry(ctx, environment, {
      event: 'session_start', reason: event.reason,
      header: ctx.sessionManager.getHeader(),
      entries: ctx.sessionManager.getEntries().filter(entry => entry.type === 'custom'),
    });
    if (result.error) ctx.ui.notify(result.error, 'error');
    else if (result.source === 'main') ctx.ui.notify('GraphTraj Main Session associated.', 'info');
    if (!result.error && ['main', 'child'].includes(result.source)) {
      collectors.set(ctx.sessionManager, await startCollection(ctx, environment));
    }
    pi.registerMcpServer('graphtraj', {
      command: 'graphtraj-mcp', cwd: ctx.cwd, env: environment, exposure: 'direct',
    });
  });
  for (const kind of ['before_agent_start', 'model_select', 'tool_result', 'agent_start', 'turn_start', 'message_start', 'message_update',
    'message_end', 'tool_execution_start', 'tool_execution_update', 'tool_execution_end',
    'turn_end', 'agent_end', 'session_tree', 'session_compact']) {
    pi.on(kind, async (event, ctx) => {
      const piNative = ['turn_end', 'agent_end', 'session_tree', 'session_compact'].includes(kind)
        ? {entries: ctx.sessionManager.getEntries(), leafId: ctx.sessionManager.getLeafId()} : undefined;
      await collectors.get(ctx.sessionManager)?.write(piNative ? {...event, piNative} : event);
    });
  }
  pi.on('session_shutdown', async (_event, ctx) => {
    await agentHost?.close();
    agentHost = undefined;
    await collectors.get(ctx.sessionManager)?.write({type: 'session_shutdown', piNative: {
      entries: ctx.sessionManager.getEntries(), leafId: ctx.sessionManager.getLeafId(),
    }});
    await collectors.get(ctx.sessionManager)?.close();
    collectors.delete(ctx.sessionManager);
  });
  pi.on('tool_call', async (event, ctx) => {
    await collectors.get(ctx.sessionManager)?.write(event);
    if (event.toolName !== 'bash') return;
    if (independent.has(ctx.sessionManager)) return;
    const environment = sessions.get(ctx.sessionManager);
    if (!environment) return { block: true, reason: 'GraphTraj Session entry is unavailable.' };
    // Preserve the selected bash backend and all native tool/approval handlers.
    // The export affects only this shell and its children, not the Pi process.
    const exports = Object.entries(environment).map(([key, value]) => `${key}=${quote(value)}`).join(' ');
    event.input.command = `export ${exports}\n${event.input.command}`;
  });
  pi.on('agent_before_settle', async (event, ctx) => {
    const environment = sessions.get(ctx.sessionManager);
    if (!pi.getFlag('graphtraj-finish-check') || !environment || event.outcome !== 'completed') return;
    const markers = ctx.sessionManager.getEntries();
    if (environment.PI_SUBAGENT_CHILD === '1' || Number(environment.PI_SUBAGENT_DEPTH) > 0 ||
        markers.some(entry => entry.type === 'custom' && (
          entry.customType === 'graphtraj:completion-checker' && entry.data?.session === environment.GRAPHTRAJ_NATIVE_SESSION ||
          entry.customType === 'pi-subagent:delegation' && entry.data?.childSessionId === environment.GRAPHTRAJ_NATIVE_SESSION
        ))) return;
    ctx.ui.notify('GraphTraj completion check started.', 'info');
    let checker;
    const abort = () => { void checker?.abort(); };
    try {
      const prepared = await nativeEntry(ctx, environment, { event: 'check_context' }, ctx.signal);
      if (prepared.error) throw new Error(prepared.error);
      // Load the SDK belonging to the running Pi, rather than a second installation.
      const sdk = await loadHostSdk();
      const manager = sdk.SessionManager.forkFrom(ctx.sessionManager.getSessionFile(), ctx.cwd);
      manager.appendCustomEntry('graphtraj:completion-checker', {
        session: manager.getSessionId(), parent: ctx.sessionManager.getSessionId(),
      });
      const created = await nativeEntry(ctx, environment, {
        event: 'checker_created', session: manager.getSessionId(),
      }, ctx.signal);
      if (created.error) throw new Error(created.error);
      const settings = sdk.SettingsManager.inMemory(pi.getSettings(), { projectTrusted: ctx.isProjectTrusted() });
      const effort = ctx.thinkingLevel ?? pi.getThinkingLevel();
      const systemPrompt = ctx.getSystemPrompt();
      const loader = new sdk.DefaultResourceLoader({
        cwd: ctx.cwd, settingsManager: settings,
        additionalExtensionPaths: [fileURLToPath(import.meta.url), 'builtin:mcp'],
        extensionFactories: [{ name: 'graphtraj:inherited-prompt', factory: api => {
          api.on('before_agent_start', event => {
            event.systemPromptOptions.forceSystemPrompt = systemPrompt;
          });
        } }],
      });
      await loader.reload();
      ({ session: checker } = await sdk.createAgentSession({
        cwd: ctx.cwd, model: ctx.model, thinkingLevel: effort,
        settingsManager: settings, resourceLoader: loader, sessionManager: manager,
      }));
      if (checker.model?.id !== ctx.model?.id || checker.model?.provider !== ctx.model?.provider ||
          checker.thinkingLevel !== effort) throw new Error('Pi changed the checker model or thinking level.');
      ctx.signal?.addEventListener('abort', abort, { once: true });
      if (ctx.signal?.aborted) return;
      await checker.prompt(prepared.prompt);
      if (ctx.signal?.aborted) return;
      const message = checker.messages.findLast(item => item.role === 'assistant');
      const output = message?.content.filter(item => item.type === 'text').map(item => item.text).join('\n');
      const result = await nativeEntry(ctx, environment, {
        event: 'check_result', session: manager.getSessionId(), output,
        model: checker.model.id, provider: checker.model.provider, effort: checker.thinkingLevel,
      }, ctx.signal);
      if (result.error) throw new Error(result.error);
      ctx.ui.notify(`Completion check ${result.status}: ${result.reason}`, result.status === 'error' ? 'error' : 'info');
      if (result.status === 'actionable') return { continue: true, entries: [{
        type: 'custom_message', customType: 'graphtraj:remaining-work',
        content: [result.reason, ...result.nodes].join('\n'), display: true,
      }] };
    } catch (error) {
      if (!ctx.signal?.aborted) ctx.ui.notify(`Completion check failed: ${error.message}`, 'error');
    } finally {
      ctx.signal?.removeEventListener('abort', abort);
      if (checker) {
        await checker.abort();
        checker.dispose();
      }
    }
  });
}
