---
name: graphtraj
description: Use GraphTraj to plan task dependencies, coordinate execution and follow retained results and traces in a user-owned project.
---

# GraphTraj

Use MCP `agents` / `tasks` for every exposed Agent and Task operation.
Use `agents` for Agent communication, hierarchy, execution and native permission
handling, including members participating in Tasks. Use `tasks` for Task graphs,
participation, scoped member queries and delivery. Independent Agent operations
must work without GraphTraj Tasks or Worldline. Report an installed entry that
violates this boundary as a defect; its presence does not establish ownership.
Discover only the needed feature, describe it for its guide or input schema
(`schema: true`), then execute through the entry that exposes it. Known
operations need no repeated discovery.

Use the corresponding public CLI only when the needed MCP entry is unavailable
or has an observed failure. Retain that failure and limit fallback to the
affected operation, preserving caller identity and native permission checks.
A permission refusal is not authority to switch channels. Return to MCP when
it works; an earlier failure is not a standing CLI preference. Shell-running
a CLI is not an MCP call. Obtain fallback syntax from its current `--help`.

A feature may provide guidance without an executable action. Read its selected
guide and follow the project's requirements, roles, resources and authorization.
The host supplies project and caller context. This workflow introduces no extra
per-call approval role; native permission checks remain effective.
