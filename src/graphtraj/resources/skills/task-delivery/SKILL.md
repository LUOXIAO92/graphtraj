---
name: task-delivery
description: Coordinate accepted tasks through dispatch, event-driven follow-up, recovery after failures or budget stops, and validated integration.
---

# Task Delivery

Read Harness Guidance, the current task graph and its accepted requirements.
Use the configured project paths, roles and execution limits. Run Harness
commands from the Harness Project Root.

## Select the work and its executor

Select active nodes whose required predecessor results have been accepted
and integrated. Apply known blocker reports to dependencies before dispatching
affected work; do not wait for another execution to hit the same gap. Read the
existing current definition before registering or changing a Ticket. Preserve
completed predecessor edges and register missing
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
and relevant predecessor evidence. Preserve the agreed
[node boundaries](../task-breakdown/SKILL.md#find-the-useful-boundaries) in the
dispatch instructions. Confirm sources are reachable from the assigned role's
permitted view. Reuse unchanged setup and evidence rather than reconstructing
them for every dispatch. Keep dispatch details concise. Main owns
cross-task decisions and integration; a selected team's Leader owns its
internal specialist workflow and acceptance decision.

## Dispatch and follow up

Formal team work uses `agent-runner --batch-input <batch.yml>`.
Respect configured depth and concurrency. A Batch starts all selected tasks
or none; reduce it or wait when there is insufficient capacity.

Wait for existing completion, failure and budget notifications. Keep one
active driver per Session; Main waits for the team's handoff while its Leader
owns member execution. For Main-owned external validation, deliver the outcome
through the existing handoff instead of having Leader watch temporary files.
Keep the Runner's caller notice channel connected to Main's waiting execution
tool as well as the Leader notification path; retaining a notice only in a log
does not deliver it to Main. Let the timer return information automatically,
rather than scheduling Agent queries to discover an elapsed threshold.

On a received event, read only the evidence needed for the next decision.
When a proactive check is necessary, apply Harness Guidance's shared polling
limit across Main, Leader, delegates, scripts and tools. Use
`agent-runner status <alias>` for status and `graphtraj worldline read` for
retained evidence; do not query both merely to confirm nothing changed.
Progress messages use known state and do not trigger another check.

Send relevant new evidence with `agent-runner send <alias> --instruction <text>
--caused-by-event-id <event-id>` under its active-execution semantics; do not
start a second driver to deliver it. Use `agent-runner interrupt <alias>` when
interruption is intended. Reuse valid reports and validation for unchanged
paths; rerun affected checks and explicitly required fresh validation.

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

When a task's scope changes, a shared input changes, or a missing common
prerequisite is discovered, Main rechecks affected pending and active tasks:
boundaries, dependencies and the starting results each executor relies on.
Pause affected dispatch or obsolete work while making the smallest
product-preserving correction under Harness Guidance; independent work can
continue. Use `task-breakdown` for boundary changes, reusing guidance and results
already available. Record changed definitions with `graphtraj ticket revise`
and the command reference, retaining the original dispatch inputs.

Give affected executors the corrected assignment, prerequisite results and
reusable evidence before continuing. Each shared prerequisite has one owner;
consumers continue from its result instead of separately adapting an obsolete
starting point. Main owns this cross-task check; a Team's internal review does
not establish that parallel assignments are compatible.

When validation or integration exposes incompatible assumptions or duplicated
work, correct the affected task arrangement as well as the immediate conflict.
Changes to the product goal or acceptance require user direction. A graph
revision alone does not accept a candidate or manufacture Team evidence.

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
independent work within the user's current continuation or pause instruction.
Keep original Batch and Session evidence; generated views
need no separate persisted ledger. Treat integration as one completed handoff;
do not regenerate the graph or repeat cleanup on an unchanged status check.

Finish when the accepted scope is integrated or no authorized progress remains.
Report delivered results, validation, graph changes and concrete blockers.
For tracker publication, summarize the delivered behavior, commit and relevant
checks. Select information for the external reader; temporary probes, private
paths and raw diagnostic payloads stay in their existing local records.
