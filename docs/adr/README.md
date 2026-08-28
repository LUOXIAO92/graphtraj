# Architecture decision records

The ADRs are split by functional decision boundary so changes in one part of
the Harness do not require editing a single system-wide record.

## Project boundary and layout

- [ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md) — each
  Harness Project isolates one Source Repository, its Worktrees, and persistent
  state beneath a dedicated project root.
- [ADR 0013](0013-own-runtime-resources-at-the-harness-root.md) — Main runs at
  the Harness Project Root, whose Runtime Store owns Harness roles and Hooks
  independently of Source Repository history and Worktree lifecycles.

## Soft orchestration and delivery state

- [ADR 0001](0001-task-delivery-is-soft-agent-orchestration.md) — Task Delivery
  remains soft Agent orchestration controlled by Main.
- [ADR 0003](0003-delivery-state-agent-maintains-run-state.md) — the Delivery
  State Agent owns the ledger and Mermaid working view.
- [ADR 0004](0004-preserve-delivery-evidence-outside-git-worktrees.md) — durable
  delivery evidence lives outside Git worktrees.
- [ADR 0025](0025-preserve-a-time-normalized-delivery-worldline.md) — each
  Delivery Run retains one append-only worldline, a readable YAML projection,
  and links to complete per-Turn Agent traces.
- [ADR 0019](0019-main-dispatches-reviewers.md) — Main conditionally dispatches
  Standards and Spec Reviewers, with optional Review Diversity.
- [ADR 0022](0022-diagnose-review-failures-before-choosing-an-action.md) — Main
  diagnoses each review failure before choosing retry, escalation, or
  replanning.
- [ADR 0024](0024-keep-main-read-only-until-explicitly-authorized.md) — Main
  remains in Soft Plan until the user explicitly authorizes execution.

## Agent Runner and isolation

- [ADR 0006](0006-runner-dispatches-main-selected-ticket-batches.md) — the
  Runner launches only the exact task objects selected by Main.
- [ADR 0007](0007-hide-runtime-cli-details-behind-adapters.md) — Runtime CLI
  and role configuration stay behind Adapter boundaries.
- [ADR 0008](0008-address-engineer-sessions-by-alias.md) — Main controls
  Engineer sessions through semantic aliases.
- [ADR 0009](0009-integrate-ticket-worktrees-through-dev.md) — Ticket
  Worktrees integrate through the project-level `dev` worktree.
- [ADR 0014](0014-inject-engineer-runtime-through-the-adapter.md) — the Adapter
  constructs an Engineer's effective role and isolation context without
  loading the Source Repository's project-scoped Codex configuration.
- [ADR 0017](0017-prepare-engineer-runtime-context-in-two-stages.md) — Engineer
  Runtime Context is prepared through one side-effect-free, two-stage boundary.
- [ADR 0018](0018-main-selects-runtimes-outside-task-objects.md) — Main selects
  a Runtime outside logical task objects while Runtime-specific mechanics stay
  private to the selected Adapter.
- [ADR 0023](0023-keep-project-documents-read-only-for-subagents.md) — every
  subagent receives read-only access to Source Repository Project Documents.

## Distribution and target-project setup

- [ADR 0002](0002-distribute-with-uv-as-a-python-tool.md) — the product is an
  auditable Python tool installed with `uv`.
- [ADR 0010](0010-configure-target-projects-locally.md) — setup writes
  Harness-local Runtime configuration and machine-local Runner state through
  one interactive, preflighted operation.
- [ADR 0011](0011-resolve-core-skills-by-name.md) — core Skill dependencies are
  checked and resolved by declared name.
- [ADR 0015](0015-select-repository-skills-explicitly.md) — Harness Skills are
  owned by the Harness Project, while Source Repository Skills are disabled by
  default and selected explicitly per task or allowlist policy.
- [ADR 0016](0016-install-harness-skills-under-agents.md) — V2 setup installs
  only missing Harness Skills under the Harness Project Root's `.agents/skills`
  directory instead of `.codex/skills`.

## Historical audit sources

[ADR 0005](0005-review-failures-escalate-within-task-delivery.md) is retained
as the superseded mechanical review-escalation decision.

The pre-split files
[`docs/task-delivery-adr-before-functional-split.md`](../task-delivery-adr-before-functional-split.md)
and
[`docs/distribution-adr-before-functional-split.md`](../distribution-adr-before-functional-split.md)
are non-normative historical sources retained only for split-audit
traceability. They are superseded by the active ADRs indexed above.
