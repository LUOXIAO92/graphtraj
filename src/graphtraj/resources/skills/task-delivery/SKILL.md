---
name: task-delivery
description: Deliver the current accepted Ticket DAG through Team Leaders. Main owns readiness, difficulty, cross-Ticket decisions, evidence-driven Task Graph revisions, integration, and Team retirement; each Leader owns its Engineer, both Reviewers, and Team Round decisions.
---

# Task Delivery

## Consume the current accepted graph

Read Harness Guidance, `CONTEXT.md`, the accepted Spec, and referenced ADRs at
the Harness Project Root. Read `.graphtraj/config.yml` for the recorded Source
Repository, documents, Worktrees, state, dispatch depth, and concurrency limit.
This works when the Source Repository is the Harness Project Root and when it
is its configured direct child. Do not rediscover the layout or treat Source
history as a reason to reject existing Project Documents. Reuse existing
`CONTEXT.md` and `docs/` as the document base, preserving their contents and Git
tracking. Team members read their Worktree documents; only missing paths use
links to shared documents. Main retains document-update authority.

Initialize with `graphtraj setup`: every core Skill belongs in the Harness
Project Root’s `.agents/skills`, including project-adapted Skills. A user-global
copy does not replace this installation; existing project Skills are preserved.

Consume accepted GitHub Tickets and explicit dependencies. Register missing
Tickets in dependency order with `graphtraj ticket register --ticket-file
<issue.yml>`. Supply `ticket_id`, `ticket_name`, `source` (Issue URL), `title`,
`body`, and `dependencies` (stable Ticket IDs). Read existing current state
instead of registering it again. Its `current_definition` selects the accepted
snapshot; `ticket.md` remains the immutable initial definition.

Generate readiness with `graphtraj ticket graph`; read causal facts with
`graphtraj worldline read`. Request a ledger-shaped Worldline view only when
useful. Do not persist a ledger, DAG, or task map. Never create or ask for a
Delivery Run or `run_id`; leave historical Run state untouched without fallback
reads. Initial requirement discovery belongs outside delivery, but acceptance
does not freeze the graph when delivery evidence disproves its structure.

## Keep decisions with their owners

- Main owns the whole request, readiness, Ticket difficulty, Team Leader
  dispatch, cross-Ticket coordination, Task Graph revisions, integration order,
  merge acceptance, Team retirement, and requests for user direction.
- Each Team Leader alone schedules its one active Engineer and both Reviewers,
  diagnoses Team-internal failures, corrects Team behavior, and decides Round
  outcomes after adversarial examination of implementation and Review evidence.
- Delivery State requests semantic records only from supplied Main and Leader
  decisions and observed execution facts. It never selects graph corrections,
  readiness, Review outcomes, rework, retirement, or integration. Deterministic
  commands validate fields, authority, references, and transitions before
  serializing Ticket, Team, and Worldline state.
- Runner retains only the exact Batch, Session mapping, append-only Trace,
  launch result, and terminal execution result it observes. Successful Runtime
  execution does not itself mean Team acceptance or integration.

Formal Agents run through `agent-runner`, including Delivery State. The Team
flow requests Delivery State serialization as needed; do not launch a native
Delivery State Agent or ask it to maintain a second history. Supply Main's
explicit registration, readiness, revision, and integration decisions through
the corresponding `graphtraj ticket` commands. Never hand-edit durable state
to bypass validation.

## Deliver each frontier

1. Regenerate the current graph and inspect new evidence. Main selects ready
   active Tickets whose current prerequisites have validated `dev` integration.
   A candidate or accepted Team Round alone cannot unlock a dependent.
   Record Main's readiness decision for a selected pending Ticket with
   `graphtraj ticket update --state-file <state.yml>`. Supply `ticket_id`,
   `status: ready`, the current `active_team_ordinal`, `worktree`, `branch`,
   `current_candidate`, `caused_by_event_ids`, and `evidence_refs`. Preserve
   current values; new Tickets have null Team, Worktree, branch, and candidate.
2. Classify selected Tickets as Junior, Senior, or Expert. Give each Leader
   the difficulty, current Ticket/Spec, acceptance mapping, and relevant
   cross-Ticket evidence. The Leader schedules the matching Engineer. Keep
   instructions concise; the current Ticket remains the scope source.
