# Architecture decision records

The ADRs are split by functional decision boundary so changes in one part of
the Harness do not require editing a single system-wide record.

## Project boundary and layout

- [ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md) — each
  Harness Project isolates one Source Repository, its Worktrees, and persistent
  state beneath a dedicated project root.

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

## Distribution and target-project setup

- [ADR 0002](0002-distribute-with-uv-as-a-python-tool.md) — the product is an
  auditable Python tool installed with `uv`.
- [ADR 0010](0010-configure-target-projects-locally.md) — setup writes
  project-local Runtime configuration and machine-local Runner state.
- [ADR 0011](0011-resolve-core-skills-by-name.md) — core Skill dependencies are
  checked and resolved by declared name.
