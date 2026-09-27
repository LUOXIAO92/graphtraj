---
name: task-breakdown
description: Break an agreed goal into independently verifiable tasks, recursively sizing them for available resources and connecting the results each task needs.
---

# Task Breakdown

Read the agreed goal, constraints, existing graph and retained results. Separate
user requirements from proposals and implementation choices. Reuse established
findings; investigate a missing fact when it changes the decomposition.

## Work backward from results

Identify the final observable outcome and the inputs needed to establish it.
Each node needs a result its user or next consumer can inspect, use or falsify.
Keep the operations necessary for one independently useful result together.

For each node record its result and consumer, scope and exclusions, completion
criteria, investigation findings and remaining uncertainties. Include relevant
locations, reusable evidence, inherited constraints and each required input.
Distinguish required predecessor results from background sources or chronology.
A dependency does not transfer the consumer's acceptance criteria upstream.

## Recurse to fit available resources

Assess the resources actually available: permitted executors and their observed
capabilities, context, time, cost, concurrency and the effort of combining work.
A model mentioned as an example is not an available preset. Preserve the user's
resource choices; model names alone do not establish capability.

For every proposed assignment ask whether it still contains separable results
that would be better handled independently by the available executors. If so,
repeat the decomposition on that node, connect its real inputs and outputs, and
check the resulting children together. One level of splitting is not a stopping
condition. Stop when the executor can complete and verify the scoped result
with its available resources, and further splitting adds coordination or
integration cost without a useful independent outcome.

Distinguish a large collection of simpler work from intrinsically difficult
reasoning. Several independent modules may suit smaller assignments; a hard
proof, integral or algorithm may still need a stronger specialist after all
useful decomposition. Artificially splitting that reasoning does not lower its
difficulty. If no available resource can handle the remaining core, report the
specific resource gap rather than silently assigning an unsuitable executor.

For the same multi-part goal:

- With a capable executor and ample context/time, keep coherent larger results.
- With a smaller local model, separate more bounded results, supply clear inputs
  and completion evidence, and retain a task that combines the needed outputs.
- With mixed or fast models, judge the actual task and available evidence; use
  smaller executors for bounded work and stronger ones for irreducible reasoning
  or difficult integration. There is no fixed model-tier or recursion-depth table.

For example, a software feature with many modules can be decomposed into small
module behaviors for several inexpensive coders, with a coordinator, conflict
resolver and two review axes when the project chooses that method. These are
optional task-specific roles. A researcher may instead complete a task alone.
The organization tree records who can dispatch whom; the task DAG records
required results. Neither graph determines the other, and task decomposition
does not override configured dispatch depth or permissions.

## Draw only required result dependencies

For each edge A → C, name the result C directly needs from A. Check whether an
intermediate B actually includes that result in the form C needs. A path from
A through B to C alone neither proves nor disproves the direct edge. Inspect
the deliverables, not just the ancestry of commits or the order of execution.

**Positive example — independently produced paper summaries.** A reads paper 1,
summarizes it and finds links to papers 2, 3 and 4. B consumes those links and
summarizes papers 2–4. C explains paper 1 and its relationship to those papers.
B's deliverable contains only its own summaries, so C needs A's paper-1 summary
as well as B's summaries. All three edges are necessary:

```mermaid
flowchart LR
  A["A: paper 1 summary + links to 2–4"] --> B["B: independent summaries of 2–4"]
  B --> C["C: synthesis of paper 1 and its references"]
  A --> C
```

**Negative example — the needed result is already included.** A produces the
same paper-1 summary and links. B delivers a complete collection containing the
paper-1 summary, summaries 2–4 and the source references C needs. C consumes
that collection. A → B → C suffices: another A → C edge contributes no required
input. If B merely points to A's separate file, that file remains an independent
input; a reference is not the file's inclusion in B's deliverable.

The same distinction applies to implementation: if task 167 needs task 163,
and task 169 needs both 167's fix and 163's independent report, retain
163 → 169 alongside 163 → 167 → 169. If 167 contains every result from 163 that
169 actually needs, omit the redundant direct edge. Merging code does not by
itself establish that a separate report was included. Never apply automatic
transitive reduction as a substitute for checking the required artifacts.

A completed predecessor remains a dependency but no longer blocks readiness.
Shared files, dispatch order and provenance alone do not create blocking edges.
When shared behavior requires a common prerequisite, assign that result once
and connect its consumers. Keep genuinely independent work available in parallel.

## Check and deliver the graph

Trace every accepted requirement to completion criteria. Check cycles, missing
inputs, duplicated results and supposedly parallel nodes with incompatible
assumptions. Resolve a known prerequisite gap before dispatching its consumers.
Reuse the existing graph format and evidence records; a new edge schema or
artifact ledger is unnecessary to explain a required input.

When delivery evidence changes a boundary, revise affected nodes and edges while
preserving useful results, stable identities and original inputs elsewhere.
Record the cause. Product-preserving details belong to the executor; unresolved
changes to the promised outcome or authority return to the user.

Present the nodes, dependency reasons, resource assumptions and remaining
uncertainties. Publish tickets and execute only within the user's authorization.
