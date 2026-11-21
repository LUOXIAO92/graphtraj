/** GraphTraj lifecycle/context hooks; Agents MCP belongs to the independent adapter. */
import { realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { installCollection } from './collection.mjs';
// The installed graftling distribution (the range in pyproject.toml), wherever it is.
import { graftlingImport } from '../graftling.mjs';

const { sessionEnvironment: nativeSessionEnvironment } = await graftlingImport('dsh/plugin.mjs');

// A user-started DSH sets no package variable: resolve from its real entry file,
// since an installed `dsh` command is usually a symlink to it.
const require = createRequire(process.env.GRAPHTRAJ_DSH_PACKAGE || realpathSync(process.argv[1]));
const { default: z } = await import(pathToFileURL(require.resolve('@deepseek-ai/schemastery')));
const { createUserMessage } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
export const name = 'graphtraj';
export const inject = ['tools', 'shellEnv', 'sessionQuery', 'agents'];
// python: set only by a user-started Main's patch (`graphtraj.runtimes.dsh.main_entry`).
// It names the GraphTraj installation whose commands this plugin starts.
export const Config = z.object({ finishCheck: z.boolean().default(false), python: z.string() });

/** The Main's own tasks/agents MCP server; its Session comes only from the native header. */
async function attachMain(agent, python) {
  const mcpClient = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-mcp-client')));
  const { DSH_SESSION_ID, DSH_AGENT_SOURCE } = nativeSessionEnvironment(agent);
  await agent.ctx.plugin(mcpClient, {
    transport: 'stdio', serverName: 'graphtraj', command: python,
    args: ['-I', '-m', 'graphtraj.interfaces.mcp'], cwd: agent.session.header.cwd,
    env: { DSH_SESSION_ID, DSH_AGENT_SOURCE }, toolCallTimeoutMs: 300000, failOnStartupError: true,
  }).await();
}

/**
 * Deliver the DSH Main's queued GraphTraj notices through its native inbox,
 * as the agents plugin relays Agent messages; acknowledge only after send.
 * Each notice is one relay from the member that ended (538): the model reads
 * its `graftling.notice_text` (title with the execution, Markdown content,
 * Facts), and the sender is the member's alias, so graftling-dsh's browser
 * module names the member rather than 'graphtraj'.
 * Each relay goes to the next-turn inbox (545): a running turn's later steps
 * claim only next-step input, so a notice that arrives mid-turn opens its own
 * turn when that turn ends (one per notice), shown as a notice block rather
 * than folded into the running turn as a context node.
 */
export async function deliverNotices(agent, entry) {
  const pending = await entry(agent, { event: 'notices' });
  if (!pending.notices) return 0;
  pending.items.forEach(({ text, sender }, index) => agent.send(createUserMessage({
    content: [{ type: 'text', text }],
    source: { kind: 'agent-message', form: 'relay', senderSessionId: sender, senderAgentId: sender,
      recipientAgentId: agent.session.id,
      communicationId: `graphtraj-notice:${agent.session.id}:${pending.position}:${index}` },
  }), 'next-turn', true));
  await entry(agent, { event: 'notices_ack', position: pending.position });
  return pending.notices;
}

/** Read actual durable source facts from this execution's native Agent. */
export function sessionEnvironment(agent) {
  const native = nativeSessionEnvironment(agent);
  return { DSH_GRAPHTRAJ_SESSION: native.DSH_SESSION_ID, DSH_GRAPHTRAJ_SOURCE: native.DSH_AGENT_SOURCE };
}

export function apply(ctx, config = { finishCheck: false }) {
  // graftling-dsh's host row would make this Session a second, Task-free agents host.
  if (config.python && process.env.GRAFTLING_DSH_CONFIG) {
    throw new Error('GraphTraj DSH Main: unset GRAFTLING_DSH_CONFIG; graftling-dsh must not host this Session too.');
  }
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
    const [executable, args] = config.python
      ? [config.python, ['-I', '-m', 'graphtraj.runtimes.native_entry', 'dsh']]
      : [process.env.GRAPHTRAJ_DSH_TOOL || 'graphtraj-session', ['dsh']];
    const result = await new Promise((resolve, reject) => {
      const child = spawn(executable, args, {
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
  const agentsOnly = process.env.GRAPHTRAJ_DSH_AGENTS_ONLY === '1';
  const collect = agentsOnly ? async () => {} : installCollection(ctx, entry);
  // The Main Session's notice loop: delivered at entry, then every 5 seconds.
  const noticeLoops = new Map();
  const attached = new Set();
  const stopNotices = id => { clearTimeout(noticeLoops.get(id)); noticeLoops.delete(id); };
  const pullNotices = agent => {
    const id = agent.session.id;
    const pull = async () => {
      try { await deliverNotices(agent, entry); }
      catch (error) { ctx.logger.error(`GraphTraj notice delivery failed: ${error.message}`); }
      if (noticeLoops.has(id)) noticeLoops.set(id, setTimeout(pull, 5000).unref());
    };
    noticeLoops.set(id, undefined);
    return pull();
  };
  ctx.on('session/disposed', session => stopNotices(session.id));
  ctx.effect(() => () => { for (const id of [...noticeLoops.keys()]) stopNotices(id); });
  ctx.on('agent/created', async ({ agent, source, signal }) => {
    if (!agentsOnly && !process.env.GRAPHTRAJ_ROLE) {
      const result = await entry(agent, { event: 'agent/created', source, header: agent.session.header }, signal);
      // agent/created repeats for one Session (resume, compact); attach its server once.
      if (result.source === 'main' && config.python && !attached.has(agent.session.id)) {
        attached.add(agent.session.id);
        await attachMain(agent, config.python);
      }
      if (result.source === 'main' && !noticeLoops.has(agent.session.id)) await pullNotices(agent);
    }
    await collect(agent, source);
  });
  ctx.on('agent/turn-stopping', async ({ agent, signal }) => {
    if (agentsOnly || !config.finishCheck || process.env.GRAPHTRAJ_ROLE ||
        sessionEnvironment(agent).DSH_GRAPHTRAJ_SOURCE !== 'main' || signal.aborted) return;
    const { check } = await import('./finalize.mjs');
    await check(ctx, agent, signal, entry);
  });
}
