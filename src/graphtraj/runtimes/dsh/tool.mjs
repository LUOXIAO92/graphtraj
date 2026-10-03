/** Native DSH tool invoking GraphTraj's public, process-authenticated CLI. */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';

const require = createRequire(process.env.GRAPHTRAJ_DSH_PACKAGE);
const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')));
export const name = 'graphtraj';
export const inject = ['tools'];

export function apply(ctx) {
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
        const child = spawn(process.env.GRAPHTRAJ_DSH_TOOL, [], {
          cwd: process.env.GRAPHTRAJ_HARNESS_ROOT,
          env: process.env,
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
