---
name: task-delivery
description: Coordinate accepted tasks through dispatch, result submission, acceptance, integration and recovery.
---

# Task Delivery

Read the project's guidance, current task graph and accepted requirements. Use
the configured paths, roles, Runtime settings and execution limits. Run Harness
commands from the Harness Project Root.

The shared tool's default describe returns a readable guide reference. Read that
file as needed; request describe with `schema: true` for the selected operation's
parameters. Known authorized operations need no prior describe call.

## Assign ready work

Select tasks whose required predecessor results are integrated. Read the current
Ticket definition and provide its scope, recorded difficulty assessment,
resource assumptions, findings, inputs and acceptance criteria. Use that assessment
to select the actual expertise and professional methods the task needs. A Team can
have one member. Role names do not grant task acceptance or control authority;
role_tree permits dispatch edges, while real Session bindings determine parents.
Apply the project's assigned validation responsibilities.

Difficulty assessment belongs to [task-breakdown](../task-breakdown/guide.md).
Use it to complete a missing assessment or revise one when new evidence changes
scope, resource fit or granularity; delivery consumes that result rather than
running a second assessment. Consume the registered node's required artifacts
and preserved evidence; use the project's selected professional methods without
changing the common completion protocol.

Formal dispatch uses `agent-runner --swarm-input <swarm.yml>` with the selected
role, instruction and ready Ticket ID. Reuse the registered definition and
returned aliases. Supply external role instructions and explicitly selected
resources through the configured Runtime's supported mechanisms; GraphTraj
does not choose a professional Skill by its name.
If child dispatch returns `registered`, end that dispatch turn so the existing
Driver can start the child.
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

Task notices identify their existing Agent alias and carry the recorded event
and message, with `source: graphtraj`. They do not need duplicate Ticket or
Session identity fields. A mapped Agent notifies its actual direct parent; root
notifications require the owning host's existing parent Session connection.
Keep that host binding alive while Agents can still produce events, including
after an individual tool call or `send` acknowledgement returns. The selected
Runtime delivers input to the parent's current turn or continues its idle
Session. A channel write or forwarding acknowledgement is not evidence that
the parent processed the event. Handle the event's result or explicit request
through the existing result/reply operation.

A root Agent can use `agent-runner parent-status` or `parent_status` to observe
its recorded owning host without sending input. With a positive finite timeout,
the operation waits on native events for that host to become idle. Choose the
timeout within the remaining execution budget. The caller supplies no parent
identity or connection; Main cannot synchronously wait for its own turn to end.
An unavailable operation, timeout or failed observation is not proof of idle.
After observing idle, notification validation still needs an ordinary event to
reach the same Main and be handled there.

The authorized parent or task-authorized caller assesses the submitted version
against the task's criteria, reusing valid evidence. Use `decide-result` to record
the exact submission/version, accepted or rejected decision, reason and evidence.
Use actual caller identity; a role label is not permission. Return concrete missing
behavior or evidence for correction and preserve the earlier decision. Read
[command inputs](references/command-inputs.md) for current operations.

## Integrate and continue

Before integration, identify the accepted input versions, target and task-specific
checks. Git can combine Markdown, LaTeX, data and software results. A clean text
merge alone does not establish that the result satisfies the task: preserve
citations, definitions, data meaning or behavior as applicable. For incompatible
content, resolve against the accepted requirements and source evidence; do not
invent a new outcome. Use a specialist only when the actual conflict needs one.
Commit changed tracked results and retain their version and provenance. Reuse
valid evidence for unchanged inputs and verify the affected combined result
through the project's assigned executor. No coding review or named merge role
is a universal integration requirement.

Integrate the accepted result with `graphtraj ticket integrate`, using the task's
necessary validation and its assigned executor. If integration changes the accepted
result, confirm the affected behavior before completion and reuse unaffected
checks. For an actual conflict, use a permitted specialist and the retained evidence.

After integration use `agent-runner cleanup --ticket-id <id>`, retain original
Batches/Sessions/Traces, regenerate the task graph and continue newly ready work. A completed input
remains a dependency. A later node absorbs an earlier result only when it
actually contains the artifact its consumer needs; retain independent inputs.
A failed integration or necessary check does not complete the Ticket or unlock its
successors. Finish when the accepted scope is integrated or authorized progress is
blocked; report exact results and remaining obstacles.

## Main completion checking

Use the selected Runtime's session-entry integration to recognize the external
Main and carry its current Session association through CLI, Tool and MCP calls.
GraphTraj members retain their existing identities and parent relationships.
Runtime-native and supported plugin children, including the checker, must not
register as Main or recursively activate its completion hook. Unknown sources
remain explicitly unrecognized. Review installation material through the
Runtime's normal configuration and trust mechanism before enabling the hook.

For an already-running Codex Main, a trusted Stop can reuse the native entry
checks to establish a missing association when its ownership of existing root
Agents is verified. No restart, fabricated startup event or manual binding is
required.

The Adapter runs and collects the checker using Main's current native context
and actual Runtime settings. Main does not relay prepare, spawn or collect
operations. The checker identifies the current task from inherited context and
verifies the applicable Issue, DAG and Tickets; a supplied Issue reference is
a hint to verify, not a permanent task binding.

Every activation visibly reports its start and outcome. Completed work or
legitimate waiting permits the turn to end without another Main input or reply.
Actionable unfinished work returns to the same Main with the concrete next work.
Unreadable task sources and execution errors are visible failures. Preserve user
stops, permissions and execution limits: a check grants no time, approval or
acceptance. It does not redo code Review or create another task ledger.

Validate actual host behavior after adopting a fixed installation. Configuration
material and controlled checks alone do not prove live Session recognition,
configuration inheritance or the absence of duplicate Main replies.

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
