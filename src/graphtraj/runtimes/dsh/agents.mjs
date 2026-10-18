/** DSH's native tool and presentation hooks over the common agents handler. */
export function agentsTool(invoke) {
  return {
    name: 'agents',
    description: 'Create, message, inspect, wait for, stop or resume child Agents.',
    parameters: {
      action: { type: 'string', required: true, enum: [
        'create', 'send', 'status', 'wait', 'interrupt', 'resume', 'requests', 'reply', 'retire',
      ] },
      runtime: { type: 'string' }, agent: { type: 'string' }, name: { type: 'string' },
      instruction: { type: 'string' }, message: { type: 'string' },
      execution: { type: 'string' }, timeout_seconds: { type: 'number' },
      request: { type: 'json' }, response: { type: 'json' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    presentCall(args) {
      return {
        card: 'generic', title: `agents · current Agent → ${args.agent || args.name || args.runtime || 'children'}`,
        content: [{ type: 'text', text: args.message || args.instruction || args.action }],
      };
    },
    presentResult(args, result) {
      // Presentation is a pure native UI projection. Never enqueue this copy.
      const bodies = [];
      for (const block of result.content) {
        if (block.type !== 'text') continue;
        try {
          const value = JSON.parse(block.text);
          const document = value.result?.action ? value.result : value;
          const outcome = document.result || {};
          const last = outcome.last_result?.last_message;
          bodies.push(last || document.error?.message || outcome.error?.message ||
            (typeof value.error === 'string' ? value.error : null) ||
            (typeof document.message === 'string' ? document.message : null) ||
            `${args.action}: ${outcome.state || outcome.delivery || 'received'}`);
        } catch { bodies.push(block.text); }
      }
      return {
        card: 'generic', title: `agents · ${args.agent || args.name || args.runtime || 'children'} → current Agent`,
        content: [{ type: 'text', text: bodies.join('\n') }],
      };
    },
    execute(args, execution) {
      return invoke({ action: 'execute', feature: 'agents', arguments: args }, execution);
    },
  };
}
