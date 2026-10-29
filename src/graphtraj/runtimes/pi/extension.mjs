/** Pi's session-local GraphTraj entry; loading this file is a native trust step. */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
// A supported agent-swarm distribution (the range in pyproject.toml) installs beside this package.
import { loadHostSdk, registerAgents, sessionEnvironment } from '../../../agent_swarm/pi/extension.mjs';

export { loadHostSdk, registerAgentDisplay, sessionEnvironment, startAgentHost } from '../../../agent_swarm/pi/extension.mjs';

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

/**
 * Deliver this Main's queued GraphTraj notices as one custom message that
 * starts a turn when idle; acknowledge only after Pi took the message.
 */
export async function deliverNotices(pi, ctx, environment) {
  const pending = await nativeEntry(ctx, environment, { event: 'notices' });
  if (pending.error) throw new Error(pending.error);
  if (!pending.notices) return 0;
  pi.sendMessage({ customType: 'graphtraj:main-notice', content: pending.text, display: true },
    { triggerTurn: true, deliverAs: 'followUp' });
  const acknowledged = await nativeEntry(ctx, environment, { event: 'notices_ack', position: pending.position });
  if (acknowledged.error) throw new Error(acknowledged.error);
  return pending.notices;
}

/** Quote an environment value for the existing POSIX bash tool backend. */
function quote(value) {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

export default function graphtraj(pi) {
  const sessions = new WeakMap();
  const collectors = new WeakMap();
  const agents = registerAgents(pi);
  const independent = agents.independent;
  // One notice loop for the Session currently associated as Main; a later
  // session_start or shutdown ends the earlier loop.
  let noticeLoop = 0;
  const pullNotices = (ctx, environment, loop = ++noticeLoop) => {
    const timer = setTimeout(async () => {
      if (loop !== noticeLoop) return;
      try { await deliverNotices(pi, ctx, environment); }
      catch (error) { ctx.ui.notify(`GraphTraj notice delivery failed: ${error.message}`, 'error'); }
      if (loop === noticeLoop) pullNotices(ctx, environment, loop);
    }, 5000);
    timer.unref?.();
  };
  pi.registerFlag('graphtraj-finish-check', { type: 'boolean', default: false,
    description: 'Check Main completion using the current native Session context.' });
  pi.on('session_start', async (event, ctx) => {
    noticeLoop++;
    await collectors.get(ctx.sessionManager)?.close();
    collectors.delete(ctx.sessionManager);
    // A GraphTraj-bound Session keeps its GraphTraj owner: it adopts neither
    // an inherited independent connection nor a standalone agents host.
    if (Object.hasOwn(process.env, 'GRAPHTRAJ_CLI_CONNECTION')) {
      if (Object.hasOwn(process.env, 'AGENT_SWARM_CONNECTION')) {
        throw new Error('Conflicting existing Agent connections; no identity was adopted.');
      }
      if (pi.getFlag?.('agents-config')) {
        throw new Error('Standalone agents config cannot replace an existing managed Agent context; retain its owning connection.');
      }
    }
    if (await agents.start(ctx)) return;
    const environment = sessionEnvironment(ctx, process.env);
    sessions.set(ctx.sessionManager, environment);
    const result = await nativeEntry(ctx, environment, {
      event: 'session_start', reason: event.reason,
      header: ctx.sessionManager.getHeader(),
      entries: ctx.sessionManager.getEntries().filter(entry => entry.type === 'custom'),
    });
    if (result.error) ctx.ui.notify(result.error, 'error');
    else if (result.source === 'main') {
      ctx.ui.notify('GraphTraj Main Session associated.', 'info');
      pullNotices(ctx, environment);
    }
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
    noticeLoop++;
    await agents.close();
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
