---
status: accepted
---

# Store handoffs in scope-owned Harness State

Each Handoff Scope exposes one current file named `HANDOFF.md` and an
`archive/` directory in Harness State. Main uses
`<harness-root>/state/handoffs/HANDOFF.md`, visible from the Integration
Worktree as `.scratch/handoffs/HANDOFF.md`. An Engineer uses its Ticket's
existing evidence scope at
`<harness-root>/state/task-delivery/<run-id>/tickets/<ticket-stem>/handoffs/HANDOFF.md`.
The `.scratch` path is an access path, not the canonical store. Main's handoff
does not belong to a Delivery Run because a Main session can precede or span
runs, and no handoff enters Source Repository history.

Before writing a new current handoff, the common Hook framework moves any
existing `HANDOFF.md` to
`archive/<timestamp>-<session-id>-<compact-count>.md`, then atomically replaces
the fixed-name current file. Main and Engineer use the same archive operation,
while their separate Handoff Scopes keep their state isolated. Each scope root
therefore retains only its latest `HANDOFF.md`; archives have no automatic
cleanup policy.

Every current handoff begins with top-level YAML metadata shaped as follows:

```yaml
---
current_session: <session-id>
historical_sessions:
  - <prior-session-id>
automatic_compaction_count: 3
compactions:
  - trigger: auto
    compacted_at: 2026-08-17T22:30:00+09:00
---
```

`compactions` records each current-session compaction and whether its trigger
was `auto` or `manual`; `automatic_compaction_count` counts only the automatic
entries. Every timestamp, including `compacted_at` and the archive filename,
uses the Harness host's local time in ISO 8601 form with its numeric UTC offset;
it is never normalized to Pacific Time or another fixed timezone. Archived
handoffs retain the statistics of earlier sessions, while `historical_sessions`
preserves the session lineage carried into the current file. This
Harness-managed location supersedes the generic `$handoff` Skill's
operating-system temporary-file default only for pre-compaction handoffs.
