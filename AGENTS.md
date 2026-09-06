# Repository Guidance

Keep this file limited to stable facts and constraints that apply to ordinary
work in this Source Repository. Harness orchestration, Ticket-and-Team delivery
policy, review findings, and task-specific instructions belong in Main-owned
Harness Project Documents.

## Project structure

- `src/you_are_a_product_architect/` contains the Python package and packaged
  Runtime, role, Hook, and Skill resources.
- `tests/` contains behavior-focused pytest coverage.
- `README.md` is the product-facing installation and operation guide.
- `pyproject.toml` defines the GraphTraj distribution and the `graphtraj` /
  `agent-runner` command surfaces.
- New delivery uses `.graphtraj` configuration, Ticket/Team state, retained
  Batches, Session Traces, and the Project Worldline. Historical Run state is
  never migrated, read as fallback, or modified by supported commands.
- `CONTEXT.md` and `docs/` inside linked Worktrees are read-only Harness
  Project Document views, not Source Repository content.

## Standard checks

- Run focused tests with `pytest -p no:cacheprovider -q <paths>`.
- Run the complete suite with `pytest -p no:cacheprovider -q` only when the
  change can affect the wider product.
- Use `python -m compileall -q src tests` for a syntax pass and
  `git diff --check` for patch hygiene.

## Working constraints

- Prefer the smallest direct implementation that satisfies the accepted
  requirement. Do not add speculative abstractions, compatibility layers,
  configuration switches, fallback paths, or defense-in-depth work.
- Test observable behavior through public Setup, Runner, Runtime, or Hook
  seams. Do not freeze prose tokens, source text, private helper structure,
  absent code, or unsupported corruption scenarios.
- Preserve existing user changes and keep unrelated cleanup outside the active
  ticket.
- Do not modify, replace, move, or delete the Worktree `CONTEXT.md` or `docs/`
  views or their Harness-root targets.
- Repository issues are tracked in GitHub Issues and managed with `gh`.

## Plain language and problem checks

These rules apply to every Agent doing implementation, review, investigation,
documentation, or other work in this Source Repository.

- Use established project terms and ordinary language. Do not invent jargon,
  synonyms, ownership labels, lifecycle concepts, layers, or named mechanisms
  merely to discuss or implement something. This applies to prompts, code,
  schemas, filenames, documentation, and review findings.
- Introduce a new term only when existing language cannot express a real
  distinction. Describe the concrete behavior and the need for the distinction
  before naming it.
- Before reporting a problem, creating rework, challenging a decision, or
  asking a question, check the assigned task, Session or handoff, repository
  guidance, accepted decisions, existing implementation, tests, and available
  evidence for an answer. Use an existing answer instead of asking someone to
  repeat it.
- A suspicion is not a problem. Identify a concrete conflicting requirement,
  missing fact, or observable failure before raising it or changing work for
  it. If none exists, do not raise it.
- Resolve ordinary implementation details within the assigned scope using the
  smallest reasonable choice. Do not repeatedly ask an upstream Agent or the
  user to decide them.
- Never reopen or relabel an accepted decision as unresolved. If new evidence
  genuinely conflicts with it, show the evidence and exact conflict before
  requesting another decision or changing the implementation.
