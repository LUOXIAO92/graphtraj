/** Native context and human-only observation for the external agents entry.
 *
 * This module associates the current native call with its MCP owner while
 * preserving Claude's entire tool/permission chain.
 * It never caches session.start as identity across clear/resume/branch.
 */
function noticeFrames(session, document, frame) {
  // Member events queued for this Main arrive with its next agents/tasks result.
  const frames = [];
  for (const notice of Array.isArray(document.main_notices) ? document.main_notices : []) {
    const body = notice.event;
    const sender = typeof body?.alias === 'string' ? body.alias : 'graphtraj';
    const text = typeof body?.message === 'string' ? body.message : JSON.stringify(notice.event);
    frames.push(frame(sender, session, text));
  }
  return frames;
}

function noticePrompt(notices) {
  // One plain-text Main input; the full structured notices stay in the queue history.
  return notices.map((notice) => {
    const body = notice.event ?? {};
    return `[GraphTraj notice from ${body.alias ?? 'graphtraj'} · ${body.event ?? 'event'}]\n${body.message ?? JSON.stringify(body)}`;
  }).join('\n\n');
}

function exchangeFrames(session, event, result, seen) {
  if (result.deny || result.isError) return [];
  const content = result.result ?? result.text;
  const text = typeof content === 'string' ? content : Array.isArray(content)
    ? content.filter((block) => block.type === 'text').map((block) => block.text).join('\n') : '';
  let document;
  try { document = JSON.parse(text); } catch { return []; }
  if (!document) return [];
  const frames = [];
  const frame = (from, to, body) => `┌ agents · ${from} → ${to}\n${body.split('\n').map((line) => '│ ' + line).join('\n')}\n└`;
  if (document.error || typeof document.agent !== 'string') return noticeFrames(session, document, frame);
  const outgoing = event.action === 'create' ? event.instruction : event.message;
  if (['create', 'send', 'resume'].includes(event.action) && typeof outgoing === 'string'
      && document.result?.resumed !== false) {
    frames.push(frame(session, document.agent, outgoing));
  }
  const last = document.result?.last_result;
  const incoming = last?.last_message || last?.error?.message;
  const key = JSON.stringify([session, document.agent, last?.id]);
  if (last?.id && document.execution === last.id
      && typeof incoming === 'string' && incoming && !seen.has(key)) {
    frames.push(frame(document.agent, session, incoming));
    seen.add(key);
  }
  frames.push(...noticeFrames(session, document, frame));
  return frames.map((value) => value.length <= 10000 ? value
    : value.slice(0, 9800) + '\n… Display truncated; full text remains in the tool input/result.');
}

async function context($, document) {
  const python = await $.env.get('GRAPHTRAJ_CLAUDE_HOST_PYTHON');
  const config = await $.env.get('GRAPHTRAJ_CLAUDE_HOST_CONFIG');
  if (!python || !config) throw new Error('Native agents host configuration is missing.');
  const result = await $.process.run([python, '-m', 'agent_swarm.claude.host',
    'context', '--config', config], {stdin: JSON.stringify(document)});
  if (result.exitCode !== 0) throw new Error('Native agents association failed: ' + result.stderr);
  return JSON.parse(result.stdout);
}

// Deliver member events into the Main's turn or its idle Session through
// Claude's own prompt submission. Reading claims the notices, so a tool result
// never shows them again; a failed submission returns them to the queue.
// Without that host capability the notices stay queued for the next result.
function startPush($, state) {
  if (state.pushing) return;
  state.pushing = true;
  schedulePush($, state);
}

function schedulePush($, state) {
  const run = () => pushNotices($, state).finally(() => schedulePush($, state));
  try {
    $.clock.setTimeout(run, 5000);
  } catch {
    setTimeout(run, 5000);
  }
}

