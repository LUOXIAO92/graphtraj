## Agent skills

### Issue tracker

Issues for this repository are tracked in GitHub Issues and managed with `gh`.
This repository-level setting does not configure the portable Master in
`codex/config.toml`; each target project binds its own tracker. See
`docs/agents/issue-tracker.md`.

### Triage labels

This repository's GitHub Issues use the five default canonical triage labels.
This mapping is not propagated to target projects operated by the Harness
Master. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses the single-context layout. See `docs/agents/domain.md`.

## Harness delivery workflow

These rules apply whenever an accepted ticket DAG is delivered through the
Harness. They define responsibilities and evidence, independent of whether the
transport is Agent Runner or native subagents.

### Control plane

- The Main/Master owns user communication, ready-frontier selection, Engineer
  tier selection, dispatch, review adjudication, retry or escalation decisions,
  integration order, and process exceptions.
- The Main/Master does not ordinarily implement tickets, prescribe or apply an
  Engineer's review fixes, resolve merge conflicts, or create the ticket's
  Reviewers on the Engineer's behalf. Assign implementation to an Engineer and
  conflicts to a fresh Merge Resolver.
- Treat the accepted ticket and its dependency edges as the planning authority.
  Delivery must not silently split or rewrite tickets, invent dependencies, or
  broaden acceptance criteria. An Engineer may decompose its own implementation
  internally without changing that contract.
- Runner and native delegation are transport adapters. In either case, bind the
  assignment to the exact Ticket Worktree and a narrow ticket scope. Record a
  native session as native; never fabricate a Runner alias, session, or metadata.

### Ticket execution and review

- One Engineer exclusively owns each Ticket Worktree. The Engineer follows the
  implementation workflow: test-first changes, focused tests, the repository's
  type check (or a documented compile substitute), the full relevant suite, and
  committed candidate changes.
- After freezing a candidate, that Engineer creates exactly two independent
  child reviews: one Standards review against repository rules and one Spec
  review against the accepted ticket. Reviewers inspect a fixed baseline and
  candidate and write their raw reports; the Engineer cannot declare its own
  review result.
- The Main/Master reads both raw reports and alone adjudicates PASS or FAIL. A
  PASS may advance to `awaiting-integration`; review comments are not silently
  waived or reinterpreted by the Engineer.
- Only a Main-adjudicated review FAIL increments the delivery failure counter.
  Test failures, type-check failures, transport failures, and integration
  failures do not. Before a retry, the Engineer reflects across all accumulated
  findings, identifies the shared root cause or invariant, and expands the test
  matrix before changing production code.
- For fewer than three review FAILs at one tier, resume the same Engineer in the
  same Worktree. On the third Junior FAIL, retry with a fresh Senior; on the
  third Senior FAIL, retry with a fresh Expert; on the third Expert FAIL, stop
  and escalate to the Main/Master and user.

### State and evidence

- A dedicated Delivery State Agent is the sole writer of the run ledger and
  DAG. It is separate from the six work-agent slots. It records facts only: it
  does not choose readiness or tier, dispatch work, change dependencies, or
  adjudicate reviews.
- After each meaningful event, the Delivery State Agent reads Git state,
  Engineer results, validation records, and raw review reports directly. The
  Main/Master sends only compact semantic decisions such as an adjudicated
  result or approved exception, never rewritten evidence in place of sources.
- Keep per-ticket evidence in persistent run storage outside disposable
  Worktrees. Expose only that ticket's evidence inside its Worktree through an
  ignored `.scratch/task-delivery` view. The Engineer writes `result.md`,
  `validation.md`, and the two raw review reports there. Preserve prior rounds;
  do not overwrite or have the Main/Master reconstruct them.

### Integration and concurrency

- The Main/Master serializes integration of exact reviewed candidates into
  `dev`. If a conflict occurs, a fresh Merge Resolver works from the reviewed
  candidate and current Integration state. Run post-merge validation before
  marking a ticket `integrated` and unlocking dependents.
- Preserve persistent evidence, then clean up disposable transport and
  Worktrees only after successful integration when cleanup is appropriate.
- Run at most four implementation Engineers and two Reviewers concurrently.
  The Delivery State Agent is separate from this six-agent work capacity. Fill
  only the accepted ready frontier and continue through subsequent frontiers
  until the DAG is integrated, externally blocked, or explicitly escalated.
