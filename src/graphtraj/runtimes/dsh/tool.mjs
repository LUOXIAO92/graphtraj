/** GraphTraj lifecycle/context hooks; Agents MCP belongs to the independent adapter. */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { installCollection } from './collection.mjs';
import { sessionEnvironment as nativeSessionEnvironment } from '../../../agent_swarm/dsh/plugin.mjs';

const require = createRequire(process.env.GRAPHTRAJ_DSH_PACKAGE || process.argv[1]);
const { default: z } = await import(pathToFileURL(require.resolve('@deepseek-ai/schemastery')));
const { createUserMessage } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm')));
export const name = 'graphtraj';
export const inject = ['tools', 'shellEnv', 'sessionQuery', 'agents'];
export const Config = z.object({ finishCheck: z.boolean().default(false) });

/**
 * Deliver the DSH Main's queued GraphTraj notices through its native inbox,
 * as the agents plugin relays Agent messages; acknowledge only after send.
 */
export async function deliverNotices(agent, entry) {
  const pending = await entry(agent, { event: 'notices' });
  if (!pending.notices) return 0;
  agent.send(createUserMessage({
    content: [{ type: 'text', text: pending.text }],
    source: { kind: 'agent-message', form: 'relay', senderSessionId: 'graphtraj', senderAgentId: 'graphtraj',
      recipientAgentId: agent.session.id, communicationId: `graphtraj-notice:${agent.session.id}:${pending.position}` },
  }), 'next-step', true);
  await entry(agent, { event: 'notices_ack', position: pending.position });
  return pending.notices;
}

/** Read actual durable source facts from this execution's native Agent. */
export function sessionEnvironment(agent) {
  const native = nativeSessionEnvironment(agent);
  return { DSH_GRAPHTRAJ_SESSION: native.DSH_SESSION_ID, DSH_GRAPHTRAJ_SOURCE: native.DSH_AGENT_SOURCE };
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
    const executable = process.env.GRAPHTRAJ_DSH_TOOL || 'graphtraj-session';
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
  const agentsOnly = process.env.GRAPHTRAJ_DSH_AGENTS_ONLY === '1';
  const collect = agentsOnly ? async () => {} : installCollection(ctx, entry);
  // The Main Session's notice loop: delivered at entry, then every 5 seconds.
  const noticeLoops = new Map();
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
