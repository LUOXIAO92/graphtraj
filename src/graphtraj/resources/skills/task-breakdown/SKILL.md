---
name: task-breakdown
description: Break a goal into independently verifiable task nodes with deliverables, completion criteria and real dependencies. Use for planning work of any domain or granularity.
---

# Task Breakdown

Start from the agreed goal, constraints and evidence of completion. Read the
existing decisions, task graph and delivered results before splitting anything.
Extend that project history: identify the results or observed problems each new
node builds on. Resolve a missing
fact from available evidence; ask only when it changes the intended result.

## Find the useful boundaries

Work backward from the final result: what must exist to demonstrate success,
and what inputs does each result actually need? Each node should leave an
outcome that a user or its next consumer can inspect, use or falsify on its own.
Keep the internal operations needed for that outcome together.

Choose granularity to suit the work and available context. A complete result
that fits one assignment stays one node, even if it uses several methods or
files. Split a larger result only where the new nodes still have observable
completion criteria. If an unresolved fact determines the route, make the
investigation or experiment a node with a question and evidence to resolve it.

For each node state:

- The result and its intended consumer.
- Completion criteria and the evidence that would establish them.
- Constraints and required inputs inherited from the goal.
- Required predecessors, with the input each predecessor supplies.
- Other source results or observations that explain why the node exists.

An edge records a required predecessor result, including one already delivered.
Its completion removes the wait, not the relationship. Record other origins in
the node description; chronology alone does not create a blocking edge. This is
a result dependency, not a preferred work order. Shared files and possible merge conflicts do not create
dependencies. Check cycles and keep independent work available concurrently.

## Check the graph

Trace each goal requirement to a node's completion criteria. Look for missing
outcomes, duplicated work and steps that produce nothing useful alone. Merge,
remove or split those nodes while preserving the intended result.

Task types can differ across an edge. Make the handoff concrete enough that
the consumer can use the result and judge its limitations. A node may already
be as small as its eventual task ticket; an extra stage or child graph adds
value only when more decomposition is actually needed.

Present the nodes and dependencies in the project's existing format. State
remaining uncertainties and resolve changes to the product goal with the user.
Keep ticket publication and execution within their separately authorized scope.
