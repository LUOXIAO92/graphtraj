## Agent skills

### Issue tracker

Issues for this repository are tracked in GitHub Issues and managed with `gh`.
This repository-level setting does not configure the portable Main in the
Harness Project Root's `.codex/config.toml`; each target project binds its own
tracker. See `docs/agents/issue-tracker.md`.

### Triage labels

This repository's GitHub Issues use the five default canonical triage labels.
This mapping is not propagated to target projects operated by the Harness
Master. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses the single-context layout. See `docs/agents/domain.md`.

## Harness execution

- Until Runtime installation exposes the project-owned `$task-delivery` Skill,
  use its authoritative temporary source in the registered `dev` Integration
  Worktree at
  `src/you_are_a_product_architect/resources/skills/task-delivery/SKILL.md`.
  In this Harness checkout, that file is
  `<home>/workspace/you-are-a-product-architect-delivery/.agent-worktrees/integration/src/you_are_a_product_architect/resources/skills/task-delivery/SKILL.md`;
  resolve `<home>` from the current session and read the file in full before
  delivery. Do not mistake its absence from `main` or the injected Skill list
  for absence from the project.
- Invoke the project-owned `$task-delivery` Skill directly for an accepted
  Ticket DAG. Follow the Skill; do not restate or recreate its SOP here.
- Invoke Matt Pocock's global Skills directly when their workflow applies,
  including `$to-spec`, `$to-tickets`, `$implement`, `$tdd`, `$code-review`,
  and `$resolving-merge-conflicts`. Do not replace them with project copies or
  hand-written prompts.
- Spawn the installed canonical roles by name: `delivery-state`,
  `engineer-junior`, `engineer-senior`, `engineer-expert`, and
  `merge-resolver`. Their role definitions are authoritative; do not duplicate
  their developer instructions in dispatch prompts.
- Use the Harness Project Root's `.codex/config.toml` as the concurrency
  authority. Do not hard-code or reinterpret its capacity outside the Harness
  workflow.
- When monitoring Runner aliases, wait 90 seconds between unchanged status
  polls. A meaningful event may trigger an immediate status check.
- If a required Skill or role is unavailable, stop that operation and repair
  Runtime selection or installation. Do not improvise a substitute workflow.

### Proportional review and validation

- Use the narrowest check that can falsify the current change. A small,
  localized correction does not authorize a baseline-to-HEAD review or a full
  test-suite run merely because those workflows are available.
- After Main has accepted a full Standards/Spec review, review a bounded
  follow-up against that accepted candidate, not the original branch baseline.
  Carry the accepted full-review evidence forward; do not review the unchanged
  branch again.
- During rework, run the affected tests and the acceptance check that exposed
  the problem. Run the full suite once for the final candidate only when the
  change can affect the wider product. If `dev` fast-forwards to that exact
  already-validated commit, use targeted integration checks instead of running
  the same full suite a second time.
- Keep real-Runtime acceptance fixtures narrow. Stub unrelated Skills and
  workflows so a probe does not launch TDD, code review, or sub-agents. If an
  unrelated workflow makes a probe slow, narrow the fixture; do not repeatedly
  increase its timeout.
- Do not turn a judgement-call smell or a few duplicated test lines into a new
  helper, abstraction, framework, or ticket when the requested fix is already
  clear and local. Require a concrete correctness or maintenance benefit.
- Successful reviewed integration plus proportionate integration validation is
  delivery. Runner cleanup is post-delivery housekeeping: a cleanup failure
  must not reopen the ticket or trigger config migration, setup, or product
  changes unless the user explicitly requests that work.

### Review-failure authority

This target project delegates review-failure diagnosis and corrective
orchestration within the accepted Ticket and Spec to Main. A failure count does
not select the next action.

- Before retrying, replacing an Agent, choosing a higher tier, or returning to
  planning, inspect the retained implementation and review evidence and record
  the diagnosed cause and next-action rationale.
- Keep small implementation corrections with the same Engineer and tier. Use a
  fresh Agent at the same tier only for polluted session context, and choose a
  higher tier only for demonstrated difficulty or capability mismatch on a
  clear Ticket. Three failures at one tier require reassessment, never
  automatic escalation.
- Correct Main-caused tier selection, decomposition, dependency, acceptance,
  or dispatch errors within the accepted Spec instead of counting an Engineer
  failure. If Main introduced overengineering, remove the unsupported work and
  return the corrected minimal work to ticket planning rather than refining
  the polluted Ticket or candidate.
- Keep product and Spec changes user-owned. If the diagnosis would require one,
  stop and ask the user for an explicit decision.

<!-- you-are-a-product-architect:reviewer-guidance:start -->

## Reviewer guidance

Review against the smallest implementation that satisfies the accepted Ticket,
its acceptance criteria, and the repository's documented constraints.

- A blocking finding must cite the exact Ticket, Spec, ADR, or repository rule,
  identify a currently supported input or state, trace how it passes existing
  callers and upstream validation to the changed code, and show the concrete
  observable failure. If any part is missing, omit the finding; do not replace
  it with non-blocking speculation.
- Treat established upstream validation and interface invariants as
  authoritative. Do not require duplicate downstream validation, fallback,
  error mapping, or tests unless the downstream code is itself an explicitly
  documented trust, security, data-loss, or destructive-operation boundary.
- Review only behavior changed by the fixed candidate. Unrelated existing
  inconsistency and repository-wide normalization are out of scope.
  Consistency is blocking only when a cited rule explicitly requires it or the
  difference causes the concrete failure above.
- Do not use unsupported corruption, unsupported environments, future
  extension, bare theoretical races, defense in depth, code smells, or generic
  best practice as grounds for `FAIL` or rework.
- Prefer deletion and the fewest files, branches, validations, and tests. Once
  the minimum code satisfies current acceptance and applicable constraints,
  additional defensive machinery is scope creep.
- Main must reject a report item that fails this baseline as Reviewer error. It
  does not count as an Engineer review failure and cannot authorize rework.

<!-- you-are-a-product-architect:reviewer-guidance:end -->
