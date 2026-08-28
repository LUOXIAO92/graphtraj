---
status: accepted
---

# Preserve a time-normalized Delivery Run worldline

A Delivery Run must retain enough causal history to reconstruct what each
Agent did, what the user changed, how Main interpreted the available evidence,
and why task state or the accepted DAG changed. A phase-oriented Markdown
ledger cannot represent parallel turns and causal links reliably enough, so
`state/task-delivery/<run-id>/ledger.yml` is the single canonical, readable,
structured **Delivery Worldline**. It replaces `ledger.md` as the authoritative
ledger. `task-map.yml` remains the current semantic-state projection and
`dag.md` remains the current accepted-topology projection.

One Delivery Run has one worldline. Its entries are coarse-grained lifecycle
and semantic events in Harness-observed chronological order, including Agent
turn start and terminal events, relevant user input, Main decisions, Runner
actions, and task or DAG changes. Every entry has an ISO 8601 `captured_at`
value from the Harness boundary and a stable, monotonically increasing
`worldline_seq` unique within the Run. Runtime-native timestamps remain source
evidence but cannot establish cross-session order by themselves. Equal capture
times retain deterministic Harness capture order.

The ledger never uses a bare `id`. Each identifier or ordinal names its domain:

- `run_id` identifies the Delivery Run;
- `ticket_id` preserves the tracker-supplied ticket identity;
- `worldline_seq` orders one Run's canonical worldline;
- `review_round` groups the two review axes for one fixed candidate;
- `alias` addresses one logical Runtime session while it is live; and
- `turn` numbers resumed turns within `(run_id, alias)`.

A cross-Run worldline reference is therefore `(run_id, worldline_seq)`, not an
overloaded identifier that can be mistaken for a ticket number. Causal fields
name the same key explicitly, for example `caused_by_worldline_seqs`.

## Coarse worldline and complete Agent traces

The worldline is an index over evidence, not a replacement for it. Every
Engineer and Reviewer turn maps to one complete, immutable raw Agent event
stream containing that turn's captured actions and final output. The trace is
addressed by `(run_id, alias, turn)` and linked with a Run-relative
`trace_ref`; the ledger does not embed or summarize away the JSONL stream.
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

A representative readable shape is:

```yaml
run_id: 20260823-example
worldline:
  - worldline_seq: 1
    captured_at: 2026-08-23T10:00:00+09:00
    ticket_id: "53"
    kind: agent-turn-start
    role: engineer
    alias: "@e1"
    turn: 1

  - worldline_seq: 2
    captured_at: 2026-08-23T10:08:41+09:00
    ticket_id: "53"
    kind: agent-turn-terminal
    role: engineer
    alias: "@e1"
    turn: 1
    trace_ref: traces/e1/turn-1/events.jsonl

  - worldline_seq: 3
    captured_at: 2026-08-23T10:09:02+09:00
    ticket_id: "53"
    kind: agent-turn-start
    role: standards-reviewer
    review_round: 1
    alias: "@r1"
    turn: 1

  - worldline_seq: 4
    captured_at: 2026-08-23T10:09:03+09:00
    ticket_id: "53"
    kind: agent-turn-start
    role: spec-reviewer
    review_round: 1
    alias: "@r2"
    turn: 1

  - worldline_seq: 5
    captured_at: 2026-08-23T10:12:17+09:00
    ticket_id: "53"
    kind: agent-turn-terminal
    role: spec-reviewer
    review_round: 1
    alias: "@r2"
    turn: 1
    trace_ref: traces/r2/turn-1/events.jsonl

  - worldline_seq: 6
    captured_at: 2026-08-23T10:14:31+09:00
    ticket_id: "53"
    kind: agent-turn-terminal
    role: standards-reviewer
    review_round: 1
    alias: "@r1"
    turn: 1
    trace_ref: traces/r1/turn-1/events.jsonl

  - worldline_seq: 7
    captured_at: 2026-08-23T10:15:04+09:00
    ticket_id: "53"
    kind: user-input

  - worldline_seq: 8
    captured_at: 2026-08-23T10:16:20+09:00
    ticket_id: "53"
    kind: main-decision
    caused_by_worldline_seqs: [5, 6, 7]
    verdict: fail
```

The example is illustrative rather than a complete persistence schema. The
required invariants are the domain-specific keys, chronological ordering,
causal links, and lossless per-turn trace mapping.

## Ownership and lifecycle

The Runner captures mechanical Runtime and turn facts and preserves each raw
Agent trace in the Harness State Directory before live session or Worktree
cleanup. The Delivery State Agent remains the sole writer of `ledger.yml`,
`task-map.yml`, and `dag.md`; Main supplies user-facing meaning, review
adjudication, and DAG decisions rather than asking the Runner to infer them.
The State Agent updates these projections after every meaningful confirmed
change.

Successful cleanup still removes retired live aliases, Runtime mappings,
Worktrees, branches, and disposable transport diagnostics. It must not remove
the preserved per-turn Agent traces or canonical worldline. This decision
promotes the captured Agent event stream to durable delivery evidence; stderr
remains a disposable transport diagnostic unless a later decision explicitly
promotes it.

No independently hand-maintained `ledger.md` copy is kept. A Markdown view may
be generated from `ledger.yml` later if it proves useful, but it is a derived
view and cannot become a second authority. Existing historical Runs need not
be rewritten merely to adopt this decision.

This partially supersedes ADR 0003's `ledger.md` representation, ADR 0004's
classification of raw Runtime events as disposable, and ADR 0008's deletion of
those events with live alias state. Their state ownership, storage boundary,
session addressing, and cleanup decisions otherwise remain accepted.

## Considered options

- Keeping `ledger.md` with Markdown links was rejected because regex-based
  parsing becomes brittle once parallel turns, causal references, and DAG
  evolution must be reconstructed.
- Maintaining both YAML and Markdown ledgers by hand was rejected because they
  can disagree; one canonical YAML document remains readable without creating
  duplicate authority.
- Merging every Agent's fine-grained events into one rewritten JSONL stream was
  rejected because it would alter raw evidence and conflate global delivery
  order with Runtime-local action order.
- Reusing a generic `id` was rejected because ticket identity, worldline order,
  review rounds, sessions, and turns have different scopes and lifecycles.
