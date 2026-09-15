# Coding setup

Use this reference only when the project includes programming work.

Record that maintained modules, interfaces and cross-module changes use the
project's coding team and engineering skills. Auxiliary data conversion,
plotting and one-off calculations can be done directly; writing a function or
using a programming language does not call for a Team. This does not change
who executes tests.

Write the following rule into the project's `AGENTS.md` (or its existing
`CLAUDE.md` guidance), rather than leaving it only in this setup procedure:

> For projects that include programming work, Main and Team Leaders must not
> execute any tests, during setup or later delivery. This includes baseline,
> regression, smoke, installation and integration tests, and validation probes;
> wrappers and integration commands do not provide an exception. Engineers run
> tests and report the candidate, environment and results. Main assigns shared
> validation and ensures reuse of valid evidence; Leaders define the Ticket's
> needed checks and assess the returned evidence. Main and Leaders inspect
> evidence and make delivery decisions without running tests themselves.
> Existing independent Reviewer responsibilities remain unchanged.

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
its Engineer and Standards/Spec code reviews. Configure the installed role
presets through their documented interface, preserving user Runtime settings.

Keep the setup procedure in this reference. Add the test-execution rule above
and the project-specific pointers to guidance. Shared tracker and triage
configuration remains in the parent skill. Keep pull requests out of the request
queue unless the project has explicitly selected them as a request surface.

For coding projects, retain the provider's request-surface setting. Read only
the configured provider's instructions: [GitHub](github-requests.md) or
[GitLab](gitlab-requests.md). Include its default-off flag in the tracker
binding; include the operational details only when that surface is enabled.
