/** DSH's native turn-stopping owner: fork, collect, and steer only actionable work. */
import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(process.env.GRAPHTRAJ_DSH_PACKAGE || process.argv[1]);
const load = name => import(pathToFileURL(require.resolve(name)).href);

/** Keep the open source turn intact; DSH closes only the copied fork tail. */
export async function check(ctx, parent, signal, entry) {
  const { buildForkSeed, SessionLogOffset } = await load('@deepseek-ai/dsh-session');
  const { foldConsumedWork } = await load('@deepseek-ai/dsh-agent');
  const { createUserMessage } = await load('@deepseek-ai/dsh-llm');
  const { applyChildComposition, childSessionMeta, resolveChildAgentOptions,
    resolveChildDepth, finalAssistantOutput } = await load('@deepseek-ai/dsh-subagent');
  let handle;
  const abort = () => handle?.agent.cancel({ kind: 'parent' });
  ctx.logger.info('GraphTraj completion check started.');
  try {
    const prepared = await entry(parent, { event: 'check_context' }, signal);
    if (prepared.error) throw new Error(prepared.error);
    const source = parent.session.snapshotEvents();
    const seed = source.length ? buildForkSeed(source, source.at(-1).seq) : [];
    const depth = resolveChildDepth(parent, undefined);
    handle = await parent.ctx.agents.create({
      sessionId: randomUUID(), parentAgent: parent, signal,
      seed, inheritedEventCount: SessionLogOffset(source.length),
      meta: childSessionMeta(parent, depth, true),
      agentOptions: resolveChildAgentOptions(parent, undefined, depth),
      setup: childCtx => applyChildComposition(childCtx, parent, {}),
    });
    const child = handle.agent;
    const created = await entry(parent, {
      event: 'checker_created', session: child.session.id,
    }, signal);
    if (created.error) throw new Error(created.error);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) return;
    const boundary = SessionLogOffset(child.session.snapshotEvents().length);
    child.followup(createUserMessage({
      content: [{ type: 'text', text: prepared.prompt }], source: { kind: 'user' },
    }));
    await child.whenIdle();
    if (signal.aborted) return;
    const own = child.session.snapshotEvents(boundary);
    if (foldConsumedWork(own).end?.data.reason.kind !== 'completed') {
      throw new Error('The native DSH checker did not complete.');
    }
    const current = parent.session.requestHeader()?.config;
    const effective = child.session.requestHeader()?.config;
    if (!current || !effective) throw new Error('DSH current request configuration is unavailable.');
    for (const field of ['provider', 'model', 'reasoningEffort']) {
      if (current[field] !== effective[field]) throw new Error(`DSH changed checker ${field}.`);
    }
    const output = (finalAssistantOutput(own) || []).filter(block => block.type === 'text')
      .map(block => block.text).join('\n');
    const result = await entry(parent, {
      event: 'check_result', session: child.session.id, output,
      model: effective.model, provider: effective.provider, effort: effective.reasoningEffort,
    }, signal);
    if (result.error) throw new Error(result.error);
    ctx.logger.info(`Completion check ${result.status}: ${result.reason}`);
    if (result.status === 'actionable' && !signal.aborted) {
      parent.steer(createUserMessage({
        content: [{ type: 'text', text: [result.reason, ...result.nodes].join('\n') }],
        source: { kind: 'user' },
      }));
    }
  } catch (error) {
    if (!signal.aborted) ctx.logger.error(`Completion check failed: ${error.message}`);
  } finally {
    signal.removeEventListener('abort', abort);
    if (handle) await handle.dispose();
  }
}
