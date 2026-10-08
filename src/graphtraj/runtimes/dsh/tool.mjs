/** Native DSH tool invoking GraphTraj's public, process-authenticated CLI. */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';

const require = createRequire(process.env.GRAPHTRAJ_DSH_PACKAGE || process.argv[1]);
const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')));
const { default: z } = await import(pathToFileURL(require.resolve('@deepseek-ai/schemastery')));
export const name = 'graphtraj';
export const inject = ['tools', 'shellEnv'];
export const Config = z.object({ finishCheck: z.boolean().default(false) });

/** Read actual durable source facts from this execution's native Agent. */
export function sessionEnvironment(agent) {
  const header = agent?.session.header;
  if (!header) return {};
  const child = header.origin === 'subagent' || (header.delegationDepth || 0) > 0;
  const main = header.version === 4 && typeof header.id === 'string' &&
    header.origin === undefined && typeof header.isSeeded === 'boolean';
  return {
    DSH_GRAPHTRAJ_SESSION: header.id,
    DSH_GRAPHTRAJ_SOURCE: child ? 'child' : main ? 'main' : 'unknown',
  };
}

export function apply(ctx, config = { finishCheck: false }) {
  ctx.shellEnv.register({
    name: 'graphtraj',
    variables: {
      DSH_GRAPHTRAJ_SESSION: { description: 'GraphTraj association for this native Session.' },
      DSH_GRAPHTRAJ_SOURCE: { description: 'The native Session origin used by GraphTraj.' },
    },
    resolve: execution => sessionEnvironment(execution.agent),
  });
  async function entry(agent, event, signal) {
    // The native callback owns these facts; no model tool parameter selects them.
    const executable = process.env.GRAPHTRAJ_DSH_TOOL?.replace(/graphtraj-tool$/, 'graphtraj-session') || 'graphtraj-session';
    const result = await new Promise((resolve, reject) => {
      const child = spawn(executable, ['dsh'], {
        cwd: agent.session.header.cwd,
        env: { ...process.env, DSH_SESSION_ID: agent.session.id, ...sessionEnvironment(agent) },
        stdio: ['pipe', 'pipe', 'pipe'], signal,
      });
      let output = '';
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', value => { output += value; });
      child.stderr.resume();
      child.on('error', reject);
      child.on('close', code => {
        if (code !== 0) reject(new Error('GraphTraj DSH Session entry failed'));
        else {
          try { resolve(JSON.parse(output)); } catch (error) { reject(error); }
        }
      });
      child.stdin.end(JSON.stringify(event));
    });
    if (result.error) throw new Error(result.error);
    return result;
  }
  ctx.on('agent/created', async ({ agent, source, signal }) => {
    if (process.env.GRAPHTRAJ_ROLE) return; // Existing managed Session registration owns this case.
    await entry(agent, { event: 'agent/created', source, header: agent.session.header }, signal);
  });
  ctx.on('agent/turn-stopping', async ({ agent, signal }) => {
    if (!config.finishCheck || process.env.GRAPHTRAJ_ROLE ||
        sessionEnvironment(agent).DSH_GRAPHTRAJ_SOURCE !== 'main' || signal.aborted) return;
    const { check } = await import('./finalize.mjs');
    await check(ctx, agent, signal, entry);
  });
  ctx.tools.register(defineTool({
    name: 'graphtraj',
    description: 'Discover, describe or execute GraphTraj public operations as this Agent. Authority is supplied by the host, never by tool arguments.',
    parameters: {
      action: { type: 'string', required: true, enum: ['discover', 'describe', 'execute'] },
      query: { type: 'string' },
      feature: { type: 'string' },
      schema: { type: 'boolean' },
      arguments: { type: 'json' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args, execution) {
      // The executable/root come from the owned service, not model arguments.
      // Its child PID retains the native Session's Runner ownership ancestry.
      return await new Promise((resolve, reject) => {
        const child = spawn(process.env.GRAPHTRAJ_DSH_TOOL || 'graphtraj-tool', [], {
          cwd: process.env.GRAPHTRAJ_HARNESS_ROOT || execution.agent?.session.header.cwd,
          env: { ...process.env, ...ctx.shellEnv.collect(execution) },
          stdio: ['pipe', 'pipe', 'pipe'],
          signal: execution.signal,
        });
        let output = '';
        child.stdout.setEncoding('utf8');
        child.stdout.on('data', value => { output += value; });
        child.stderr.resume();
        child.on('error', () => reject(new Error('GraphTraj public CLI unavailable')));
        child.on('close', code => {
          if (code !== 0) reject(new Error('GraphTraj public CLI failed'));
          else resolve(output);
        });
        child.stdin.end(JSON.stringify(args) + '\n');
      });
    },
  }));
}
