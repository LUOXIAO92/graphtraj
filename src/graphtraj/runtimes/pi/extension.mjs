/** Pi's session-local GraphTraj entry; loading this file is a native trust step. */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

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

/** Quote an environment value for the existing POSIX bash tool backend. */
function quote(value) {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

export default function graphtraj(pi) {
  const sessions = new WeakMap();
  pi.registerFlag('graphtraj-finish-check', { type: 'boolean', default: false,
    description: 'Check Main completion using the current native Session context.' });
  pi.on('session_start', async (event, ctx) => {
    const environment = sessionEnvironment(ctx, process.env);
    sessions.set(ctx.sessionManager, environment);
    const result = await nativeEntry(ctx, environment, {
      event: 'session_start', reason: event.reason,
      header: ctx.sessionManager.getHeader(),
      entries: ctx.sessionManager.getEntries().filter(entry => entry.type === 'custom'),
    });
    if (result.error) ctx.ui.notify(result.error, 'error');
    else if (result.source === 'main') ctx.ui.notify('GraphTraj Main Session associated.', 'info');
    pi.registerMcpServer('graphtraj', {
      command: 'graphtraj-mcp', cwd: ctx.cwd, env: environment, exposure: 'direct',
    });
  });
  pi.on('tool_call', (event, ctx) => {
    if (event.toolName !== 'bash') return;
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
