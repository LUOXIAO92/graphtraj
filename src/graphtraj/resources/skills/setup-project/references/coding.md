# Coding setup

Use this reference only when the project includes programming work.

Record that maintained modules, interfaces and cross-module changes use the
project's coding team. Main gives each Ticket a scope and its investigation
findings; the Leader assesses difficulty and scope before choosing methods.
Small fixes and test modifications do not use TDD or code-review Skills; each
Review axis runs at most once per Ticket. Auxiliary data conversion,
plotting and one-off calculations can be done directly; writing a function or
using a programming language does not call for a Team. This does not change
who executes tests.

Write the following rule into the project's `AGENTS.md` (or its existing
`CLAUDE.md` guidance), rather than leaving it only in this setup procedure:

> Main does not run tests. Engineers may run development tests and report the
> candidate, environment, commands and results. The Leader is the sole
> test-acceptance role and executes any acceptance checks still needed, reusing
> valid development evidence. Code Reviewers must not run tests or probes,
> including through wrappers or temporary installations.
> Reviewers use controlled read-only queries and write their evidence reports;
> they do not execute project code, builds or installs or modify candidates.
> Every Agent communicates only with its direct parent and direct children.
> Cross-level observation is limited to status summaries. The control exception
> is interruption of one's own descendant subtree, not messages or approvals.
> Only a target's direct parent or the user may replace it, after that target
> and all descendants are confirmed stopped.
> Do not wake or relaunch a Leader while its Ticket execution is running.
> Instruction-only changes to prompts, Skills and guidance end with consistency
> checking and a commit where tracked, without tests or Reviewers.

Within a Harness Project, put this rule directly in the Source Repository's
`AGENTS.md` and the `AGENTS.md` of the Integration and existing Ticket Worktrees
as well as the Harness-root guidance. Preserve their other instructions. New
Worktrees inherit the repository file; existing Worktrees need the same update.
Inspect these local files rather than assuming access to a parent directory.

Inspect the software's existing guidance and package structure. Keep one
context unless genuinely separate domain vocabularies warrant a context map.
A monorepo is evidence to inspect, not a requirement for multiple contexts.
Within a Harness Project, all shared context files and ADRs remain owned by
Main at its root, even when the source has several packages.

Point engineering work to the relevant codebase guidance and validation
commands. Use `to-spec` for an agreed software design and `to-tickets` to turn
its task nodes into deliverable code tickets. The coding team's Leader owns
its Engineer, the necessary one-time Review axes and test acceptance. Configure the installed role
presets through their documented interface, preserving user Runtime settings.

Keep the setup procedure in this reference. Add the test-execution rule above
and the project-specific pointers to guidance. Shared tracker and triage
configuration remains in the parent skill. Keep pull requests out of the request
queue unless the project has explicitly selected them as a request surface.

For coding projects, retain the provider's request-surface setting. Read only
the configured provider's instructions: [GitHub](github-requests.md) or
[GitLab](gitlab-requests.md). Include its default-off flag in the tracker
binding; include the operational details only when that surface is enabled.
