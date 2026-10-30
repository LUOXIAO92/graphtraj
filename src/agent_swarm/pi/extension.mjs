/** Pi's session-local independent agents entry; loading this file is a native trust step. */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// How long a Session with a UI that starts no turn by itself waits before taking held notices.
const READY_MS = 2000;
// How often, and how many times, to look for a notice's entry after its message_end.
const ENTRY_POLL_MS = 20;
const ENTRY_POLLS = 250;

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

/** Whether this notice's message is among the Session's ``custom_message`` entries. */
function noticeInSession(manager, fact) {
  // ponytail: scan native entries, as the display does; a notice is rare.
  return manager.getEntries().some(entry => entry.type === 'custom_message' &&
    entry.customType === 'graphtraj:agent-communication' && entry.details?.fact === fact);
}

/**
 * Inject one host notice (a child's answer, permission request or a
 * failed/interrupted end) into this Pi Session through Pi's native
 * custom-message API: an idle Session starts a turn with it, a streaming one
 * receives it as a follow-up. Returns true for a notice replayed after a crash
 * between injecting and acknowledging: it is already among the Session's
 * entries (Pi's ``SessionManager.appendCustomMessageEntry``) and is not
 * injected again. Otherwise Pi has only taken it; see ``registerAgents``.
 */
export function deliverNotice(pi, notice, session, manager) {
  const {id, alias, agent, event, message, execution} = notice;
  const fact = `notice:${id}`;
  if (noticeInSession(manager, fact)) return true;
  pi.sendMessage({
    customType: 'graphtraj:agent-communication',
    content: `[agents notice from ${alias} · ${event}]\n${message}`, display: true,
    details: {fact, sender: alias, recipient: session, body: message,
      agent, execution, event, source: 'agents'},
  }, {triggerTurn: true, deliverAs: 'followUp'});
  return false;
}

/**
 * Own the independent core until native shutdown; MCP only connects to it.
 * After the connection line, each host stdout line is one notice for
 * ``onNotice``: true means it is already in the Session (``shown``), otherwise
 * Pi has taken it (``queued``) and ``shown`` reports it later. After ``close``
 * starts, a notice is neither injected nor acknowledged, so the host keeps it
 * held. ``ready`` tells the host once that it may deliver the notices it holds.
 */
export function startAgentHost(ctx, config, onNotice = () => {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.AGENT_SWARM_PYTHON,
      ['-I', '-m', 'agent_swarm.pi.host', '--config', config], {
        cwd: ctx.cwd, stdio: ['pipe', 'pipe', 'pipe'],
        env: {...process.env, ...sessionEnvironment(ctx, process.env),
          AGENT_SWARM_PI_NODE: process.execPath,
          AGENT_SWARM_PI_ENTRY: process.argv[1],
          AGENT_SWARM_PI_MODEL: ctx.model?.id || '',
          AGENT_SWARM_PI_PROVIDER: ctx.model?.provider || ''},
      });
    let diagnostic = '', output = '', failure, ready = false, closing = false, announced = false;
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
    child.stdin.write(JSON.stringify({header: ctx.sessionManager.getHeader(),
      entries: ctx.sessionManager.getEntries().filter(entry => entry.type === 'custom')}) + '\n');
    const notice = line => {
      if (closing) return;
      let document, inSession;
      try {
        document = JSON.parse(line).notice;
        if (typeof document?.id !== 'string') throw new Error('not a notice');
        inSession = onNotice(document) === true;
      } catch (error) {
        // The host keeps a notice that was not shown readable through status.
        diagnostic = (diagnostic + `\nNotice delivery failed: ${error.message}`).slice(-8192);
        if (typeof document?.id === 'string') child.stdin.write(JSON.stringify({ack: document.id, shown: false}) + '\n');
        return;
      }
      child.stdin.write(JSON.stringify(inSession ? {ack: document.id, shown: true} : {ack: document.id, queued: true}) + '\n');
    };
    child.stdout.on('data', value => {
      output += value;
      if (!ready) {
        if (!output.includes('\n')) return;
        try {
          const {connection} = JSON.parse(output.slice(0, output.indexOf('\n')));
          if (typeof connection !== 'string' || !connection) throw new Error('No independent host connection.');
          ready = true;
          output = output.slice(output.indexOf('\n') + 1);
          resolve({connection, ready() {
            if (closing || announced) return;
            announced = true;
            child.stdin.write('{"ready":true}\n');
          }, shown(id) {
            if (!closing) child.stdin.write(JSON.stringify({ack: id, shown: true}) + '\n');
          }, async close() {
            closing = true;
            child.stdin.end();
            await ended;
            if (failure) throw failure;
          }});
        } catch (error) { child.stdin.end(); reject(error); return; }
      }
      let end;
      while ((end = output.indexOf('\n')) >= 0) {
        const line = output.slice(0, end);
        output = output.slice(end + 1);
        notice(line);
      }
    });
  });
}

