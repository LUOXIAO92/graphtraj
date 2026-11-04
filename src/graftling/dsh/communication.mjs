/** Use DSH's native relay message/container for asynchronous Agent replies. */
export function installCommunication(ctx, { TypertRemoteService, Remote, createUserMessage }) {
  const initializers = [];
  class AgentMessages extends TypertRemoteService {
    constructor(context) {
      super(context, 'agentMessages');
      for (const initialize of initializers) initialize.call(this);
      this.inflight = new Map();
    }

    /** Admit a stable communication fact once to its actual native recipient. */
    async receive(request) {
      for (const key of ['id', 'sessionId', 'senderSessionId', 'sender', 'recipient', 'body']) {
        if (typeof request?.[key] !== 'string' || !request[key]) throw new Error(`Invalid Agent message ${key}`);
      }
      const key = `${request.sessionId}/${request.id}`;
      if (this.inflight.has(key)) return this.inflight.get(key);
      const delivery = this.deliver(request);
      this.inflight.set(key, delivery);
      try { return await delivery; } finally { this.inflight.delete(key); }
    }

    /** Inspect only the addressed Session and use its existing native inbox. */
    async deliver(request) {
      const agent = this.ctx.agents.get(request.sessionId);
      if (!agent) throw new Error('The native recipient Session is not active in this host');
      const observation = await this.ctx.sessionQuery.observeSession(request.sessionId, { projectionMode: 'none' });
      let delivered;
      try {
        delivered = observation.events.some(event => event.type === 'user/message' &&
          event.data.source.kind === 'agent-message' && event.data.source.communicationId === request.id);
      } finally { observation[Symbol.dispose](); }
      if (delivered || [...agent.inbox.nextTurn, ...agent.inbox.nextStep].some(message =>
        message.source.kind === 'agent-message' && message.source.communicationId === request.id)) {
        return { accepted: true, duplicate: true };
      }
      const message = createUserMessage({
        content: [{ type: 'text', text: request.body }],
        // Native UI RelayBody renders senderSessionId separately from content.
        // The same actual message enters the model once; no rendered copy does.
        source: { kind: 'agent-message', form: 'relay', senderSessionId: request.senderSessionId,
          senderAgentId: request.sender, recipientAgentId: request.recipient, communicationId: request.id },
      });
      agent.send(message, 'next-step', true);
      return { accepted: true, duplicate: false };
    }
  }
  // Apply the public Stage-3 decorator contract to ordinary distributable JS.
  Remote(AgentMessages.prototype.receive, {
    kind: 'method', name: 'receive', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize),
  });
  return ctx.plugin(AgentMessages);
}
