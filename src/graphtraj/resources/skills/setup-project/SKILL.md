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

Use the conversation and existing project guidance to identify the work,
selected roles, professional Skills and validation responsibilities. Ask only
for an actual missing choice. Git and a repository do not imply coding work;
Markdown, LaTeX and software can use the same task lifecycle.

Select resources for the actual task through the existing project setup and
role/Skill selection interfaces. Preserve existing models, connections and
role definitions. A task can use one researcher or engineer; its content does
not require a coordinator, reviewer or state-maintenance role.

For programming work, offer the relevant implementation, test and review
methods. Read [coding setup](references/coding.md) when configuring a selected
coding method. Record agreed responsibilities; programming alone does not
select the coding-team arrangement.

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
Make the project-selected responsibilities accessible to their executors; do not
assume a delegated Agent can read guidance above its working directory.

Keep one Agent skills section with brief pointers to the tracker, domain
documents and, when used, triage labels. Reuse the section if it exists. Include
only the selected domain guidance. Keep the rest of the user's files intact.

Check that each pointer resolves and the resulting documents match the user's
answers. Report the files changed and any unanswered configuration choice.
