---
name: task-delivery
description: Coordinate accepted tasks through dispatch, result submission, acceptance, integration and recovery.
---

# Task Delivery

Read the project's guidance, current task graph and accepted requirements. Use
the configured paths, roles, Runtime settings and execution limits. Run Harness
commands from the Harness Project Root.

## Assign ready work

Select tasks whose required predecessor results are integrated. Read the current
Ticket definition and provide its scope, findings, inputs and acceptance criteria.
Choose the actual expertise and professional methods the task needs. A Team can
have one member. Role names do not grant task acceptance or control authority;
role_tree permits dispatch edges, while real Session bindings determine parents.
Apply the project's assigned validation responsibilities.

When the project selects the coding-team method, read
[coding dispatch](references/coding.md). Other tasks use their selected roles and
instructions with the same task lifecycle. Professional checks produce evidence
for task acceptance; they do not create another completion protocol.

Formal dispatch uses `agent-runner --swarm-input <swarm.yml>` with the selected
role, instruction and ready Ticket ID. Reuse the registered definition and returned
aliases. Repository Skills named in `skills` must exist in the task's Worktree;
read Harness Skills through their supplied paths. If child dispatch returns
`registered`, end that dispatch turn so the existing Driver can start the child.
Keep one execution per Session and communicate only with direct parents/children.

## Receive and decide results

Wait for completion, failure and budget events. Apply the project's polling limit
when an additional observation is necessary. Public status gives cross-level
summaries; private reports stay within the direct relationship. Send changed
instructions through the existing execution rather than waking another copy.

The executing Session commits its file results and uses `submit-result` to record
the version, result references, completion statement, evidence and unresolved work.
Use assigned report destinations. No role-specific filename or prose format is a
universal submission or acceptance condition. Session completion alone does not
accept or finish a Ticket.

The authorized parent or task-authorized caller assesses the submitted version
against the task's criteria, reusing valid evidence. Use `decide-result` to record
the exact submission/version, accepted or rejected decision, reason and evidence.
Use actual caller identity; a role label is not permission. Return concrete missing
behavior or evidence for correction and preserve the earlier decision. Read
[command inputs](references/command-inputs.md) for current operations.

## Integrate and continue

Integrate the accepted result with `graphtraj ticket integrate`, using the task's
necessary validation and its assigned executor. If integration changes the accepted
result, confirm the affected behavior before completion and reuse unaffected
checks. For an actual conflict, use a permitted specialist and the retained evidence.

After integration use `agent-runner cleanup --ticket-id <id>`, retain original
Batches/Sessions/Traces, regenerate the task graph and continue newly ready work.
A failed integration or necessary check does not complete the Ticket or unlock its
successors. Finish when the accepted scope is integrated or authorized progress is
blocked; report exact results and remaining obstacles.

## Limits and recovery

Honor the existing Ticket budget and Runner's enforced stop. Budget notices go to
the task's actual parent, which coordinates its children; stopping does not wait
for the notice to be processed. Keep elapsed accounting and stop history. An
interruption, recovery or replacement does not authorize more time.

For a failure, stop or replacement, read [recovery](references/recovery.md).
Identify the failing action and its responsible direct parent, retain useful work,
and use public continuation/replacement operations. Replace only after the target
and descendants are stopped and the real parent or user has authority. Preserve
native approvals and file/report boundaries.

When evidence changes task boundaries or reveals a common prerequisite, use
the project's decomposition method and `ticket revise` to correct the graph before dependent
work. Preserve original inputs and causal evidence. Product changes need user
direction; ordinary product-preserving graph corrections follow project guidance.
