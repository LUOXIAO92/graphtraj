---
status: accepted
---

# A Delivery State Agent maintains Delivery Run state

Main is the semantic authority for a Delivery Run, but it does not spend its
context and output budget rewriting the ledger or Mermaid graph. Each active
Delivery Run has one Delivery State Agent acting on Main's behalf as the sole
writer of that Run's ledger and Mermaid graph. Concurrent Runs may use
different State Agents because their artifacts are run-scoped; no State Agent
owns another Run's files.

The Delivery State Agent is a custom Agent role launched and coordinated by
Main through the Runtime's native agent tools. It shares Main's Integration
Worktree context and does not cross the Agent Runner seam. The Merge Resolver
is likewise a Main-coordinated native role rather than a Runner-managed
Engineer.

At initialization, the Delivery State Agent reads the accepted tickets and
their explicit dependencies, then creates the working task map, ledger, and
Mermaid DAG. It also creates a short stable `run_id` in the ASCII form
`YYYYMMDD-short-name`, adding a numeric suffix such as `-2` on collision. The
Agent chooses the semantic short name and resolves collisions; the Runner only
validates that the ID is path-safe, within its allowed length, and consistent
with any existing mapping. V1 bounds the complete identifier at 64 ASCII
characters as a filesystem-nesting limit; this does not transfer naming or
collision authority to the Runner.

Each task is keyed by its tracker-supplied `ticket_id` and receives a short,
stable `ticket_name` for the Delivery Run. An accepted ticket may supply that
name; otherwise the Delivery State Agent assigns it once. Main only intervenes
when a name collides or is materially misleading.

When Main dispatches a ticket, the Delivery State Agent registers its
worktree, branch, tier, and Engineer session. After an Engineer turn or another
meaningful event, Main asks the same Agent to synchronize the task. The Agent
reads the registered worktree, Git state, result, review reports, and
validation evidence itself; updates the ledger and Mermaid graph; and returns
a short summary, ready-ticket suggestions, and any inconsistency or semantic
question that requires Main.

Main must still trigger synchronization. V1 has no autonomous watcher,
hook-triggered drawing Agent, or event-loop controller. If the original state
session is unavailable, a fresh Delivery State Agent can recover by reading
the persistent artifacts and replace it as that Run's sole writer.

The ledger uses this shared soft status vocabulary:

- `pending` — explicit dependencies have not all been integrated.
- `ready` — the ticket is a candidate for Main to dispatch.
- `implementing` — an Engineer is implementing the ticket.
- `reviewing` — the Standards and Spec Reviewers are examining candidate work.
- `reworking` — Main adjudicated review as `FAIL` and rework is in progress.
- `awaiting-integration` — Main adjudicated review as `PASS` and the reviewed
  commit is queued for integration.
- `integrating` — the commit is being merged and validated in `dev`.
- `resolving-integration` — the Merge Resolver is reconciling an integration
  conflict.
- `integrated` — the commit is present in `dev` and integration validation
  passed.
- `blocked` — an external condition prevents autonomous progress.
- `escalated` — autonomous review escalation is exhausted and Main or the user
  must decide what happens next.

`completed` is not a ticket status because it conflates implementation,
review, and integration. `failed` is also excluded because review failure,
transport failure, test failure, and integration failure have different
consequences. The Agent records those as evidence-bearing events and applies
the semantic status chosen by Main. Plain-language notes about current intent
or user direction are not control states and do not drive orchestration.

The Delivery State Agent does not adjudicate reviews, choose a tier, dispatch
work, change tickets or dependencies, accept integration, or replace Main's
authority. It records a review verdict only after Main supplies the compact
semantic decision and blocking rationale. Persistent storage and evidence
ownership are defined separately in
[ADR 0004](0004-preserve-delivery-evidence-outside-git-worktrees.md).

## Considered options

- Requiring Main to construct the normalized graph, ledger, or Mermaid was
  rejected because it creates high-volume mechanical work in Main's context.
- Requiring Main to relay Engineer and Reviewer output was rejected because the
  Delivery State Agent can read registered artifacts directly.
- Automatically invoking the Agent after every transition was rejected because
  that would require the hook or controller deliberately excluded from V1.
