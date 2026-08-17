---
status: accepted
---

# Write a handoff before compaction

Before a configured Agent session compacts, the Runtime integration gives that
same Agent an explicit `$handoff` turn and waits for it to write the handoff
document. Only a successfully written handoff permits compaction; this flow
does not create a child Agent, replacement Agent, or new session, and the
post-compaction continuation receives the resulting handoff context.

The policy applies to both manual and automatic compaction through the
Runtime's pre-compaction lifecycle. Main enables it by default, while Engineer
sessions opt in through Runtime configuration. Automatic handoff is configured
to begin at 75 percent of the active model's context window so the same Agent
has enough remaining context to write the document before compaction.

Each Runtime Adapter owns the native prompt, Hook or lifecycle mechanics. The
shared Runner does not parse Runtime transcripts or hard-code Codex compaction,
and a deterministic Hook script does not replace the semantic `$handoff` work
performed by the current Agent. Main and Engineer sessions use the same Hook
framework; only their Runtime configuration and Handoff Scope differ. ADR 0021
defines the shared storage and archive contract.
