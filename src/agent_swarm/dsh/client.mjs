/** Official browser module/Tool view extension; never submits model input. */
window.__ModuleLoader__.load({
  id: 'agents-dsh',
  factory(require) {
    const { createElement: h } = require('react');

    function parse(text) {
      try { return JSON.parse(text); } catch { return undefined; }
    }

    /** Read the same durable call/result facts as the existing native Tool row. */
    function communication(block, sessionId) {
      const request = parse(block.argsRaw || block.call?.argsRaw || '') || {};
      const args = request.arguments || {};
      const outbound = args.message || args.instruction;
      let document;
      for (const content of block.content || []) {
        if (content.type === 'text') {
          const candidate = parse(content.text);
          if (candidate && typeof candidate === 'object') document = candidate;
        }
      }
      const result = document?.result || {};
      return {
        sender: sessionId,
        recipient: document?.agent || args.agent || args.name || args.runtime || 'Agents',
        outbound: typeof outbound === 'string' ? outbound : undefined,
        state: result.state,
        error: document?.error?.message || result.last_result?.error?.message,
        operation: request.feature || request.action || 'agents',
      };
    }

    function AgentsRow({ block, sessionId, phase, inspect }) {
      const fact = communication(block, sessionId);
      const body = (title, text, key) => text ? h('section', {
        key, style: { border: '1px solid currentColor', borderRadius: 8, padding: '8px 12px', margin: '6px 0' },
      }, h('div', { style: { fontSize: 12, opacity: 0.7 } }, title),
      h('div', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, text)) : null;
      return h('div', { 'data-agent-communication': true },
        body(`${fact.sender} → ${fact.recipient}`, fact.outbound, 'outbound'),
        // Incoming body belongs to the native relay message, not a second Tool card.
        body('Agents', fact.error, 'error'),
        !fact.outbound && !fact.error
          ? h('div', null, `agents · ${fact.operation} · ${fact.state || phase}`) : null,
        inspect ? h('button', { type: 'button', onClick: inspect }, 'Details') : null);
    }

    return {
      inject: ['slots'],
      communication,
      AgentsRow,
      apply(ctx) {
        ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({
          name: 'tool.call.toolview', key: 'mcp__agents__agents',
        }, AgentsRow));
      },
    };
  },
});
