# Coding setup

Use this reference only when the project includes engineering delivery.

Record that maintained modules, interfaces and cross-module changes use the
project's coding team and engineering skills. Auxiliary data conversion,
plotting and one-off calculations can be done directly with suitable checks;
writing a function or using a programming language does not call for a Team.

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

Add only these project-specific pointers to guidance; keep this procedure in
the reference. Shared tracker and triage configuration remains in the parent
skill. Keep pull requests out of the request queue unless the project has
explicitly selected them as a request surface.

For coding projects, retain the provider's request-surface setting. Read only
the configured provider's instructions: [GitHub](github-requests.md) or
[GitLab](gitlab-requests.md). Include its default-off flag in the tracker
binding; include the operational details only when that surface is enabled.
