---
name: to-tasks
description: Register accepted software task nodes produced by task-breakdown, preserving goals, completion criteria and dependencies. Depends on task-breakdown for decomposition.
disable-model-invocation: true
---

# To Tasks

Register code tasks from the accepted task nodes. Each task delivers a complete
software behavior and retains its source node's goal, constraints, completion
criteria and blocking dependencies. Task decomposition depends on
`task-breakdown`. Reuse its available guidance and valid results; use it to fill
missing decomposition or revise task boundaries when needed. Registering an existing
breakdown does not require rereading the skill or repeating that work. A tracker
Issue can represent a node of any domain.
For a delivery-driven revision, change only affected nodes and dependencies;
reuse existing local Task identities rather than republishing the graph.

The issue tracker and triage label vocabulary should have been provided to you — run `/setup-project` if not.

## Process

### 1. Gather context

Work from the available conversation and accepted sources. Fetch referenced
specs or Issues when their contents are missing or changed; reuse material
already read, fetching only relevant new comments or revisions.

Read the current project graph and delivered results. Retain required completed
predecessors when issuing follow-up tasks; they do not block readiness. Put
other origins in the source-node description rather than inventing wait edges.

Map the supplied task nodes before slicing. A fine enough code node becomes one
task directly. A coarse code node may need several tasks with internal
dependencies; connect its prerequisites and consumers to the tasks that
actually supply or require those results. Record the source node in each task.
A general node remains general even when tracked by an Issue.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Task titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Include necessary prefactoring inside the task whose behavior it enables.
A standalone refactor task needs its own independently verifiable outcome.

### 3. Draft vertical slices

Break the work into **tracer bullet** tasks.

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests) — vertical, NOT a horizontal slice of one layer
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Preserve source-node acceptance and include the internal steps needed for it

</vertical-slice-rules>

Check the proposed tasks together against the accepted breakdown. Inspect
changes to shared behavior, interfaces, installation configuration and test setup.
Assign each common prerequisite once; consumers start from its integrated result
instead of independently patching the same missing foundation. Keep changes that
must be coordinated within one behavior in the same task. Preserve genuinely
independent work rather than splitting by file or cleanup category alone.

Give each task its **blocking edges**, naming the result each predecessor
supplies. A task with no blockers can start immediately.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change — rename a column, retype a shared symbol — whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own task blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a task blocked by every migrate batch. Explain why independent vertical changes cannot stay green before choosing this exception. Keep non-deliverable intermediate steps within one task.

Before publishing each concrete code task, read
[the coding-budget reference](references/coding-budget.md).
Assess difficulty and execution budget with reasons, and put the
YAML front matter at the very start of the task. Resolve unknown scope before
claiming a usable budget; retain uncertainty as explanation. Keep the existing
source node and real dependencies.

### 4. Resolve remaining choices

Present the proposed breakdown as a numbered list. For each task, show:

- **Title**: short descriptive name
- **Blocked by**: which other tasks (if any) must complete first
- **What it delivers**: the end-to-end behaviour this task makes work

Ask only about unsettled product choices or boundaries the current authority
does not resolve. Apply accepted granularity, real dependencies and authorized
product-preserving corrections without requesting the same decision again.

### 5. Register the accepted tasks

For a GraphTraj project, use its public `task_register` and `task_revise`
operations in dependency order. Read their current schemas and provide complete
definitions, including the local parent and dependency IDs. Keep local task
state authoritative; a remote Issue number is a separate reference, never a
replacement for the local ID. Remote backup follows the project's configured
adapter and authorization, separately from registration. Do not create a second
task ledger in documentation or modify private state files.

If adapting this sample to another task system, use that system's configured
registration entry and preserve the same scope and dependency meaning. The
templates below describe task content, not a required storage layout.

When execution is authorized, hand the accepted graph and publication results
to [task-delivery](../../../manuals/task-delivery/guide.md), reusing its current context.
It owns readiness, dispatch, event handling and recovery; registration does not
start another monitoring loop. Apply any user pause or stop-after instruction.

Do NOT close or modify any parent issue.

<local-task-template>

<YAML front matter from the coding-budget reference>

# <NN> — <Task title>

**Source task node:** the accepted node this task delivers or refines.

**What to build:** the end-to-end behaviour this task makes work, from the user's perspective — not a layer-by-layer implementation list.

**Blocked by:** the numbers/titles of the tasks that gate this one, or "None — can start immediately".

**Status:** ready-for-agent

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2

</local-task-template>

<issue-template>

<YAML front matter from the coding-budget reference>

## Parent

A reference to the parent issue on the tracker (if the source was an existing issue, otherwise omit this section).

## Source task node

The accepted task node this task delivers or refines.

## What to build

The end-to-end behaviour this task makes work, from the user's perspective — not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- A reference to each blocking task, or "None — can start immediately".

</issue-template>

In either form, avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.
