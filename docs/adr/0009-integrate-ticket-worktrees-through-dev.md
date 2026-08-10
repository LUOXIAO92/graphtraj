---
status: accepted
---

# Integrate isolated Ticket Worktrees through dev

Engineers implement in isolated Ticket Worktrees while one long-lived
project-level **Integration Worktree** owns serialized development integration.
The Integration Worktree lives at
`<harness-project-root>/.agent-worktrees/integration`, is fixed to `dev`, and
is shared by concurrent Delivery Runs. The Source Repository checkout at
`<harness-project-root>/repo` remains the primary `main` checkout reserved for
release work.

Physical Worktrees live outside the Source Repository but inside its dedicated
Harness Project Root, under the project-private `.agent-worktrees/` directory
defined by
[ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md). Setup ensures
this directory is writable under the host and Runtime sandbox configuration.
It is neither committed configuration nor batch input, must not resolve inside
the Source Repository, and is canonicalized and checked against
`git worktree list`. Setup and the Runner never treat the parent workspace as a
shared project or authorization boundary.

Ticket Worktrees are run-scoped:

```text
<harness-project-root>/.agent-worktrees/runs/<run-id>/<ticket-id>-<ticket-name>
```

The Runner derives branch names and paths from project, run, and stable ticket
identity; `ticket_name` is only a readable suffix. A worktree is a complete
isolated checkout and the Engineer's editable repository root, not a
Main-designed file or directory allowlist. Retries and tier escalation reuse
the same branch and worktree. A later batch for the same live ticket recovers
and validates that worktree but creates a fresh Runtime session; only `send`
resumes an existing alias.

Ticket branches start from the current validated `dev` state. Independent
tickets may share a base snapshot. A dependent ticket starts only after its
prerequisites are merged and validated in `dev`. Review `PASS` makes work
eligible for integration but does not update `dev`; Main performs merge,
conflict reconciliation, and integration validation in the Integration
Worktree. Promotion from `dev` to `main` is outside Task Delivery.

Normal planning and delivery Main sessions run from the registered Integration
Worktree. `task-delivery` verifies that workspace before dispatch. Starting an
Engineer with its resolved Ticket Worktree lets the existing guard derive the
correct immutable root; its native Reviewer children inherit that workspace.

After a reviewed commit is successfully merged and validated in `dev`, Main
may request:

```text
agent-runner cleanup --run-id <run-id> --ticket-id <ticket-id>
```

Cleanup is an idempotent ticket-lifecycle operation addressed by stable run
and ticket identity, not a session alias. Before deletion, the Runner verifies
that the registered ticket branch is merged into registered `dev`, the Ticket
Worktree is clean, and the mapping and canonical path belong to the supplied
IDs. Failure refuses cleanup with evidence; an already-cleaned ticket succeeds.
Success removes the Ticket Worktree, merged ticket branch, all aliases, and
temporary transport diagnostics. It never deletes canonical tickets or
persistent Delivery Run evidence.

Setup creates or registers the Integration Worktree. If `dev` exists, setup
validates it and detects any conflicting checkout instead of silently moving or
switching it. If `dev` does not exist, setup shows the exact proposed base and
requires operator confirmation before creating the branch and worktree. Main
does not choose or type physical paths.

V1 targets at most four tickets concurrently: four Engineer processes and up
to eight Reviewer threads, in addition to Main and the Delivery State Agent.
Each Engineer process owns its Runtime session and Reviewer children, so
Main's native subagent limit is not treated as a global limit for externally
launched Engineers.

## Considered options

- Putting linked Worktrees inside the Source Repository, in a shared
  workspace-level project root, or in a system temp directory was rejected
  because of recursive discovery, cross-project access, accidental edits, and
  poor recovery durability.
- Creating one `dev` worktree per run was rejected because Git permits one
  checkout of a local branch and `dev` is the unique integration state.
- Integrating in the primary `main` checkout was rejected because routine
  development must not mutate the release worktree.
- Starting dependent work from unintegrated commits was rejected because it
  bypasses `dev` and duplicates conflict handling.
- Letting Engineers work in Main's Integration Worktree was rejected because a
  shared index and working directory destroy ticket isolation.
