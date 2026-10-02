---
name: graphtraj
description: Use GraphTraj to plan task dependencies, coordinate execution and follow retained results and traces in a user-owned project.
---

# GraphTraj

GraphTraj connects tasks through the results they need and retains the execution
history. Use the available `graphtraj` tool to discover the feature matching the
current need. Describe that feature to obtain its readable guide reference;
read the referenced file when needed. To request parameters, send describe with
`schema: true`, which returns only that feature's input schema.

Execute an operation using its returned schema and the existing authorization.
A method can provide guidance without an executable action. Previously known
operations do not require a fresh discovery call before every use.

For CLI use, start with the relevant command's `--help`; its guide and parameter
information come from the same feature definition. The host supplies the actual
project and caller context for tools. Follow that project's task, resource and
permission choices.
