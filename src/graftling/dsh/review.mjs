/**
 * The review plugin's native row, loaded only for a connection that names a
 * reviewer: every tool call DSH itself would allow becomes an approval ask the
 * owner judges (dsh/execution.py) before the call runs.
 *
 * The ask is marked by a key of ``displayReason``. Native asks set only fixed
 * locale keys there, and a model's text reaches their values, never a key, so
 * only in-process code can make an ask look like this one.
 */
import { writeFileSync } from 'node:fs';

export const name = 'agents-review';
export const MARKER = 'agents-review';
// The bound agents tool is the child's channel to its parent, limited by agents'
// authority checks, and must work when the reviewer is down.
export const AGENTS_TOOL = 'mcp__agents__agents';

export function apply(ctx, config) {
  ctx.on('tools/pre-execute', async (exec, next) => {
    const decision = await next();
    // A native deny stays denied; a native ask stays a native request for the parent.
    if (decision.kind !== 'allow' || exec.name === AGENTS_TOOL) return decision;
    const call = { tool: exec.name, call_id: exec.callId, input: exec.arguments };
    return { kind: 'ask', reason: `agents review of tool "${exec.name}"`,
      displayReason: { en: `agents review of tool "${exec.name}"`, [MARKER]: JSON.stringify(call) } };
  }, { prepend: true });
  // Written last: its existence tells the owner this hook is registered.
  writeFileSync(config.readyFile, `${process.pid}\n`);
}
