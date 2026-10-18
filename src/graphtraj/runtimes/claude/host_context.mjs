/** Native context and human-only observation for the external agents entry.
 *
 * This module does not grant Python gateway authority. It makes the live host
 * facts reviewable while preserving Claude's entire tool/permission chain.
 * It never caches session.start as identity across clear/resume/branch.
 */
function exchangeFrames(session, event, result, seen) {
  if (result.deny || result.isError) return [];
  const content = result.result ?? result.text;
  const text = typeof content === 'string' ? content : Array.isArray(content)
    ? content.filter((block) => block.type === 'text').map((block) => block.text).join('\n') : '';
  let document;
  try { document = JSON.parse(text); } catch { return []; }
  if (!document || document.error || typeof document.agent !== 'string') return [];
  const frames = [];
  const frame = (from, to, body) => `┌ agents · ${from} → ${to}\n${body.split('\n').map((line) => '│ ' + line).join('\n')}\n└`;
  const outgoing = event.action === 'create' ? event.instruction : event.message;
  if (['create', 'send', 'resume'].includes(event.action) && typeof outgoing === 'string'
      && document.result?.resumed !== false) {
    frames.push(frame(session, document.agent, outgoing));
  }
  const last = document.result?.last_result;
  const incoming = last?.last_message || last?.error?.message;
  const key = JSON.stringify([session, document.agent, last?.id]);
  if (last?.id && typeof incoming === 'string' && incoming && !seen.has(key)) {
    frames.push(frame(document.agent, session, incoming));
    seen.add(key);
  }
  return frames.map((value) => value.length <= 10000 ? value
    : value.slice(0, 9800) + '\n… Display truncated; full text remains in the tool input/result.');
}

export function register(on) {
  const displayed = new Set();
  on('session.start', async ($, event, next) => {
    await $.command.register({
      name: 'agents-context',
      description: 'Show current native Session and agents registration without a model turn',
      immediate: true,
    });
    return next(event);
  });

  on('command.run', { command: 'agents-context' }, async ($) => {
    const session = await $.session.id();
    const cwd = await $.session.cwd();
    const tools = await $.tool.list();
    const registered = tools.some((tool) => tool.name === 'mcp__agents__agents');
    $.ui.log(JSON.stringify({ event: 'agents-context', session, cwd, registered }));
    // Command text would enter model history. ui.log is explicitly human-only.
    return {};
  });

  on('tool.call', { tool: 'mcp__agents__agents' }, async ($, event, next) => {
    const session = await $.session.id();
    const cwd = await $.session.cwd();
    // next runs native permissions and the MCP function. No direct process,
    // alternate tool call, or allow/ask/deny interpretation replaces it.
    const result = await next(event);
    $.ui.log(JSON.stringify({ event: 'agents-call', session, cwd,
      action: event.action, denied: Boolean(result.deny), failed: result.isError === true }));
    for (const frame of exchangeFrames(session, event, result, displayed)) $.ui.log(frame);
    return result;
  });

  on('tool.check', { tool: 'mcp__agents__agents' }, async ($, event, next) => {
    const result = await next(event);
    const session = await $.session.id();
    // agentId and ceiling are host fields on tool.check in 2.1.299. Retain
    // their absence rather than inventing a source or deciding an ask.
    $.ui.log(JSON.stringify({ event: 'agents-check', session,
      agentId: event.agentId, ceiling: event.ceiling, decision: result.decision }));
    return result;
  });
}
