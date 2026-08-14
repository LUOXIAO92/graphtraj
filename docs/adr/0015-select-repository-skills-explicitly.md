---
status: accepted
---

# Select Repository Skills explicitly for Engineer tasks

Harness-installed Skills are canonical resources under
`<harness-project-root>/.codex/skills/`. Main's Harness-root configuration and
Runner-launched roles reference them explicitly with `skills.config`; they are
not copied into the Source Repository or linked Worktrees. Main remains
unrestricted by Engineer role guidance.

Interactive setup asks one user-facing question when supported core Skills are
missing:

> Install the missing Skills into this Harness Project? `[Y/n]`

On yes, setup installs only the missing backed-up supported copies into the
Harness Runtime Store. On no, setup stops before every write, lists the missing
names, tells the operator to install them through the Runtime's user scope,
and asks them to rerun setup. The interface does not expose the former
`project-local` versus `independent` terminology. `doctor` continues to check
only required core Skill names, but evaluates the Harness Runtime Store and
the selected Runtime's user scope rather than the Integration Worktree.

Source Repository Skills under `.agents/skills/` are not automatically trusted
as Engineer capabilities. Runner enumerates the Skills discoverable in the
Ticket Worktree and constructs one explicit per-path `skills.config` result:

- the selected role's required Harness Skills are enabled from the Harness
  Runtime Store;
- Repository Skills are disabled by default;
- Repository Skills selected for the current task are enabled by their exact
  resolved paths; and
- every other discovered Repository Skill remains explicitly disabled.

There are two ways to select a Repository Skill. A user may tell Main to use it
for one task, in which case Main includes its semantic name in that task's
batch object. A persistent Harness Project allowlist permits Main to select a
listed Repository Skill autonomously when a task needs it; allowlisting does
not enable the Skill for every Engineer session. This is a soft-Harness trust
decision: Runner does not require a second authorization token or reproduce
the user's words.

Main passes semantic Skill names, not filesystem paths or raw `skills.config`
fragments. Runner reads `SKILL.md` metadata beneath the Ticket Worktree and
resolves each requested name. A unique name resolves to its canonical path; a
missing or ambiguous name fails preflight and reports the candidates instead
of guessing. The batch input and durable launch evidence record the selected
names and resolved effective Skill set.

Codex exposes per-Skill path enablement rather than a documented directory-wide
allowlist, so enumeration and construction of the final configuration remain
mechanical Adapter work. Codex Adapter acceptance must prove with a real
installed process that an external Harness Skill can be enabled and that an
otherwise discoverable Repository Skill can be disabled for the same
Engineer invocation.

This decision supersedes the Integration-Worktree Skill installation and
discovery context in ADRs 0002, 0010, 0011, and 0012. ADR 0011's name-only core
dependency policy, manual upstream compatibility review, and lack of content
locking remain accepted.

## Considered options

- Enabling every Repository Skill for every Engineer was rejected because
  project-authored convenience Skills should not silently alter all Harness
  roles or consume the initial Skill-list budget.
- Permanently forbidding Repository Skills was rejected because project
  developers may intentionally provide useful domain-specific workflows.
- Asking Main to construct physical paths or Codex CLI syntax was rejected
  because Runtime details belong behind the Adapter boundary.
