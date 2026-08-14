# Architecture decision records

The ADRs are split by functional decision boundary so changes in one part of
the Harness do not require editing a single system-wide record.

## Project boundary and layout

- [ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md) — each
  Harness Project isolates one Source Repository, its Worktrees, and persistent
  state beneath a dedicated project root.
- [ADR 0013](0013-own-runtime-resources-at-the-harness-root.md) — Main runs at
  the Harness Project Root, whose Runtime Store owns Harness roles, Skills, and
  Hooks independently of Source Repository history and Worktree lifecycles.

## Soft orchestration and delivery state

- [ADR 0001](0001-task-delivery-is-soft-agent-orchestration.md) — Task Delivery
  remains soft Agent orchestration controlled by Main.
- [ADR 0003](0003-delivery-state-agent-maintains-run-state.md) — the Delivery
  State Agent owns the ledger and Mermaid working view.
- [ADR 0004](0004-preserve-delivery-evidence-outside-git-worktrees.md) — durable
  delivery evidence lives outside Git worktrees.
- [ADR 0005](0005-review-failures-escalate-within-task-delivery.md) — review
  failures escalate within Task Delivery.

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

## Distribution and target-project setup

- [ADR 0002](0002-distribute-with-uv-as-a-python-tool.md) — the product is an
  auditable Python tool installed with `uv`.
- [ADR 0010](0010-configure-target-projects-locally.md) — setup writes
  Harness-local Runtime configuration and machine-local Runner state through
  one interactive, preflighted operation.
- [ADR 0011](0011-resolve-core-skills-by-name.md) — core Skill dependencies are
  checked and resolved by declared name.
- [ADR 0015](0015-select-repository-skills-explicitly.md) — Harness Skills live
  in the Harness Runtime Store, while Source Repository Skills are disabled by
  default and selected explicitly per task or allowlist policy.

## Historical audit sources

The pre-split files
[`docs/task-delivery-adr-before-functional-split.md`](../task-delivery-adr-before-functional-split.md)
and
[`docs/distribution-adr-before-functional-split.md`](../distribution-adr-before-functional-split.md)
are non-normative historical sources retained only for split-audit
traceability. They are superseded by the active ADRs indexed above.
