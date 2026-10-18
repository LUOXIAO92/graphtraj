/** Independent native context/display hooks and the installed official MCP client. */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { installCommunication } from './communication.mjs';

const require = createRequire(process.env.DSH_AGENT_PACKAGE || process.env.GRAPHTRAJ_DSH_PACKAGE || process.argv[1]);
const mcpClient = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-mcp-client')));
const { default: z } = await import(pathToFileURL(require.resolve('@deepseek-ai/schemastery')));
const { TypertRemoteService, Remote } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-typert-protocol')));
const { createUserMessage } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
export const name = 'agents';
export const inject = ['tools', 'sessionQuery', 'agents'];
export const Config = z.object({ mcpCommand: z.string().required(), mcpArgs: z.array(String).default([]) });

/** Preserve durable native source; fork ancestry alone is not delegation. */
export function sessionEnvironment(agent) {
  const header = agent?.session.header;
  if (!header) return {};
  const child = header.origin === 'subagent' || (header.delegationDepth || 0) > 0;
  const main = header.version === 4 && typeof header.id === 'string' &&
    header.origin === undefined && typeof header.isSeeded === 'boolean';
  return { DSH_SESSION_ID: header.id, DSH_AGENT_SOURCE: child ? 'child' : main ? 'main' : 'unknown' };
}

export function apply(ctx, config) {
  installCommunication(ctx, { TypertRemoteService, Remote, createUserMessage });
  ctx.on('agent/created', async ({ agent }) => {
    await agent.ctx.plugin(mcpClient, {
      transport: 'stdio', serverName: 'agents',
      command: config.mcpCommand, args: config.mcpArgs,
      cwd: agent.session.header.cwd,
      env: {
        ...sessionEnvironment(agent),
        ...(process.env.AGENT_SWARM_CONNECTION ? { AGENT_SWARM_CONNECTION: process.env.AGENT_SWARM_CONNECTION } : {}),
        ...(process.env.GRAPHTRAJ_CLI_CONNECTION ? { GRAPHTRAJ_CLI_CONNECTION: process.env.GRAPHTRAJ_CLI_CONNECTION } : {}),
        ...(process.env.PYTHONPATH ? { PYTHONPATH: process.env.PYTHONPATH } : {}),
      },
      toolCallTimeoutMs: 300000, failOnStartupError: true,
    }).await();
  });
}
