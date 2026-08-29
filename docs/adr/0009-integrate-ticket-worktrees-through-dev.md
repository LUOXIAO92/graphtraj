---
status: accepted
---

# Integrate isolated Ticket Worktrees through dev

> **Partial supersession:** [ADR 0013](0013-own-runtime-resources-at-the-harness-root.md)
> replaces the requirement that normal Main sessions run from Integration and
> that setup write Harness Runtime resources there. Integration's Git, merge,
> validation, and Worktree-lifecycle responsibilities remain accepted.

Engineers implement in isolated Ticket Worktrees while one long-lived
project-level **Integration Worktree** owns serialized development integration.
The Integration Worktree lives at
`<harness-project-root>/.agent-worktrees/integration`, is fixed to `dev`, and
is shared by concurrent Delivery Runs. The operator-selected repository
directory is the **Primary Worktree**, remains on `main`, and is reserved for
release work.

One Main orchestration context owns Integration Worktree writes for a Harness
Project at a time and may interleave the serial integration work of several
Delivery Runs. A Main-coordinated Merge Resolver writes there only under that
same ownership. This is a soft-Harness operating responsibility, not a Runner
lock, resident coordinator, or Delivery Run control state.

The linked Integration and Ticket Worktrees remain part of the same Source
Repository but live outside its Primary Worktree, inside the dedicated Harness
Project Root under the project-private `.agent-worktrees/` directory defined by
[ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md). Setup ensures
this directory is writable under the host and Runtime sandbox configuration.
It is neither committed configuration nor batch input, must not resolve inside
the Primary Worktree, and is canonicalized and checked against
`git worktree list`. Setup and the Runner never treat the parent workspace as a
shared project or authorization boundary.

Ticket Worktrees are run-scoped:

```text
<harness-project-root>/.agent-worktrees/runs/<run-id>/<ticket-stem>
```

Project isolation is already supplied by the Harness Project Root, so the
Runner derives branch names and paths only from the Delivery Run and stable
ticket identity. The mechanical `ticket-stem` is
`<ticket-id-length>-<encoded-ticket-id>-<ticket-name>`: the length is the
decimal ASCII length of the validated original ID, and each dot in that ID is
encoded as `%2E`. The length prefix makes the ID/name boundary unambiguous, so
identities such as `(a-b, c)` and `(a, b-c)` cannot collide; `ticket_name`
remains a readable suffix rather than another identity key. The same stem is
used in branch, Worktree, and evidence-directory names; ADR 0008 alone defines
how a live Session alias incorporates it. No project name is repeated inside
the project's branch or Worktree namespace. A Worktree is a complete isolated
checkout and the Engineer's editable repository root, not a Main-designed file
or directory allowlist.

One `ticket_id` may have at most one live Ticket Worktree in a Harness Project,
regardless of how many Delivery Runs are active. Runner preflight rejects a
batch that assigns an already-live ticket to another Run. Retries and tier
escalation reuse the same branch and Worktree, while a later batch in the same
Run recovers and validates it but creates a fresh Runtime session; only `send`
resumes an existing alias. If successful-merge cleanup already removed the
Ticket Worktree, a later Run may create a new branch, Worktree, and Runtime
session for that ticket from the then-current validated `dev` state.

Ticket branches start from the current validated `dev` state. Independent
tickets may share a base snapshot. A dependent ticket starts only after its
prerequisites are merged and validated in `dev`. Review `PASS` makes work
eligible for integration but does not update `dev`; Main performs merge,
conflict reconciliation, and integration validation in the Integration
Worktree outside the `task-delivery` Skill, then resumes the same Delivery Run.
The Skill does not own or perform serialized integration. Promotion from `dev`
to `main` is a release concern outside both Task Delivery and the Delivery Run.

Normal planning and delivery Main sessions run from the registered Integration
Worktree. `task-delivery` verifies that workspace before dispatch. Starting an
Engineer with its resolved Ticket Worktree lets the existing guard derive the
correct immutable root; its native Reviewer children inherit that workspace.

After a reviewed commit is successfully merged and validated in `dev`, Main
instructs the Runner to clean up the ticket:

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
persistent Delivery Run evidence. Cleanup also removes the now-empty Run
Worktree directory and the `runs/` parent when no Ticket Worktrees remain;
empty lifecycle directories are not retained as state.

Setup creates or registers the Integration Worktree. If `dev` exists, setup
validates it and detects any conflicting checkout instead of silently moving or
switching it. If `dev` does not exist, setup shows the exact proposed base and
requires operator confirmation before creating the branch and worktree. Main
does not choose or type physical paths. After establishing the Integration
Worktree, the same setup invocation writes the reviewable Runtime resources
there as described in
[ADR 0010](0010-configure-target-projects-locally.md).

V1 targets at most four tickets concurrently: four Engineer processes and up
to eight Reviewer threads, in addition to Main and the Delivery State Agent.
Each Engineer process owns its Runtime session and Reviewer children, so
Main's native subagent limit is not treated as a global limit for externally
launched Engineers.

## Considered options

- Putting linked Worktrees inside the Primary Worktree, in a shared
  workspace-level project root, or in a system temp directory was rejected
  because of recursive discovery, cross-project access, accidental edits, and
  poor recovery durability.
- Creating one `dev` worktree per run was rejected because Git permits one
  checkout of a local branch and `dev` is the unique integration state.
- Integrating in the `main` Primary Worktree was rejected because routine
  development must not mutate the release worktree.
- Starting dependent work from unintegrated commits was rejected because it
  bypasses `dev` and duplicates conflict handling.
- Letting Engineers work in Main's Integration Worktree was rejected because a
  shared index and working directory destroy ticket isolation.
