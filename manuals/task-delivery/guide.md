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

## GraphTraj Agent identity

GraphTraj registers Main, members and completion checkers with their purpose
and direct parent. Runtime session/thread identifiers remain execution handles
inside Adapters rather than identity or authority. Query the bound caller with
`agent-runner identity` or the `agent_identity` tool operation; an unregistered
model caller is not Main, and human CLI access is a separate context.

An existing external Main is adopted by its owning host through
`HostTool.adopt_main(runtime_name)`, with the actual host reviewer and event
receiver supplied to `bind`. These callbacks are host integration, not model
request arguments or an approval stub. No replacement Main conversation is
started. A new binding restores a stopped identity with `resume=recorded_alias`
or performs authorized replacement with `replaces=stopped_alias`, preserving
history and original descendant parentage.

The owning Main registers a checker through `register_checker(receiver)` before
Adapter execution and closes its binding when finished. CLI/MCP calls use that
Agent's `cli_channel(verify_writer)` and required channel access; the host checks
the actual writer rather than trusting an environment address or shared PID.
Adoption requires a host capable of this integration; installing a package does
not retrofit callbacks into an already-running conversation or enable a hook.

## Main completion checking: finish-check

An existing external Codex Main uses `graphtraj adopt-main` from its actual
native terminal in the Harness Project Root. The command obtains the selected
native review, registers the existing conversation and prints its ready alias
and hook material. Keep this foreground owner running; it creates no replacement
Main and enables no hook. Closing it revokes the private lifecycle attachment.
Restore a stopped owner in the same conversation with
`graphtraj adopt-main --resume <returned-alias>`, preserving its history.

For ordinary requests from that external Main, use the returned
`operation_binding` with `graphtraj main-operation --binding <path> --request
'<public request JSON>'`. Obtain the native execution permission for the exact
command if its sandbox denies the private binding. The retained owner supplies
the registered caller identity; the path alone grants none. Lifecycle and
ordinary-operation capabilities are separate. Bare `graphtraj-tool` does not
automatically gain this binding, while managed Agent channels keep their
existing route. Existing root relationships are resolved from their retained
owning connection without rewriting the original parent records.

An already integrated Python host can instead retain its authenticated
`HostTool.cli_channel(verify_writer)` and use `graphtraj bind-finalize` or
`bind_main_finalize`. An optional summary Issue is only a hint; the public
adoption command does not need it. The shared `adopt_main` feature directs
callers to the retained CLI owner, not a model-supplied executor. Installation
alone establishes neither adoption nor observed hook behavior.

Review and adopt returned material through the Runtime's configuration and
trust mechanism, honoring explicit user disablement. Preserve the owning
host/channel for the hook's lifetime. Preparation is not enablement or observed
receipt; legacy static Session bindings and expired channels fail visibly.
The fixed trusted hook uses a private lifecycle-only host attachment; ordinary
Agent commands keep their own interface and file permissions. Trusted hook
execution is not evidence of a model command's filesystem sandbox.

GraphTraj identity selects Main and excludes members and checkers. The checker
inherits native context and Main's complete effective Runtime configuration,
including current-turn overrides. The Adapter must preserve those settings or
fail explicitly, rather than substitute stored defaults. The checker identifies
the current goal, then treats its Issue, current DAG and Tickets as the state authority.
Resolve stale/conflicting hints or return an error when the goal cannot be
identified. Completed work or legitimate waiting for an execution, event or
approval permits Main to finish its turn. Actionable unfinished nodes return
an exception to the same Main. Keep real user stops and execution limits;
the check grants no approval, time extension or acceptance. Unreadable state or
checker errors remain explicit failures, not a completed-task conclusion.
Every activation visibly starts with `[GraphTraj hook: finish-check]` and
shows the actual decision and why it permits or prevents ending the turn.
Start, completed and waiting use host-visible output without waking Main;
only actionable returns work to Main. Waiting does not mean the task is complete.
Errors remain visible hook failures. Private logs alone do not satisfy this
feedback; disabled hooks do not claim execution.

Ordinary children and the checker itself do not run Main's finalize hook.
This task-state check does not add automatic code Review or another task ledger.
Verify actual host behavior after adopting a fixed installation and report only
observable context, effective configuration and optional cache-usage evidence.

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
