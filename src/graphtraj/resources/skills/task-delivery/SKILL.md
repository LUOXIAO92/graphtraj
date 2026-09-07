---
name: task-delivery
description: Deliver an accepted Ticket DAG through Team Leaders, from readiness and dispatch to validated dev integration.
---

# Task Delivery

## Read the current work

Read Harness Guidance, `CONTEXT.md`, the accepted Spec, and referenced ADRs
at the Harness Project Root. Read `.graphtraj/config.yml` for project paths,
dispatch depth, and concurrency; use `.graphtraj/roles.yml` for role presets.
Run commands from the Harness Project Root.

Consume accepted GitHub Tickets and explicit dependencies. Register missing
Tickets in dependency order; otherwise use the existing `current_definition`.
Read [command inputs](references/command-inputs.md) before registering Tickets,
recording readiness, or submitting a graph revision.

Use `graphtraj ticket graph` for the current graph and
`graphtraj worldline read` for causal evidence. Generated views need no separate
persisted ledger or DAG. Historical Delivery Run state remains untouched.

## Select and dispatch ready Tickets

Main owns readiness, difficulty, cross-Ticket decisions, graph revisions,
integration, and Team retirement. Each Leader owns its Engineer, both Reviewers,
and Team Round decisions under the Runner-supplied role instructions.
Formal work uses `agent-runner`; state changes use validated commands.
Delivery State records supplied decisions; Runner records execution facts.
Neither decides acceptance on Main's or the Leader's behalf.

1. Select active Tickets whose prerequisites have validated `dev` integration.
   Record readiness for selected pending Tickets using the command reference.
2. Classify each as Junior, Senior, or Expert. Give its Leader the difficulty,
   current Ticket/Spec, acceptance mapping, and relevant cross-Ticket evidence.
   Keep dispatch instructions concise; the Ticket remains the scope source.
3. Dispatch selected Tickets with `agent-runner --batch-input <batch.yml>`:

   ```yaml
   tasks:
     - ticket_id: "86"
       ticket_name: team-delivery
       role: team-leader
       instruction: Senior difficulty. Deliver the current accepted Ticket.
   ```

A Batch starts all selected tasks or none. Respect project-wide
`max_concurrency`: reduce the Batch or wait for executing work when capacity
is insufficient. Leaders schedule their own children within the same limit.

## Follow the Teams

Let each Leader run implementation and both review axes against the same fixed
candidate and comparison point. Main receives the candidate, validation,
both Reviews, and the Leader's decision; it does not schedule the Reviewers
or take over Team adjudication. Runtime success alone is not acceptance.

Use `agent-runner status <alias>` for execution status. Send relevant evidence
to an existing Leader Session with `agent-runner send <alias> --instruction
<text> --caused-by-event-id <event-id>`. Use `agent-runner interrupt <alias>`
when interruption is intended.

Return Team-internal problems to the Leader. Correct Main-caused graph or
scope errors as Main; seek user direction for product or Spec changes.
Diagnose failures before choosing further work or replacement; failure counts
alone do not establish an Engineer capability mismatch.

Only Main or the user initiates Team retirement. To replace a Team, use
`agent-runner replace <leader-alias> --actor main --caused-by-event-id <event-id>`.
The successor continues on the same Ticket branch and Worktree using the
current definition and the predecessor's handoff. Recover from retained state
and alias status after worker failure.

## Correct the graph when evidence requires it

Pause affected dispatch when implementation, Review, or integration shows an
incorrect Ticket boundary, dependency, acceptance mapping, or unnecessary work.
Apply the Harness Guidance rules for product-preserving graph revisions;
product changes and new external authority require user direction.

Submit the complete affected definitions through `graphtraj ticket revise`
using the command reference. Preserve prior definitions and evidence.
Regenerate the graph and give affected Leaders the current definitions and
revision event before continuing. Decide whether their Teams can continue or
need replacement. Integration requires Team evidence for the revised scope;
a graph correction alone does not open a new Round or accept an old candidate.

## Integrate and continue

Main integrates accepted candidates serially in the configured `dev` Worktree:

```text
graphtraj ticket integrate --ticket-id <id> -- <validation-command> <arguments>
```

Supply the project's required validation. Only a candidate present in `dev`
with passing validation counts as integrated and unlocks dependents.
For an observed textual or semantic conflict, add
`--resolve-conflict <evidence-based instruction>` before `--` to dispatch a
Merge Resolver. Main adjudicates the resolution and retains required validation.
If integration disproves the graph, correct it before further affected dispatch.

After accepted integration, use `agent-runner cleanup --ticket-id <id>`.
It checks integration and Worktree cleanliness and preserves durable evidence.
Regenerate readiness and continue independent ready work even if another Ticket
is blocked. An accepted Team Round awaiting integration is not completion.

Finish when every active Ticket has validated `dev` integration or no authorized
progress remains. Honor user interruption or redirection immediately. Report
delivered Tickets, integration and validation evidence, graph corrections, and
remaining blockers. Do not promote `dev` to `main`.
