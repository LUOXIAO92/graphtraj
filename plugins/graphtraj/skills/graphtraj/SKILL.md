---
name: graphtraj
description: Use GraphTraj to plan task dependencies, coordinate execution and follow retained results and traces in a user-owned project.
---

# GraphTraj

GraphTraj connects tasks through the results they need and retains the execution
history. Use the `agents` MCP entry for cross-Runtime Agent control and `tasks`
for GraphTraj task management and delivery. Discover the feature matching the
current need, then describe it to obtain its readable guide reference;
read the referenced file when needed. To request parameters, send describe with
`schema: true`, which returns only that feature's input schema.

Execute an operation using its returned schema and the existing authorization.
A method can provide guidance without an executable action. Previously known
operations do not require a fresh discovery call before every use.

For CLI use, start with the relevant command's `--help`; its guide and parameter
information come from the same feature definition. The host supplies the actual
project and caller context for tools. Follow that project's task, resource and
permission choices.
