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

> Does this project include programming work, whether maintained software or
> auxiliary scripts?

A repository alone does not answer this question.
Small helper scripts can stay with the current Agent; test execution follows
the project's responsibility rule below. A project-wide yes still requires
choosing the workflow for each task. Record the answer in the project guidance's
Agent skills section.

When the project includes programming work, Main does not run tests. Engineers
may run development tests; the Leader alone owns test acceptance and any
still-needed acceptance checks. Reviewers never run tests or probes. Record
these responsibilities in the project guidance using
[coding setup](references/coding.md), before any setup baseline or validation
probe. Read that reference only when the answer is affirmative.

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
For programming projects, also place the test-execution rule in the Source
Repository and existing Worktrees as described in the coding reference; do not
assume a delegated Agent can read guidance above its working directory.

Keep one Agent skills section with brief pointers to the tracker, domain
documents and, when used, triage labels. Reuse the section if it exists. Include
only the selected domain guidance. Keep the rest of the user's files intact.

Check that each pointer resolves and the resulting documents match the user's
answers. Report the files changed and any unanswered configuration choice.
