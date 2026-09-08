---
name: setup-project
description: Configure a project's task tracker, shared vocabulary and decision documents, and identify which kinds of work it includes.
disable-model-invocation: true
---

# Setup Project

Read the project's existing guidance, document locations, tracker conventions
and remote before proposing configuration. Preserve established choices and
existing content. Within a Harness Project, Main writes Project Documents at
the Harness Project Root; delegated Worktree views remain read-only.

## Establish the work

Unless the current conversation already answers it, explicitly ask:

> Does this project include work that needs software engineering delivery,
> such as module and interface design, coordination across modules, or
> implementation that will be maintained over time?

The presence of a repository or some scripts does not answer this question.
Small helper scripts stay with the current Agent and receive proportionate
validation. A project-wide yes still requires choosing the workflow for each
task. Record the answer in the project guidance's Agent skills section.

Only for an affirmative answer, read [coding setup](references/coding.md).

## Configure shared conventions

- **Task tracker:** use an established binding, or ask where this project's
  tasks should live. A remote can suggest a provider; it does not decide for
  the user. Read only the selected template:
  [GitHub](issue-tracker-github.md), [GitLab](issue-tracker-gitlab.md), or
  [local Markdown](issue-tracker-local.md). For another provider, record its
  actual workflow. Save the binding in `docs/agents/issue-tracker.md`.
- **Triage:** if the project uses the `triage` skill, ask whether to retain
  its default labels, then use [the label template](triage-labels.md).
  Reuse existing label mappings where already decided.
- **Domain documents:** read [the consumer rules](domain.md). Preserve an
  existing context map; otherwise use one shared glossary and decision
  directory. Create content only when there are resolved terms or decisions.

Issue identities and dependency edges can represent any task's file-based
results. Git, branches and integration remain useful across task types.

## Write and verify

Present the concrete configuration and resolve missing choices before writing.
Apply authorized edits; existing authorization needs no second confirmation.
Within a Harness Project update its root `AGENTS.md`. Else update the existing
`CLAUDE.md` or `AGENTS.md`; if neither exists, ask which guidance file to create.

Keep one Agent skills section with brief pointers to the tracker, domain
documents and, when used, triage labels. Reuse the section if it exists. Include
only the selected domain guidance. Keep the rest of the user's files intact.

Check that each pointer resolves and the resulting documents match the user's
answers. Report the files changed and any unanswered configuration choice.
