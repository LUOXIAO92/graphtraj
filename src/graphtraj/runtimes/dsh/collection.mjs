/** Forward DSH v4 semantic events through the existing Python native entry.
 * Pinned protocol: d743267388641bc76f17c45ce8b4c231aed1d32c.
 * No model stream fragments or conversation projections are persisted here.
 */

/** Read actual attachment bytes through the native capability, retaining failures. */
async function attachments(ctx, value, path = '$', result = {}) {
  if (value === null || typeof value !== 'object') return result;
  if (typeof value.attachmentId === 'string') {
    try {
      let bytes;
      if (value.mediaType) {
        bytes = (await ctx.attachments.readImage(value)).data;
      } else {
        const chunks = [];
        for await (const chunk of ctx.attachments.readFileStream(value)) chunks.push(chunk);
        bytes = Buffer.concat(chunks);
      }
      result[path] = { base64: Buffer.from(bytes).toString('base64') };
    } catch (error) {
      result[path] = { missing: `${error.name}: ${error.message}` };
    }
  } else {
    for (const [key, item] of Object.entries(value)) {
      await attachments(ctx, item, `${path}/${key}`, result);
    }
  }
  return result;
}

/** Attach one queue per live Session; flush acknowledges the durable Python cursor. */
export function installCollection(ctx, entry) {
  const sessions = new Map();

  async function drain(state) {
    if (state.running) return state.running;
    state.running = (async () => {
      while (state.pending.length || !state.initialized) {
        // Native Session order supplies a complete prefix. Re-observing lets
        // enabling backfill recover earlier history without retaining a third
        // body in this plugin. JSONL publication already processes that prefix.
        const observation = await ctx.sessionQuery.observeSession(state.agent.session.id, { projectionMode: 'none' });
        let batch;
        try { batch = [...observation.events]; }
        finally { observation[Symbol.dispose](); }
        const records = [];
        for (const event of batch) records.push({ event, attachments: await attachments(ctx, event) });
        // Collection must also settle aborted/failed attempts, so it is not
        // cancelled with a turn's AbortSignal. Native persistence owns replay.
        const result = await entry(state.agent, {
          event: 'session/collect', header: state.agent.session.header, records, history_boundary: state.boundary,
        });
        if (result.deferred) return;
        const expected = batch.at(-1)?.seq ?? -1;
        if (!Number.isInteger(result.position) || result.position < expected) {
          throw new Error('GraphTraj did not acknowledge the native Session prefix');
        }
        state.pending = state.pending.filter(event => event.seq > result.position);
        state.initialized = true;
      }
    })();
    try { await state.running; } finally { state.running = null; }
  }

  function schedule(state) {
    void drain(state).catch(error => ctx.logger.error(`Session collection failed: ${error.message}`));
  }

  ctx.on('session/event', (session, event) => {
    const state = sessions.get(session.id);
    if (!state) return; // Creation captures the complete prefix before activating this queue.
    state.pending.push(event);
    if (state.ready) schedule(state);
  });
  ctx.on('session/flush', async session => {
    const state = sessions.get(session.id);
    if (state) {
      await drain(state);
      if (state.pending.length || !state.initialized) {
        throw new Error('GraphTraj Session collection awaits its Runner binding');
      }
    }
  });
  ctx.on('session/disposed', session => {
    const state = sessions.get(session.id);
    if (state) void drain(state).then(() => sessions.delete(session.id))
      .catch(error => ctx.logger.error(`Session collection failed: ${error.message}`));
  });
  // Native plugin disposal is awaited, unlike the post-commit event feed.
  // Drain the final turn/end before the owned service finishes shutting down.
  ctx.effect(() => async () => {
    await Promise.all([...sessions.values()].map(state => drain(state)));
  });

  return async (agent, source = 'startup') => {
    // A live observation includes seed events, which never emit session/event.
    // Install the queue first: events appended while observing are deduplicated
    // against the captured cursor without dropping the new tail.
    const state = { agent, pending: [], running: null, initialized: false, ready: false, boundary: -1 };
    sessions.set(agent.session.id, state);
    const observation = await ctx.sessionQuery.observeSession(agent.session.id, { projectionMode: 'none' });
    try {
      state.boundary = source === 'resume' ? observation.cursor : -1;
      state.pending = [...observation.events,
        ...state.pending.filter(event => event.seq > observation.cursor)];
    } finally { observation[Symbol.dispose](); }
    state.ready = true;
    schedule(state);
  };
}
