---
status: accepted
---

# Write a handoff before compaction

Before a configured Agent session compacts, its Runtime integration gives the
same Agent an explicit `$handoff` turn and waits for it to write the handoff
document. Only a successfully written handoff permits compaction; this flow
does not create a child Agent, replacement Agent, or new session, and the
post-compaction continuation receives the resulting handoff context.

For Codex, this sequence is controlled through `app-server`. The controller
observes `thread/tokenUsage/updated`, waits until the current thread is idle,
and starts the handoff turn on that same thread at 75 percent of the reported
`modelContextWindow`. After the handoff is durably installed, it calls
`thread/compact/start`; after the `contextCompaction` lifecycle completes, it
supplies the handoff as application context on the next continuation. Manual
compaction enters the same controller sequence. Main enables this by default,
while Engineer sessions opt in through their immutable Runtime Context.

Codex `PreCompact` cannot insert and await a semantic turn, and
`model_auto_compact_token_limit` can compact without first completing that
turn, so neither mechanism owns this policy. Each Runtime Adapter owns its
native lifecycle controller. The shared Runner does not parse Runtime
transcripts or hard-code Codex events, and deterministic storage code does not
replace the semantic `$handoff` work performed by the current Agent. Main and
opted-in Engineers share one controller and storage implementation; only their
Runtime configuration and Handoff Scope differ. ADR 0021 defines the shared
storage and archive contract.
