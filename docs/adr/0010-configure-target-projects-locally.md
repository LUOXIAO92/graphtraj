---
status: accepted
---

# Configure Harness Projects locally and interactively

After host installation, the operator runs
`you-are-a-product-architect setup` from the Harness Project Root defined in
[ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md). The Source
Repository is its `repo/` child. V1 setup is an interactive Click workflow; it
does not offer a non-interactive mode that guesses Skill-install choices,
integration-branch confirmation, or conflict handling.

The selected Runtime Adapter writes reviewable resources into the Runtime's
native layout within the Source Repository. For Codex V1 this includes
`repo/.codex/config.toml`, `repo/.codex/agents/`, and `repo/.codex/hooks/`.
These files are intended to be reviewed and committed so `dev`-derived
Integration and Ticket Worktrees inherit the same role and isolation
configuration. Setup does not write to `${HOME}/.codex`, create global
profiles, alter credentials or user defaults, or silently trust a project.

Codex project config uses `workspace-write` and names the stable Worktree-local
`.scratch` path in `sandbox_workspace_write.writable_roots`. Setup creates the
Integration Worktree's ignored `.scratch` symlink to the external Harness State
Directory and verifies that it resolves to the registered writable location.
It also creates and validates the machine-local Project Runner Config and
`worktree_root` described in [ADR 0007](0007-hide-runtime-cli-details-behind-adapters.md),
and establishes `dev` and its Integration Worktree according to
[ADR 0009](0009-integrate-ticket-worktrees-through-dev.md).

Before changing files, setup runs the Skill check from
[ADR 0011](0011-resolve-core-skills-by-name.md) and preflights every target
file and resource. An absent file may be created and an identical file is
already configured. If any target exists with different content, setup aborts
before every planned write; V1 never merges or overwrites the conflict. The
operator resolves it and reruns setup.

Setup preflights every condition that can safely be checked before mutation,
but it does not claim transactional rollback across filesystem and Git
operations. Operations are idempotent. An execution-time failure reports which
actions completed and which did not, allowing correction and rerun.

Machine-local paths, executable bindings, and Runner session mappings stay
under `<git-common-dir>/agent-runner/`, outside committed Runtime configuration.
The Runner is a shared host tool, not something installed into an Agent
profile.

Repository engineering metadata remains owned by
`setup-matt-pocock-skills`. Product setup neither creates nor updates
`AGENTS.md` or `docs/agents/`, and it never invokes that Skill or starts an LLM.
After setup, it tells the operator to invoke the Skill separately if tracker
binding, triage labels, domain documentation, or repository instructions are
still needed.

V1 installs resources only for the Codex Adapter. A future Runtime Adapter must
use its own project-local configuration rather than reuse or pollute Codex
files.
