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
team. Apply the user's ownership and configured role choices; do not infer
fixed role tiers from difficulty. Instruction-only changes need a consistency
check and a commit where tracked, not tests or Reviewers.
Main does not run tests. Engineers may run development tests; the Leader
is the sole test-acceptance role and runs any still-needed acceptance checks,
reusing valid development evidence. Reviewers never run tests or probes. This
does not require a Team for every auxiliary script.

For engineering delivery, read [coding dispatch](references/coding.md).
For another task type, use its actually available role or agreed direct work
arrangement; a team protocol must exist before it can be dispatched.

Give the executor the Ticket scope, its investigation findings, required inputs, acceptance mapping
and relevant predecessor evidence. Preserve the agreed
[node boundaries](../task-breakdown/SKILL.md#find-the-useful-boundaries) in the
dispatch instructions. Confirm sources are reachable from the assigned role's
permitted view. Reuse unchanged setup and evidence rather than reconstructing
them for every dispatch. Keep dispatch details concise. Main owns
cross-task decisions and integration; a selected team's Leader owns its
internal specialist workflow and acceptance decision.

## Dispatch and follow up

Every Agent communicates only with its direct parent and direct children;
coordinate failures and report corrections through the same hierarchy.
Cross-level status queries expose summaries, not raw member reports or Sessions.
The permitted control exception is interrupting one's own descendant subtree;
it does not authorize cross-level messages, approvals or replacement.

Formal team work uses `agent-runner --swarm-input <swarm.yml>`.
Each task supplies its role and launch instruction; Main adds the Ticket ID
selected from the DAG. Within a Ticket, the calling Session supplies that context.
Names and requirements come from the registered current definition. Use returned
aliases for later interaction. Respect configured depth and concurrency: a swarm
starts all selected tasks or none; reduce it or wait for sufficient capacity.

Wait for existing completion, failure and budget notifications. Keep one
active driver per Session; Main waits for the team's handoff while its Leader
owns member execution. Deliver assigned validation results through the existing
handoff instead of having Leader watch temporary files.
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

Do not wake or relaunch the Leader of an executing Ticket. Deliver relevant new
evidence only through its existing live execution; do not create another turn
or Driver to retrieve reports or status. After an execution has ended, use the
documented recovery path through the direct child and its causal event. Use `agent-runner interrupt <alias>` when
interruption is intended. Reuse valid reports and validation for unchanged
paths; have the assigned executor run affected checks and explicitly required
fresh validation.

Receive the result, validation, required review evidence and acceptance
decision. Runtime success alone does not establish acceptance. Before following
up on a Leader's implementation rejection, read
[Round handling](references/recovery.md#choose-the-round-before-continuing).
For an execution failure, sampled budget stop or repeated unproductive correction,
read [recovery decisions](references/recovery.md). Correct Main's scope or dispatch
errors as Main; the responsible Agent and its superior judge internal recovery.

Only the target's direct parent or the user may replace an Agent or Team.
Prefer asking the direct child to stop; interrupt when needed, or immediately
if it is out of control. Confirm the target and all descendants are stopped
before creating replacements, using the existing task and retained handoff.
An installed Main-only replacement gate or single-Agent interrupt is a tool
limitation, not permission for Main to replace a grandchild or assume its
descendants stopped. Return the limitation through the direct hierarchy.

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

Integrate accepted file results into the configured shared branch using the
appropriate validation evidence. The Leader owns any required
integration acceptance tests; Main must not run tests through the integration
command. For a registered formal Ticket use:

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