// One push at a time per process: the timer and the re-check after the last
// running agents/tasks call share it, so a resumed Session or an overlapping
// completion never starts a second loop.
async function pushNotices($, state) {
  if (state.inflight || state.active > 0 || state.stopped) return;
  state.inflight = true;
  let claimed = [];
  let session;
  try {
    session = await $.session.id();
    const pending = await context($, {operation: 'notices', session});
    claimed = pending.notices ?? [];
    if (claimed.length) {
      await $.prompt.submit({text: noticePrompt(claimed)});
      claimed = [];
      state.pushed = true;
      state.pushError = null;
    }
  } catch (error) {
    state.pushError = String(error);
    // Only a missing interface stops pushing; notices then go with the next
    // result. A host error (HooksError) is retried on the next tick.
    if (error?.name === 'TypeError' && /not a function|undefined/.test(error.message)) state.stopped = true;
  } finally {
    if (claimed.length && session) {
      const ids = claimed.map((notice) => notice.id).filter((id) => typeof id === 'string');
      try { await context($, {operation: 'requeue', session, ids}); }
      catch (error) { state.pushError = String(error); }
    }
    state.inflight = false;
  }
}

// tool.call carries the request fields on the event, tool.check under input.
function callRequest(event) {
  if (event.input && typeof event.input === 'object') return event.input;
  const request = {};
  for (const key of ['action', 'query', 'feature', 'schema', 'arguments']) {
    if (key in event) request[key] = event[key];
  }
  return request;
}

export function register(on) {
  const displayed = new Set();
  const state = {active: 0, pushing: false, inflight: false, stopped: false, pushed: false, pushError: null};

  on('session.start', async ($, event, next) => {
    await $.command.register({name: 'agents-context',
      description: 'Show current native Session and agents registration without a model turn', immediate: true});
    startPush($, state);
    return next(event);
  });

  on('command.run', {command: 'agents-context'}, async ($) => {
    const session = await $.session.id();
    const tools = await $.tool.list();
    await $.ui.log(`agents · current Session ${session}`);
    for (const name of ['agents', 'tasks']) {
      await $.ui.log(tools.some((tool) => tool.name === `mcp__agents__${name}`)
        ? `MCP ${name} registered` : `MCP ${name} missing`);
    }
    await $.ui.log(state.pushed ? 'notice push: delivered through prompt submission'
      : state.pushError ? `notice push unavailable (${state.pushError}); notices arrive with the next result`
      : 'notice push: waiting for a notice');
    return {};
  });

  for (const [tool, name] of [['mcp__agents__agents', 'agents'], ['mcp__agents__tasks', 'tasks']]) {
    // Both entries share one association; tasks has no agents exchange to render.
    on('tool.call', {tool}, async ($, event, next) => {
      // Calls may overlap. Each ends only its own association, named by the
      // exact facts tool.check prepared; the host still consumes each once.
      state.active += 1;
      const ending = {operation: 'end', tool: name, request: callRequest(event)};
      try {
        ending.session = await $.session.id();
        const result = await next(event);
        const request = name === 'agents' && event.action === 'execute'
          ? {action: event.feature, ...event.arguments} : {};
        // Native ui.log is a single-line surface: embedded newlines become
        // replacement glyphs. Keep the same readable body, one native row each.
        for (const frame of exchangeFrames(ending.session, request, result, displayed)) {
          for (const line of frame.split(/\r?\n/)) await $.ui.log(line);
        }
        return result;
      } catch (error) {
        return {deny: String(error)};
      } finally {
        try { if (ending.session) await context($, ending); }
        catch (error) { $.ui.log('agents context cleanup failed: ' + String(error)); }
        state.active -= 1;
        // Re-check at once: a notice queued during the calls need not wait a tick.
        if (state.pushing) pushNotices($, state);
      }
    }).catch(async ($, event, next) => next.called ? next(event)
      : {deny: 'The native agents context hook failed; no call was authorized.'});

    on('tool.check', {tool}, async ($, event, next) => {
      const result = await next(event);
      if (result.decision === 'deny') return result;
      // agentId is an official host field, never a model argument. Native
      // subagents must use an actual child binding, not inherit Main authority.
      if (event.agentId) return {decision: 'deny', reason: 'This MCP owner is bound to the Main conversation.'};
      try {
        await context($, {operation: 'prepare', tool: name, session: await $.session.id(),
          cwd: await $.session.cwd(), agent: event.agentId ?? null, request: event.input});
        return result; // Preserve allow/ask and the original reason/ceiling.
      } catch (error) {
        return {decision: 'deny', reason: String(error)};
      }
    }).catch(async () => ({decision: 'deny', reason: 'Current native agents association is unavailable.'}));
  }

  on('session.end', async ($, event, next) => {
    try { await context($, {operation: 'end'}); }
    catch (error) { $.ui.log('agents context cleanup failed: ' + String(error)); }
    return next(event);
  });
}
