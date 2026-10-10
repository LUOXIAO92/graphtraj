---
name: setup-project
description: Establish a project's GraphTraj paths, task tracker, available execution resources and shared conventions while preserving existing choices.
---

# Setup Project

Read the project's existing guidance, layout, Runtime settings, tracker binding
and relevant decisions. Reuse choices already established by the user. A Git
repository can manage Markdown, LaTeX, data or software results; its presence
does not classify the work or select professional methods.

## Establish only missing configuration

Identify the Harness Project Root, Source Repository, document location and
existing GraphTraj configuration. Use the installed `graphtraj` command help
for its setup and doctor options. Preserve established layouts and user files;
initialization does not require or install a fixed set of Skills.

Resolve missing choices that change project behavior or access. Ordinary path
and wording details can follow existing conventions. Do not ask an answered
question again or make an optional preference a prerequisite for setup.

- **Tracker:** retain the project's existing binding. If absent, establish where
  the user wants tasks and dependencies recorded; a remote suggests a provider
  but does not choose it. Record its actual creation, update and lookup workflow
  using the selected tool or local-file convention. Keep stable task identities,
  completion criteria and artifact dependencies. Native dependency links are
  useful where supported; readable input references suffice otherwise.
- **Execution resources:** preserve the user's models, providers, permissions,
  budgets and Runtime settings. Record the roles and allowed dispatch tree the
  user actually selects, including a single participant when appropriate. No
  leader, coder, reviewer or dedicated acceptance role is universally required.
- **Instructions and Skills:** reference selected external role instructions and
  use the Runtime's supported Skill discovery or explicit selection. GraphTraj's
  general methods may be selected independently. Professional methods are the
  user's optional resources, not a catalog this setup installs or routes by
  domain. Keep content selection separate from the task completion protocol.
- **Shared language:** follow existing glossary and decision locations. Use
  [concept-clarification](../concept-clarification/guide.md) when a real term or
  relationship needs clarification. A missing glossary alone is not a problem;
  create records only for content the work actually needs.
- **Project conventions:** preserve document ownership, result locations,
  acceptance responsibilities and tracker labels. Establish missing conventions
  needed by this project without introducing a standard team or review process.

## Share Runtime connections across projects

Use `graphtraj connections` or the `runtime_connections` tool to read, preview,
save or discover the user catalog at `${HOME}/.graphtraj/connections.yml`.
The desktop settings operation uses the same interface with `scope: user`.
Consult command help or the selected tool schema for the complete fields.

The catalog has `version: 1` and a `runtimes` mapping. Each named entry selects
`runtime` (`codex`, `pi` or `dsh`), an optional absolute `home`, and `providers`.
Providers share that Home and contain `models`, with optional `base_url` and
`api_key_env`. A model entry has its native `id`, `source` (`native` or `manual`),
and optional display `alias` and `supported_efforts`.

Authenticate in the original Runtime. Discovery queries its public metadata
without inference; a listed model is not proof of account access or available
credit. Manual connections take environment variable names, never key values.
Custom Pi providers also select their supported `api`; extension-only routes
whose destination cannot be resolved report unsupported. Explicit Pi key
overrides use native key precedence while preserving shared Home files.

Project roles can select `connection: runtime-name/provider-name/model-key`
instead of inline Runtime/model/connection fields, and choose a separate
`reasoning_effort` from the model's supported values. Existing inline roles
remain valid. Convert only the roles the user chooses; retain their other fields.
Fresh dispatch captures the resolved connection and revision. Resume uses that
captured routing, even if the catalog later changes. Use its connection
provenance to identify the provider rather than a Runtime's internal label.

Read the current catalog and revision before editing, preview the complete
draft, then save with that `expected_revision` through native host review.
Denied review or a changed revision leaves the original catalog intact.
Saving configuration does not start, stop or reconfigure existing Agents.

## Apply and check

Apply authorized configuration and guidance changes using existing project
locations and permissions. Keep concise pointers to the selected tracker,
resources and shared vocabulary rather than duplicating their contents into
multiple files. Preserve unrelated content and native Runtime configuration.

Check configured paths and reference targets, and use the installed project's
configuration diagnostics through the authorized executor. Absence of bundled
Skills does not invalidate a project; malformed settings or inaccessible paths
still need correction. Report the actual changes, successful checks and any
unresolved configuration choices. File creation alone does not demonstrate that
an Agent can execute under the chosen Runtime and permissions.