3. Main may dispatch several ready Tickets together when project capacity
   permits. Each task selects a Team Leader:

   ```yaml
   tasks:
     - ticket_id: "86"
       ticket_name: team-delivery
       role: team-leader
       instruction: Senior difficulty. Deliver the current accepted Ticket and report graph-boundary evidence to Main.
   ```

   Run `agent-runner --batch-input <batch.yml>` from the Harness Project Root.
   Runner validates and retains that exact selection; it does not find ready
   work. Do not add a Batch Runtime field, `run_id`, old `review_round`, or
   Main-selected Reviewer tasks or report paths.
4. Let Leaders complete their Team loops. Coordinate cross-Ticket facts
   through Leader Sessions. Use `agent-runner status <alias>` for execution
   evidence and `agent-runner send <alias> --instruction <text>
   --caused-by-event-id <event-id>` to follow up in the same historical
   Session. Use `agent-runner interrupt <alias>` when interruption is intended.
   Transport outcomes do not choose Ticket status or create a Team Round.
5. Inspect candidate, validation, both Reviews, and Leader decision. Correct
   graph errors before further affected dispatch, integrate eligible work in
   Main's order, regenerate readiness, and repeat across every newly ready
   frontier. `awaiting-integration` is a checkpoint, not completion.

Respect project-wide `max_concurrency`, including maximum one. A normal Batch
acquires capacity for all tasks or starts none; there is no queue. On
insufficient capacity, Main selects a smaller frontier or waits for known
executing work before retrying. Do not change the configured limit or treat it
as a per-Team quota. Formal depth counts descendants below Main: Leaders at
depth 1 and their children at depth 2.

## Let the Team Leader complete its Round

The Leader dispatches one difficulty-appropriate Engineer, then the Standards
and Spec Reviewers against the same fixed candidate and comparison point.
Supply the accepted Ticket/Spec and axis rules; use the exact Runner-supplied
report destinations. Both axes are required. The Engineer implements,
validates, and self-reviews; it neither dispatches Reviewers nor claims Review
acceptance. Main does not take over the Leader's two-axis adjudication.

In one Runtime call, the Leader registers at most one complete direct child
Batch and ends the call. The parent worker transfers its capacity position to
the first child, acquires only additional positions, waits for all registered
children, and resumes the same Leader Session with results and Trace references.
If the complete Batch cannot fit, no child starts. The Leader can schedule
Reviewers in separate Batches at maximum one; both still review the same
candidate in the same Round. Do not hold the Leader Runtime call open polling
for children or start another dispatcher.

The Leader rejects scope expansion, unsupported findings, speculative work,
and over-engineering. Follow the fixed Team role evidence contracts:

- Process correction uses `Decision: CORRECT`, the existing responsible role,
  accepted rule, and concrete reason. Resume that Session for reflection and
  correction in the same Round; repeat affected Reviews after Engineer changes.
  Current reports may be replaced while open. Rejected intermediate content
  remains in its author's Trace. This is not implementation rework.
- A new Round requires compliant two-axis Review rejecting the implementation
  and the Leader's explicit confirmation: `Decision: REJECT`, `Diagnosis:
  implementation`, `Reviews: compliant`, `Action: rework`, and an evidence-based
  `Rationale:`. Wait for confirmation that the old Round closed and the new one
  opened before dispatching. Keep small corrections with the same Engineer and
  tier. Closed Round evidence is immutable.
- A positive adversarial decision uses `Decision: ACCEPT` and the fixed
  candidate. Delivery State records that supplied decision; the candidate
  becomes eligible for Main's integration without merging it.
- Wrong Ticket boundaries, dependencies, acceptance mappings, unnecessary work,
  or Main instructions return evidence to Main for graph correction. Product
  or Spec conflicts return to Main for user direction. Neither automatically
  opens another Round as a compliant implementation failure.

Diagnose before repeating work or changing a seat. Failure counts are historical
evidence, never an automatic retry, replacement, or escalation rule. Transport
failure, Reviewer error, integration failure, and external blockers alone do
not establish an Engineer capability mismatch.

## Correct the Task Graph from delivery evidence

When implementation, validation, Review, or integration disproves the structure,
Main pauses affected dispatch and re-examines the smallest affected subgraph.
Identify the wrong boundary, edge, acceptance mapping, or unnecessary work.
Cite retained evidence and causal Worldline events, and preserve all accepted
product behavior and acceptance coverage.

A product-preserving correction proceeds autonomously. Stop for user direction
if product behavior or acceptance would change, a genuine product choice
remains unresolved, or new external authority is needed. Do not label such a
change product-preserving to bypass that boundary.

Supply one complete correction to
`graphtraj ticket revise --revision-file <revision.yml>`. The YAML contains
`product_preserving: true`, `caused_by_event_ids`, Harness-root-relative
`evidence_refs`, and `tickets`: every affected full definition with
`ticket_id`, `ticket_name`, `source`, `title`, `body`, `dependencies`, `active`,
and `replaced_by`. Keep existing GitHub identities stable; new nodes refer to
accepted GitHub Tickets.

| Correction | Current definitions and dependencies |
| --- | --- |
| Split | Add accepted parts, deactivate the old Ticket, identify replacements, and update affected dependents. |
| Merge | Expand a survivor or add an accepted combined Ticket; deactivate absorbed Tickets, identify their replacement, and redirect affected edges. |
| Replace | Record the accepted replacement, deactivate its predecessor, and redirect dependencies. |
| Remove | Deactivate unnecessary work with no replacement and remove obsolete edges while preserving acceptance coverage. |
| Dependency or acceptance mapping | Revise the affected definition and edges without inventing new work. |

The command validates the complete affected graph and atomically records new
immutable definitions, current state, and the causal Worldline event. Preserve
initial snapshots, earlier definitions, Team Rounds, Traces, Batches, and
Worldline events. Do not rewrite prior reports to fit the new plan.

Regenerate `graphtraj ticket graph` after correction. Do not dispatch inactive
Tickets or use stale edges. Give affected Leaders the current definition and
revision event before continuing. Main decides whether their Teams can continue
or need replacement. A graph correction does not itself authorize another
Round or make an old candidate satisfy revised acceptance mapping. Obtain Team
evidence for the current definition before integration.

## Select roles and recover Teams

A string `role` resolves Runtime, model, and optional connection settings from
`.graphtraj/roles.yml`. When a needed preset is absent, use a one-entry inline
role, for example:

```yaml
role:
  investigation-specialist:
    runtime: codex
    model: gpt-5.6-luna
