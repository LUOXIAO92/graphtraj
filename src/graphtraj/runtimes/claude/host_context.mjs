/** Native context and human-only observation for the external agents entry.
 *
 * This module does not grant Python gateway authority. It makes the live host
 * facts reviewable while preserving Claude's entire tool/permission chain.
 * It never caches session.start as identity across clear/resume/branch.
 */
export function register(on) {
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