/**
 * Register the independent agents connection on this Pi extension API.
 * The returned handlers report whether they own the started Session.
 */
export function registerAgents(pi) {
  const independent = new WeakSet();
  let agentHost;
  let readyTimer;
  let sessionManager;
  let displayRegistered = false;
  pi.registerFlag('agents-config', { type: 'string',
    description: 'Independent agents host configuration: data root and optional per-Runtime settings.' });
  // A held notice starts a turn in an idle Session, and Pi refuses a prompt
  // while a turn runs (AgentSession.prompt, print mode has no streamingBehavior).
  // So the host flushes during the Session's first turn; a Session with a UI
  // that starts none by itself gets its held notices after READY_MS.
  pi.on('agent_start', () => { agentHost?.ready(); });
  // A notice is delivered once Pi has written it to the Session, which a quit
  // during the turn would prevent. Handlers run before that write
  // (AgentSession._handleAgentEvent, dist/core/agent-session.js:752 then :760),
  // so look for the entry itself; without one the next host replays the notice.
  const confirmEntry = (host, fact, polls = ENTRY_POLLS) => {
    if (host !== agentHost) return;
    if (noticeInSession(sessionManager, fact)) host.shown(fact.slice('notice:'.length));
    else if (polls > 0) setTimeout(confirmEntry, ENTRY_POLL_MS, host, fact, polls - 1).unref?.();
  };
  pi.on('message_end', event => {
    const fact = event.message?.role === 'custom' ? event.message.details?.fact : undefined;
    if (agentHost && typeof fact === 'string' && fact.startsWith('notice:')) confirmEntry(agentHost, fact);
  });
  const closeHost = async () => {
    clearTimeout(readyTimer);
    // Cleared first: a host that failed to close must not fail the next start too.
    const host = agentHost;
    agentHost = undefined;
    await host?.close();
  };
  return {
    independent,
    async start(ctx) {
      await closeHost();
      independent.delete(ctx.sessionManager);
      if (ctx.hasUI && !displayRegistered) {
        registerAgentDisplay(pi, await loadHostSdk());
        displayRegistered = true;
      }
      if (Object.hasOwn(process.env, 'AGENT_SWARM_CONNECTION')) {
        if (!process.env.AGENT_SWARM_CONNECTION) throw new Error('The existing Agent connection is empty; no identity was adopted.');
        independent.add(ctx.sessionManager);
        // This is the official MCP client wiring, not a native model tool.
        // Identity is verified by the owning host's kernel-authenticated pipe.
        pi.registerMcpServer('agents', {
          command: process.env.AGENT_SWARM_PYTHON, args: ['-I', '-m', 'agent_swarm.mcp'],
          cwd: ctx.cwd, env: {AGENT_SWARM_CONNECTION: process.env.AGENT_SWARM_CONNECTION}, exposure: 'direct',
        });
        return true;
      }
      const agentsConfig = pi.getFlag?.('agents-config');
      if (agentsConfig) {
        if (Object.hasOwn(process.env, 'DSH_SESSION_ID') || Object.hasOwn(process.env, 'DSH_AGENT_SOURCE')) {
          throw new Error('Standalone agents config cannot replace an existing managed Agent context; retain its owning connection.');
        }
        if (!process.env.AGENT_SWARM_PYTHON) throw new Error('Independent agents requires its selected Python installation.');
        independent.add(ctx.sessionManager);
        const session = ctx.sessionManager.getSessionId();
        sessionManager = ctx.sessionManager;
        agentHost = await startAgentHost(ctx, agentsConfig, notice => deliverNotice(pi, notice, session, sessionManager));
        try {
          pi.registerMcpServer('agents', {
            command: process.env.AGENT_SWARM_PYTHON,
            args: ['-I', '-m', 'agent_swarm.mcp'], cwd: ctx.cwd,
            env: {AGENT_SWARM_CONNECTION: agentHost.connection}, exposure: 'direct',
          });
        } catch (error) { await closeHost(); throw error; }
        if (ctx.hasUI) readyTimer = setTimeout(() => agentHost?.ready(), READY_MS);
        return true;
      }
      return false;
    },
    close: closeHost,
  };
}

export default function agents(pi) {
  const owner = registerAgents(pi);
  pi.on('session_start', async (_event, ctx) => { await owner.start(ctx); });
  pi.on('session_shutdown', async () => { await owner.close(); });
}
