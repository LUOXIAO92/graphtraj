---
name: to-tickets
description: Turn software task nodes produced by task-breakdown into deliverable code tickets and publish them to the configured tracker, preserving goals, completion criteria and dependencies. Depends on task-breakdown for task decomposition; this skill handles ticketing.
disable-model-invocation: true
---

# To Tickets

Issue code tickets from the accepted task nodes. Each ticket delivers a complete
software behavior and retains its source node's goal, constraints, completion
criteria and blocking dependencies. Task decomposition depends on
`task-breakdown`. Reuse its available guidance and valid results; use it to fill
missing decomposition or revise task boundaries when needed. Ticketing an existing
breakdown does not require rereading the skill or repeating that work. A tracker
Issue can represent a node of any domain.

The issue tracker and triage label vocabulary should have been provided to you — run `/setup-project` if not.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, an issue number or URL) as an argument, fetch it and read its full body and comments.

Read the current project graph and delivered results. Retain required completed
predecessors when issuing follow-up tickets; they do not block readiness. Put
other origins in the source-node description rather than inventing wait edges.

Map the supplied task nodes before slicing. A fine enough code node becomes one
ticket directly. A coarse code node may need several tickets with internal
dependencies; connect its prerequisites and consumers to the tickets that
actually supply or require those results. Record the source node in each ticket.
A general node remains general even when tracked by an Issue.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Include necessary prefactoring inside the ticket whose behavior it enables.
A standalone refactor ticket needs its own independently verifiable outcome.

### 3. Draft vertical slices

Break the work into **tracer bullet** tickets.

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests) — vertical, NOT a horizontal slice of one layer
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Preserve source-node acceptance and include the internal steps needed for it

</vertical-slice-rules>

Check the proposed tickets together against the accepted breakdown. Inspect
changes to shared behavior, interfaces, installation configuration and test setup.
Assign each common prerequisite once; consumers start from its integrated result
instead of independently patching the same missing foundation. Keep changes that
must be coordinated within one behavior in the same ticket. Preserve genuinely
independent work rather than splitting by file or cleanup category alone.

Give each ticket its **blocking edges**, naming the result each predecessor
supplies. A ticket with no blockers can start immediately.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change — rename a column, retype a shared symbol — whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. Explain why independent vertical changes cannot stay green before choosing this exception. Keep non-deliverable intermediate steps within one ticket.

Before publishing each concrete code ticket, read
[the coding-budget reference](../task-delivery/references/coding-budget.md).
Assess difficulty, Engineer tier and execution budget with reasons, and put the
YAML front matter at the very start of the ticket. Resolve unknown scope before
claiming a usable budget; retain uncertainty as explanation. Keep the existing
source node and real dependencies.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behaviour this ticket makes work

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct — does each ticket only depend on tickets that genuinely gate it?
- Should any tickets be merged or split further?

Resolve unsettled product choices with the user. Apply already accepted node
boundaries and the project's authority for product-preserving graph corrections
without requesting the same decision again.

### 5. Publish the tickets to the configured tracker

Publish the accepted tickets when tracker writes are authorized. **How** depends on the tracker `/setup-project` configured — the tickets are the same either way, only the shape of the blocking edges changes:

- **Local files** → write one file per ticket under `docs/agents/issues/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` in dependency order (blockers first). Each file's "Blocked by" lists the numbers/titles it depends on. Use the per-ticket file template below — one ticket per file, never a single combined file.
- **A real issue tracker (GitHub, Linear, …)** → publish one issue per ticket in dependency order (blockers first) so each ticket's blocking edges can reference real identifiers. Use the platform's native blocking / sub-issue relationship where it has one; otherwise set each ticket's "Blocked by" to the blocking issues. Apply the `ready-for-agent` triage label unless instructed otherwise — the tickets are agent-grabbable by construction.

Work the **frontier**: any ticket whose blockers are all done. For a purely linear chain that means top to bottom.

Do NOT close or modify any parent issue.

<local-ticket-template>

<YAML front matter from the coding-budget reference>

# <NN> — <Ticket title>

**Source task node:** the accepted node this ticket delivers or refines.

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective — not a layer-by-layer implementation list.

**Blocked by:** the numbers/titles of the tickets that gate this one, or "None — can start immediately".

**Status:** ready-for-agent

- [ ] Acceptance criterion 1
- [ ] Acceptance criterion 2

</local-ticket-template>

<issue-template>

<YAML front matter from the coding-budget reference>

## Parent

A reference to the parent issue on the tracker (if the source was an existing issue, otherwise omit this section).

## Source task node

The accepted task node this ticket delivers or refines.

## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective — not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- A reference to each blocking ticket, or "None — can start immediately".

</issue-template>

In either form, avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.
