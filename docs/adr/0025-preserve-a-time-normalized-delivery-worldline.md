---
status: accepted
---

# Preserve an append-only, time-normalized Delivery Run worldline

A Delivery Run must retain enough causal history to reconstruct what each
Agent did, what the user changed, how Main interpreted the available evidence,
and why task state or the accepted DAG changed. A phase-oriented Markdown
ledger and a mutable YAML document cannot represent parallel turns and causal
links reliably enough, so
`state/<run-id>/worldline.jsonl` is the single canonical,
append-only **Delivery Worldline**. `ledger.yml` is its deterministic readable
projection; `ledger.md` is retired. Current task-map and DAG ownership remains
with [ADR 0003](0003-delivery-state-agent-maintains-run-state.md).

One Delivery Run has one worldline. Each JSON line is one complete normalized
coarse event in Harness-observed chronological order, including Agent Turn
start and terminal events, relevant user input, Main decisions, Runner actions,
and task or DAG changes. Every entry has the Run's `run_id`, an ISO 8601
`captured_at` value from the Harness boundary, an explicit `kind`, and a
stable, monotonically increasing `worldline_seq` unique within the Run.
Runtime-native timestamps remain source evidence but cannot establish
cross-session order by themselves. Equal capture times retain deterministic
Harness capture order.

The ledger never uses a bare `id`. Each identifier or ordinal names its domain:

- `run_id` identifies the Delivery Run;
- `ticket_id` preserves the tracker-supplied ticket identity;
- `worldline_seq` orders one Run's canonical worldline;
- `review_round` groups the two review axes for one fixed candidate;
- `alias` addresses one logical Runtime session while it is live; and
- `turn` numbers resumed turns within `(run_id, ticket_id, alias)`.

A cross-Run worldline reference is therefore `(run_id, worldline_seq)`, not an
overloaded identifier that can be mistaken for a ticket number. Causal fields
name the same key explicitly, for example `caused_by_worldline_seqs`.

## Coarse worldline and complete Agent traces

The worldline is an index over evidence, not a replacement for it. Every
Engineer and Reviewer turn maps to one complete, immutable raw Agent event
stream containing that turn's captured actions and final output. The trace is
addressed by `(run_id, ticket_id, alias, turn)` and linked with a Run-relative
`trace_ref`; the worldline does not embed or summarize away the raw JSONL
stream.
When an Agent Runtime appends resumed turns to one live `events.jsonl`, the
Runner must still preserve each turn as a separately addressable durable trace
without rewriting the captured events.

A review round groups the parallel Standards and Spec Reviewer turns that
examine the same candidate and comparison point. `review_round` is not a
session ordinal: two aliases such as `@r1` and `@r2` may both belong to review
round 1. Their start and terminal events keep their actual Harness-observed
order and both traces are linked from the round. Neither review axis gates the
launch of the other.

User input and Main's decision are separate, causally linked worldline entries.
A Main-decision entry links the candidate, applicable Agent turns and raw
reports, any relevant user input, accepted and rejected findings, the `PASS` or
`FAIL` verdict, and the resulting task-state and DAG deltas. Rework is another
turn of the selected Engineer session when Main resumes it; it does not
overwrite the earlier turn or review round.

A representative canonical journal begins:

```jsonl
{"run_id":"20260823-example","worldline_seq":1,"captured_at":"2026-08-23T10:00:00+09:00","ticket_id":"53","kind":"agent-turn-start","role":"engineer","alias":"@e1","turn":1}
{"run_id":"20260823-example","worldline_seq":2,"captured_at":"2026-08-23T10:08:41+09:00","ticket_id":"53","kind":"agent-turn-terminal","role":"engineer","alias":"@e1","turn":1,"trace_ref":"tickets/2-53-example/traces/e1/turn-1/events.jsonl"}
```

The example is illustrative rather than a generalized schema. The required
invariants are append-only complete lines, domain-specific keys, chronological
ordering, causal links, and lossless per-Turn trace mapping. `ledger.yml`
groups those events by Turn, review round, user input, and Main decision using
their explicit fields and causal references; it never parses Agent prose.

## Ownership and lifecycle

One Run-local append boundary assigns `captured_at` and `worldline_seq` and
atomically appends one complete event. The existing Runner capture path records
only mechanical Agent Turn observations and raw-trace references through that
boundary; it never converts transport outcomes into verdicts. No resident
recorder, watcher, database, or event bus is introduced.

The Delivery State Agent is the sole semantic writer. When Main supplies a
confirmed user input, review decision, accepted or rejected finding, task-state
change, or DAG change, the State Agent appends that explicit semantic event and
regenerates `ledger.yml`. Current `task-map.yml` and `dag.md` synchronization
remains owned by ADR 0003. Retained batch-input lifecycle remains owned by
[ADR 0004](0004-preserve-delivery-evidence-outside-git-worktrees.md).

Successful cleanup still removes retired live aliases, Runtime mappings,
Worktrees, branches, and disposable transport diagnostics. It must not remove
the preserved per-turn Agent traces or canonical worldline. This decision
promotes the captured Agent event stream to durable delivery evidence; stderr
remains a disposable transport diagnostic unless a later decision explicitly
promotes it.

No independently hand-maintained `ledger.md` copy is kept. `ledger.yml` may
be regenerated at any time from `worldline.jsonl` and cannot become a second
authority. Existing historical Runs need not be rewritten merely to adopt this
decision.

This partially supersedes ADR 0003's `ledger.md` representation, ADR 0004's
classification of raw Runtime events as disposable, and ADR 0008's deletion of
those events with live alias state. Their state ownership, storage boundary,
session addressing, and cleanup decisions otherwise remain accepted.

## Considered options

- Keeping `ledger.md` with Markdown links was rejected because regex-based
  parsing becomes brittle once parallel turns, causal references, and DAG
  evolution must be reconstructed.
- Keeping mutable `ledger.yml` canonical was rejected because updates can
  overwrite causal history; deterministic YAML remains a readable projection
  of the append-only journal.
- Merging every Agent's fine-grained events into one rewritten JSONL stream was
  rejected because it would alter raw evidence and conflate global delivery
  order with Runtime-local action order.
- Adding a database, event bus, resident recorder, or generalized schema
  registry was rejected because one atomic Run-local append is sufficient.
- Reusing a generic `id` was rejected because ticket identity, worldline order,
  review rounds, sessions, and turns have different scopes and lifecycles.
