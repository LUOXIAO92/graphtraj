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

## Required Skill pipeline

Use the repository's existing Skills as the workflow interfaces. Do not
reconstruct their SOPs from memory or replace them with ad hoc prompts.

- Planning uses `$to-spec` to synthesize and publish the agreed specification,
  then `$to-tickets` to propose vertical tracer-bullet tickets with explicit
  blockers. Obtain the user approvals required by those Skills before
  publishing. `$grilling`, `$domain-modeling`, and `$codebase-design` may feed
  planning when their documented trigger applies.
- Delivery of an accepted Ticket DAG uses `$task-delivery`. Planning Skills stay
  outside Delivery: `$task-delivery` must not silently rewrite or re-split an
  accepted ticket. If an escalated ticket is explicitly returned to planning,
  preserve the original ticket and evidence while `$to-spec`/`$to-tickets`
  produce a separately approved replacement DAG.
- Every dispatched Engineer runs `$implement` in its exact Ticket Worktree.
  `$implement` owns the implementation loop, uses `$tdd` at agreed public
  seams, runs focused/type/full validation, commits the candidate, and invokes
  `$code-review` when the candidate is frozen.
- `$code-review` always launches its Standards and Spec axes as two independent
  parallel Reviewers against one fixed baseline and candidate. Do not manually
  recreate either Reviewer prompt, serialize the axes, merge their reports, or
  let the Engineer self-adjudicate.
- Textual or semantic Integration conflicts go to a fresh canonical
  `merge-resolver` role from `codex/agents/merge-resolver.toml` (installed into
  the Harness Runtime Store). It remains inside the Integration Worktree and
  uses `$resolving-merge-conflicts` for an in-progress Git conflict; a clean Git
  merge followed by failing integration validation receives only the role's
  documented minimal semantic reconciliation. Main does not resolve conflicts
  inline, invent a substitute Resolver prompt, or let the Resolver change merge
  order, ticket scope, or final integration acceptance.
- Treat the installed copies in the Harness Runtime Store and the canonical
  resources committed on `dev` as authoritative. If a required Skill is not
  exposed in the active Runtime, diagnose its selection or Harness-local
  installation first; never install it globally on the user's behalf. For an
  explicitly authorized native-transport fallback, read and follow the exact
  canonical `SKILL.md` from `dev/.codex/skills/<name>/` (or its packaged
  `dev` resource) and record that transport fact. This is the only permitted
  fallback: do not paraphrase, copy-edit, or substitute a hand-written
  approximation of the Skill.

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
  child reviews in parallel: one Standards review against repository rules and
  one Spec review against the accepted ticket. Reviewers inspect a fixed
  baseline and candidate and write their raw reports; the Engineer cannot
  declare its own review result. A transport or thread-capacity error must be
  reported and corrected; it must not silently degrade the two reviews to
  serial execution.
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
- Read the spawned-thread limit from
  `codex/config.toml`'s `agents.max_concurrent_threads_per_session`. Each
  in-flight ticket reserves one Engineer plus its own two parallel Reviewers,
  so `max_concurrent_tickets = floor(max_concurrent_threads_per_session / 3)`.
  This repository configures 18 spawned threads, therefore its capacity is six
  concurrent ticket groups: six Engineers and up to twelve ticket-scoped
  Reviewers. Reviewers are fresh children; they are never shared or inherited
  between tickets. Do not start a seventh Engineer merely because earlier
  tickets have not reached review yet: preserve every ticket's two-thread
  review fan-out capacity. The primary Main/Master is not counted by Codex's
  spawned-thread limit; the event-driven Delivery State Agent is separate from
  ticket-group capacity.
- Fill the accepted ready frontier up to that calculated ticket capacity and
  continue through subsequent frontiers until the DAG is integrated,
  externally blocked, or explicitly escalated. Only Integration into `dev`,
  not ticket implementation or the two-axis review, is serialized.
