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

### Expert-failure exception

This target project selects `$task-delivery`'s delegated Main authority path,
not human-in-the-loop adjudication, after three Main-adjudicated Expert review
failures on one ticket.

- Stop autonomous delivery of the failed ticket. Do not dispatch another
  Engineer against it or keep revising the same accepted ticket.
- Treat the repeated highest-tier failures as a defect in Main's ticket
  definition or decomposition, not in the accepted Spec or user requirements.
  Main must inspect the retained implementation and review evidence, explain
  which ticket boundaries, dependencies, acceptance mapping, or complexity
  assumptions failed, and return the work to ticket planning.
- Keep the accepted Spec and user requirements unchanged. Main must not invoke
  `$to-spec`, revise the Spec, reinterpret requirements, or otherwise change
  product scope while handling this exception. Use `$to-tickets` against the
  same accepted Spec to replace and re-split the failed ticket into a newly
  accepted Ticket DAG before delivery restarts. Preserve the failed ticket and
  its evidence as history; do not silently rewrite or retry it.
- If the evidence appears to require a product or Spec change, stop and ask the
  user for an explicit decision. Delegated Main authority does not authorize
  changing requirements.
