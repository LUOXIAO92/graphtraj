/** Independent native context/display hooks and the installed official MCP client. */
import { spawn } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { installCommunication } from './communication.mjs';

// The user's own DSH sets no package variable: resolve from its real entry file.
const require = createRequire(process.env.DSH_AGENT_PACKAGE || process.env.GRAPHTRAJ_DSH_PACKAGE ||
  realpathSync(process.argv[1]));
const mcpClient = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-mcp-client')));
const { default: z } = await import(pathToFileURL(require.resolve('@deepseek-ai/schemastery')));
const { TypertRemoteService, Remote } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-typert-protocol')));
const { createUserMessage } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
export const name = 'agents';
export const inject = ['tools', 'sessionQuery', 'agents'];
// Without mcpCommand this is the host row: the installed bundle's own entry.
export const Config = z.object({ mcpCommand: z.string(), mcpArgs: z.array(String).default([]) });

/** Preserve durable native source; fork ancestry alone is not delegation. */
export function sessionEnvironment(agent) {
  const header = agent?.session.header;
  if (!header) return {};
  const child = header.origin === 'subagent' || (header.delegationDepth || 0) > 0;
  const main = header.version === 4 && typeof header.id === 'string' &&
    header.origin === undefined && typeof header.isSeeded === 'boolean';
  return { DSH_SESSION_ID: header.id, DSH_AGENT_SOURCE: child ? 'child' : main ? 'main' : 'unknown' };
}

/** The relay request that admits one host notice to its DSH main Session once. */
export function noticeMessage(notice, session) {
  const { id, agent, event, message } = notice;
  return { id: `agents-notice:${id}`, sessionId: session, senderSessionId: notice.session || agent,
    sender: agent, recipient: session, body: `[agents notice from ${agent} · ${event}]\n${message}` };
}

/**
 * Start the independent control owner for one native main Session.
 * After the connection line, each host stdout line is one notice for
 * ``onNotice``; it is acknowledged with whether the Session admitted it.
 */
export function startAgentHost(agent, environment, onNotice) {
  return new Promise((resolve, reject) => {
    const child = spawn(environment.AGENT_SWARM_PYTHON,
      ['-I', '-m', 'agent_swarm.dsh.host', '--config', environment.AGENT_SWARM_DSH_CONFIG], {
        cwd: agent.session.header.cwd, stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...environment, AGENT_SWARM_DSH_NODE: process.execPath, AGENT_SWARM_DSH_ENTRY: process.argv[1] },
      });
    let diagnostic = '', output = '', failure, ready = false, closing = false;
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', value => { diagnostic = (diagnostic + value).slice(-8192); });
    const ended = new Promise(done => child.on('close', code => {
      if (code !== 0 || !ready) failure = new Error(diagnostic || 'Independent DSH host failed.');
      if (failure) reject(failure);
      done();
    }));
    child.on('error', error => { failure = error; reject(error); });
    child.stdin.on('error', error => { failure = error; });
    child.stdin.write(JSON.stringify({ header: agent.session.header, model: agent.model?.current()?.model }) + '\n');
    const notice = async line => {
      if (closing) return;
      let document, shown = false;
      try {
        document = JSON.parse(line).notice;
        if (typeof document?.id !== 'string') throw new Error('not a notice');
        shown = (await onNotice(document))?.accepted === true;
      } catch (error) {
        // The host keeps a notice that was not admitted readable through status.
        diagnostic = (diagnostic + `\nNotice delivery failed: ${error.message}`).slice(-8192);
      }
      if (typeof document?.id === 'string' && !closing) child.stdin.write(JSON.stringify({ ack: document.id, shown }) + '\n');
    };
    child.stdout.on('data', value => {
      output += value;
      if (!ready) {
        if (!output.includes('\n')) return;
        try {
          const { connection } = JSON.parse(output.slice(0, output.indexOf('\n')));
          if (typeof connection !== 'string' || !connection) throw new Error('No independent host connection.');
          ready = true;
          output = output.slice(output.indexOf('\n') + 1);
          resolve({ connection, async close() {
            closing = true;
            child.stdin.end();
            await ended;
            if (failure) throw failure;
          } });
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

/** Attach the MCP server ``agents`` to one native Agent. */
function attachMcp(agent, command, args, env) {
  return agent.ctx.plugin(mcpClient, {
    transport: 'stdio', serverName: 'agents', command, args,
    cwd: agent.session.header.cwd, env,
    toolCallTimeoutMs: 300000, failOnStartupError: true,
  }).await();
}

export function apply(ctx, config) {
  installCommunication(ctx, { TypertRemoteService, Remote, createUserMessage });
  if (config.mcpCommand === undefined) return applyHost(ctx);
  ctx.on('agent/created', async ({ agent }) => {
    await attachMcp(agent, config.mcpCommand, config.mcpArgs, {
      ...sessionEnvironment(agent),
      ...(process.env.AGENT_SWARM_CONNECTION ? { AGENT_SWARM_CONNECTION: process.env.AGENT_SWARM_CONNECTION } : {}),
      ...(process.env.GRAPHTRAJ_CLI_CONNECTION ? { GRAPHTRAJ_CLI_CONNECTION: process.env.GRAPHTRAJ_CLI_CONNECTION } : {}),
      ...(process.env.PYTHONPATH ? { PYTHONPATH: process.env.PYTHONPATH } : {}),
    });
  });
}

/**
 * The installed bundle's host row: each native main Session of this DSH owns
 * one ``agent_swarm.dsh.host`` while it is live. Inert without
 * ``AGENT_SWARM_DSH_CONFIG``, and inside a DSH that is already an Agent.
 */
function applyHost(ctx) {
  const environment = process.env;
  if (!environment.AGENT_SWARM_DSH_CONFIG || Object.hasOwn(environment, 'AGENT_SWARM_CONNECTION') ||
      Object.hasOwn(environment, 'DSH_AGENT_PACKAGE')) return;
  const hosts = new Map();
  const close = async id => {
    const host = hosts.get(id);
    hosts.delete(id);
    try { await (await host)?.close(); } catch (error) { ctx.logger?.error?.(`agents host: ${error.message}`); }
  };
  ctx.on('agent/created', async ({ agent }) => {
    const id = agent.session.header?.id;
    if (sessionEnvironment(agent).DSH_AGENT_SOURCE !== 'main' || hosts.has(id)) return;
    if (!environment.AGENT_SWARM_PYTHON) throw new Error('The agents DSH host needs AGENT_SWARM_PYTHON.');
    const started = startAgentHost(agent, environment, notice =>
      ctx.get('agentMessages').receive(noticeMessage(notice, id)));
    hosts.set(id, started);
    let host;
    try {
      host = await started;
      await attachMcp(agent, environment.AGENT_SWARM_PYTHON, ['-I', '-m', 'agent_swarm.mcp'],
        { ...sessionEnvironment(agent), AGENT_SWARM_CONNECTION: host.connection });
    } catch (error) {
      await close(id);
      throw error;
    }
  });
  ctx.on('session/disposed', session => close(session.id));
  ctx.effect(() => () => Promise.all([...hosts.keys()].map(close)));
}
