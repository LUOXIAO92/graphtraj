/** Pi's session-local independent agents entry; loading this file is a native trust step. */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

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

/** Own the independent core until native shutdown; MCP only connects to it. */
export function startAgentHost(ctx, config) {
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
    child.stdin.write(JSON.stringify({header: ctx.sessionManager.getHeader(),
      entries: ctx.sessionManager.getEntries().filter(entry => entry.type === 'custom')}) + '\n');
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

/**
 * Register the independent agents connection on this Pi extension API.
 * The returned handlers report whether they own the started Session.
 */
export function registerAgents(pi) {
  const independent = new WeakSet();
  let agentHost;
  let displayRegistered = false;
  pi.registerFlag('agents-config', { type: 'string',
    description: 'Explicit independent agents host configuration with preflighted Pi settings.' });
  return {
    independent,
    async start(ctx) {
      await agentHost?.close();
      agentHost = undefined;
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
        agentHost = await startAgentHost(ctx, agentsConfig);
        try {
          pi.registerMcpServer('agents', {
            command: process.env.AGENT_SWARM_PYTHON,
            args: ['-I', '-m', 'agent_swarm.mcp'], cwd: ctx.cwd,
            env: {AGENT_SWARM_CONNECTION: agentHost.connection}, exposure: 'direct',
          });
        } catch (error) { await agentHost.close(); agentHost = undefined; throw error; }
        return true;
      }
      return false;
    },
    async close() {
      await agentHost?.close();
      agentHost = undefined;
    },
  };
}

export default function agents(pi) {
  const owner = registerAgents(pi);
  pi.on('session_start', async (_event, ctx) => { await owner.start(ctx); });
  pi.on('session_shutdown', async () => { await owner.close(); });
}
