---
name: task-delivery
description: Coordinate an accepted task graph through readiness, team selection, dispatch, acceptance and validated integration.
---

# Task Delivery

Read Harness Guidance, the current task graph and its accepted requirements.
Use the configured project paths, roles and execution limits. Run Harness
commands from the Harness Project Root.

## Select the work and its executor

Select active nodes whose required predecessor results have been accepted
and integrated. Read the existing current definition before registering or
changing a Ticket. Preserve completed predecessor edges and register missing
accepted nodes before dispatch; readiness is determined by predecessor status.
Use [command inputs](references/command-inputs.md) for
registration, readiness and graph revisions.

Choose the executor from the task's needed expertise and accepted completion
criteria. Direct work stays with the current Agent when it needs no formal
team. Small auxiliary scripts receive suitable checks without automatically
creating tickets or triggering a team workflow.

For engineering delivery, read [coding dispatch](references/coding.md).
For another task type, use its actually available role or agreed direct work
arrangement; a team protocol must exist before it can be dispatched.

Give the executor the authoritative task, required inputs, acceptance mapping
and relevant predecessor evidence. Keep dispatch details concise. Main owns
cross-task decisions and integration; a selected team's Leader owns its
internal specialist workflow and acceptance decision.

## Dispatch and follow up

Formal team work uses `agent-runner --batch-input <batch.yml>`.
Respect configured depth and concurrency. A Batch starts all selected tasks
or none; reduce it or wait when there is insufficient capacity.

Use `agent-runner status <alias>` for execution status and
`graphtraj worldline read` for retained evidence. Send relevant new evidence
with `agent-runner send <alias> --instruction <text>
--caused-by-event-id <event-id>`. Use `agent-runner interrupt <alias>` when
interruption is intended.

Receive the result, validation, required review evidence and acceptance
decision. Runtime success alone does not establish acceptance. For an execution
failure, sampled budget stop or repeated unproductive correction, read
[recovery decisions](references/recovery.md). Correct Main's scope or dispatch
errors as Main; the responsible Agent and its superior judge internal recovery.

Only Main or the user retires a formal Team. Use
`agent-runner replace <leader-alias> --actor main
--caused-by-event-id <event-id>`; the successor uses the existing task
definition, branch, Worktree and predecessor's handoff.

## Revise the graph when evidence requires it

When implementation, validation or integration disproves a boundary or edge,
pause affected dispatch and make the smallest product-preserving correction
under Harness Guidance. Use `graphtraj ticket revise` and the command
reference, retaining prior definitions and the evidence for the change.

Give affected executors the current definitions and revision evidence before
continuing. Changes to the product goal or acceptance require user direction.
A graph revision alone does not accept a candidate or manufacture Team evidence.

## Integrate and continue

Integrate accepted file results into the configured shared branch with the
validation appropriate to those results. For a registered formal Ticket use:

```text
graphtraj ticket integrate --ticket-id <id> -- <validation-command> <arguments>
```

Only an accepted candidate present in `dev` with passing validation satisfies
the current Harness's integration gate. Commit completed changes and merges
under project guidance. For an actual conflict, select a resolver with the
required domain expertise; Main adjudicates the result and validation.

After formal Ticket integration use `agent-runner cleanup --ticket-id <id>`.
Regenerate the current graph with `graphtraj ticket graph` and continue ready
independent work. Keep original Batch and Session evidence; generated views
need no separate persisted ledger.

Finish when the accepted scope is integrated or no authorized progress remains.
Report delivered results, validation, graph changes and concrete blockers.
For tracker publication, summarize the delivered behavior, commit and relevant
checks. Select information for the external reader; temporary probes, private
paths and raw diagnostic payloads stay in their existing local records.