```

The Batch retains the exact inline definition; it does not become a preset.
Fixed role restrictions still apply. Omitted connection settings use Runtime
defaults; store an API-key environment-variable name, never credentials.
Engineer child tasks may select Repository Skills by semantic name with
`skills: [skill-name]`. Unselected Repository Skills remain disabled.
The exact selection stays in the retained Batch and the Adapter's immutable
launch context; resuming the Session preserves that selection.

Main's Runtime is outside child presets. Claim Review Diversity only when the
configured Runtime or model actually differs.

Main may use Runtime-native helpers for temporary read-only investigation.
A Leader may do so when its resolved `allow_runtime_swarm` permits it.
Helpers cannot implement, Review, occupy Team seats, or replace formal Runner
dispatch; their independent history is not a GraphTraj Trace. Engineers and
Reviewers cannot dispatch formal children or native helpers.

Only Main or the user initiates Team retirement. For replacement, Main uses
`agent-runner replace <leader-alias> --actor main --caused-by-event-id <event-id>`.
Runner stops new Team work, obtains the retiring Leader's final `$handoff`
response in its Trace, and starts the next Team generation on the same Ticket
branch and Worktree. Read that Trace and the current definition when continuing;
do not create a separate handoff artifact. Replacing a non-Leader seat preserves
the Team generation and prior Traces. After worker failure, recover from durable
facts and alias status; do not assume unattended recovery will finish work.

## Integrate, clean up, and continue

Main serializes accepted candidates in the configured `dev` Integration
Worktree. Run `graphtraj ticket integrate --ticket-id <id> -- <validation-command>
<arguments>` with the project's required validation. The command performs
Main's selected merge and retains validation evidence; it does not choose the
order. Record `integrated` only when the candidate is present in `dev` and
validation passes.

For an observed textual or semantic integration conflict, Main may invoke the
same command with `--resolve-conflict <evidence-based instruction>` before
`--`. It dispatches a Merge Resolver for that actual conflict. Main adjudicates
the resolution and keeps the required validation; ordinary integration does not
need a Resolver or another Team Review. Failed validation never unlocks
dependents. If integration disproves the graph, correct it before further
dispatch; if it requires a product decision, return to the user.

After accepted integration, use `agent-runner cleanup --ticket-id <id>`.
Cleanup verifies integration and a clean disposable Worktree before removing
safe live mappings, Worktree, and branch. Durable Ticket, Team, Round, Batch,
Trace, and Worldline evidence remains. Do not clean up unintegrated work as if
it were delivered.

Continue until every active Ticket in the current graph has validated `dev`
integration or evidence requires an authorized stop. Honor user interruption
or redirection immediately. A blocked Ticket does not end independent ready
work; report the precise blocker and decision needed when no authorized progress
remains. Finish with delivered Tickets, integration and validation evidence,
graph corrections, and outstanding concerns. Do not promote `dev` to `main`.
