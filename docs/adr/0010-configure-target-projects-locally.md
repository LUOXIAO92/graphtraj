---
status: accepted
---

# Configure Harness Projects locally and interactively

> **Partial supersession:** [ADR 0013](0013-own-runtime-resources-at-the-harness-root.md)
> replaces Integration-owned Runtime placement, while
> [ADR 0015](0015-select-repository-skills-explicitly.md) replaces the missing-
> Skill prompt and installation destination. The single interactive setup,
> complete preflight, conflict refusal, idempotence, and failure-reporting
> decisions remain accepted.

After host installation, the operator runs
`you-are-a-product-architect setup` from the Harness Project Root defined in
[ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md) and identifies
the Source Repository through its existing Primary Worktree child, using the
operator-chosen directory name.
V1 setup does not clone the repository. It is an interactive Click workflow;
it does not offer a non-interactive mode that guesses the repository, Skill
installation choices, integration-branch confirmation, or conflict handling.

One setup invocation first creates or registers `dev` and its Integration
Worktree, then writes reviewable Runtime resources into that Worktree using
repository-relative native paths. For Codex V1 these include
`.codex/config.toml`, `.codex/agents/`, and `.codex/hooks/`; locally installed
Skills use `.agents/skills/`. Setup never writes these files into the primary
`main` Worktree. The operator reviews and commits them on `dev`, after which
Ticket Worktrees inherit the same role, Skill, and isolation configuration.
Setup does not commit for the operator and does not require a second successful
invocation merely to finish initialization.

Before the first Engineer dispatch, Runner preflight requires a clean
Integration Worktree and verifies that the selected Adapter's required
repository resources are available from the committed `dev` state. This keeps
an uncommitted setup result from producing Ticket Worktrees that silently lack
their Runtime configuration.

Setup does not write to `${HOME}/.codex`, create global profiles, alter
credentials or user defaults, or silently trust a project. If a Runtime
requires project trust, the operator grants it through that Runtime's normal
user-controlled trust flow.

Codex project config uses `workspace-write` and names the stable Worktree-local
`.scratch` path in `sandbox_workspace_write.writable_roots`. Setup creates the
Integration Worktree's ignored `.scratch` symlink to the external Harness State
Directory and verifies that it resolves to the registered writable location.
It also creates and validates the machine-local Project Runner Config and
`worktree_root` described in [ADR 0007](0007-hide-runtime-cli-details-behind-adapters.md),
and establishes `dev` and its Integration Worktree according to
[ADR 0009](0009-integrate-ticket-worktrees-through-dev.md).

Before changing anything, setup runs the Skill check from
[ADR 0011](0011-resolve-core-skills-by-name.md) and preflights every target
file and resource. An absent file may be created and an identical file is
already configured. If any target exists with different content, setup aborts
before creating the branch or Worktree and before every planned write; V1 never
merges or overwrites the conflict. Setup can inspect an existing `dev` tree or
the operator-confirmed base tree through Git before materializing the
Integration Worktree. The operator resolves a conflict and reruns setup.

For that Skill check, setup supplies the Integration Worktree context it has
selected and preflighted, whether the Worktree is already registered or is
about to be materialized. The shared checker also includes Skills discoverable
from the selected Runtime's user scope. It does not treat the Harness Project
Root or Primary Worktree as a substitute project-local Runtime context.

Setup preflights every condition that can safely be checked before mutation,
but it does not claim transactional rollback across filesystem and Git
operations. Operations are idempotent. An execution-time failure reports which
actions completed and which did not, allowing correction and rerun.

Machine-local paths, executable bindings, and Runner session mappings stay
under the selected Source Repository's `<git-common-dir>/agent-runner/`,
outside committed Runtime configuration. The Runner is a shared host tool, not
something installed into an Agent profile.

Repository engineering metadata remains owned by
`setup-matt-pocock-skills`. Product setup neither creates nor updates
`AGENTS.md` or `docs/agents/`, and it never invokes that Skill or starts an LLM.
After setup, it tells the operator to invoke the Skill separately if tracker
binding, triage labels, domain documentation, or repository instructions are
still needed.

V1 installs resources only for the Codex Adapter. A future Runtime Adapter must
use its own project-local configuration rather than reuse or pollute Codex
files.
