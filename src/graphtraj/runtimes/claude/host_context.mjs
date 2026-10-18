/** Native context and human-only observation for the external agents entry.
 *
 * This module associates the current native call with its MCP owner while
 * preserving Claude's entire tool/permission chain.
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

async function context($, document) {
  const python = await $.env.get('GRAPHTRAJ_CLAUDE_HOST_PYTHON');
  const config = await $.env.get('GRAPHTRAJ_CLAUDE_HOST_CONFIG');
  if (!python || !config) throw new Error('Native agents host configuration is missing.');
  const result = await $.process.run([python, '-m', 'graphtraj.runtimes.claude.host',
    'context', '--config', config], {stdin: JSON.stringify(document)});
  if (result.exitCode !== 0) throw new Error('Native agents association failed: ' + result.stderr);
  return JSON.parse(result.stdout);
}

export function register(on) {
  const displayed = new Set();
  let busy = false;
  on('session.start', async ($, event, next) => {
    await $.command.register({name: 'agents-context',
      description: 'Show current native Session and agents registration without a model turn', immediate: true});
    return next(event);
  });

  on('command.run', {command: 'agents-context'}, async ($) => {
    const session = await $.session.id();
    const tools = await $.tool.list();
    $.ui.log(`agents · current Session ${session}\n` +
      (tools.some((tool) => tool.name === 'mcp__agents__agents') ? 'MCP agents registered' : 'MCP agents missing'));
    return {};
  });

  on('tool.call', {tool: 'mcp__agents__agents'}, async ($, event, next) => {
    // No association may overlap another native permission chain. A refused
    // concurrent call never clears or consumes the first call's context.
    if (busy) return {deny: 'Another agents call is pending; wait for its result.'};
    busy = true;
    try {
      await context($, {operation: 'end'});
      const result = await next(event);
      const session = await $.session.id();
      const request = event.action === 'execute' ? {action: event.feature, ...event.arguments} : event;
      for (const frame of exchangeFrames(session, request, result, displayed)) $.ui.log(frame);
      return result;
    } catch (error) {
      return {deny: String(error)};
    } finally {
      try { await context($, {operation: 'end'}); }
      catch (error) { $.ui.log('agents context cleanup failed: ' + String(error)); }
      busy = false;
    }
  }).catch(async ($, event, next) => next.called ? next(event)
    : {deny: 'The native agents context hook failed; no call was authorized.'});

  on('tool.check', {tool: 'mcp__agents__agents'}, async ($, event, next) => {
    const result = await next(event);
    if (result.decision === 'deny') return result;
    // agentId is an official host field, never a model argument. Native
    // subagents must use an actual child binding, not inherit Main authority.
    if (event.agentId) return {decision: 'deny', reason: 'This MCP owner is bound to the Main conversation.'};
    try {
      await context($, {operation: 'prepare', session: await $.session.id(),
        cwd: await $.session.cwd(), agent: event.agentId ?? null, request: event.input});
      return result; // Preserve allow/ask and the original reason/ceiling.
    } catch (error) {
      return {decision: 'deny', reason: String(error)};
    }
  }).catch(async () => ({decision: 'deny', reason: 'Current native agents association is unavailable.'}));

  on('session.end', async ($, event, next) => {
    try { await context($, {operation: 'end'}); }
    catch (error) { $.ui.log('agents context cleanup failed: ' + String(error)); }
    return next(event);
  });
}
