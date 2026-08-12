---
status: superseded
normative: false
---

> [!IMPORTANT]
> This is a historical pre-split audit source. The recovered decision text
> below is preserved for traceability, but it is not an active ADR and must not
> be used as current design authority. The active decisions are indexed in
> [`docs/adr/README.md`](adr/README.md).

# Distribute you-are-a-product-architect with uv as a Python tool

`you-are-a-product-architect` is distributed as one auditable Python package
rather than through npm or a mixed Node-to-Python launcher. A persistent host
installation uses `uv tool install "git+https://<repository-url>@<tag-or-commit>"`
so the tool has an isolated environment and stable executables without binding
it to a target project's virtual environment; releases should be pinned to a
reviewed tag or commit instead of a moving branch.

The Python distribution is named `you-are-a-product-architect`, its import
package is `you_are_a_product_architect`, and it exposes two console entries:
`you-are-a-product-architect` for explicit setup and configuration, and
`agent-runner` for delivery-time transport. The same distribution carries the
`task-delivery` Skill, shared templates, role definitions, and Runtime-specific
setup resources. V1 implements and verifies the Codex Adapter first; OpenCode
and other Agent Runtime Adapters remain explicit follow-up work behind the same
Adapter seam rather than claimed V1 support. Setup installs resources through
the selected Runtime Adapter; the Runner itself is a shared host tool and is
not installed into an Agent profile.

The host CLI uses Click. V1 setup is an interactive operator workflow; it does
not provide a non-interactive mode that guesses or bypasses the Skill-install
choice, integration-branch confirmation, or conflict handling.

After the host tool is installed, the operator runs
`you-are-a-product-architect setup` from the target Git project. The selected
Runtime Adapter writes its reviewable resources into that Runtime's native
project-local layout: for Codex this includes `.codex/config.toml`,
`.codex/agents/`, and `.codex/hooks/`; a later Adapter must use its Runtime's own
project-local equivalent. These resources are intended to be reviewed and
committed so that `dev`-derived Integration and Ticket Worktrees inherit the
same role and isolation configuration. The Codex project config also enables
`workspace-write` access to the Worktree-local `.scratch` path. Setup connects
that stable path to the registered physical Harness State Directory in the
Integration Worktree and verifies the resolved target, avoiding a
machine-specific absolute path in the committed config. Engineer launches do
not rely on Main to reproduce this setting: the Codex Adapter privately adds
the resolved ticket-evidence directory to each `codex exec` invocation.

Before writing, setup runs the deterministic `doctor` Skill-dependency check.
`doctor` has only this responsibility; Runtime files, Git state, Runner config,
and the Integration Worktree are checked separately by setup preflight and are
not part of `doctor`. The required core Skill names are
`setup-matt-pocock-skills`, `grill-with-docs`, `grilling`, `domain-modeling`,
`to-spec`, `to-tickets`, `task-delivery`, `implement`, `tdd`, `code-review`, and
`resolving-merge-conflicts`. Missing non-core Skills do not make the diagnostic
fail.

The standalone Click `doctor` command prints a human-readable `OK` or `MISSING`
result for each required name. It exits zero only when every core Skill is
discoverable and nonzero otherwise. It has no YAML or other machine-output
mode. Setup reuses the same Python check directly rather than spawning the
command and parsing its presentation.

When a core Skill is missing, the operator may either let setup install the
backed-up supported copy into the target project's `.agents/skills/` directory
or elect to install it at user scope independently. Setup never installs a
Skill globally on the operator's behalf. If the operator elects independent
user-scope installation, setup exits before writing anything, reports the
missing names, and asks the operator to rerun setup after installing them. It
does not hold open a partial setup session while waiting for external
installation.

Setup also preflights every target Runtime file before making any change. It
creates an absent file and treats an identical file as already configured, but
if any target file exists with different content, setup rejects the operation
and writes none of the planned Runtime files. V1 does not merge or overwrite
conflicting Runtime configuration; the operator resolves the conflict and
reruns setup. Preflight covers every condition that can be checked safely before
mutation, but setup does not promise transactional rollback across filesystem
and Git operations. Its operations are idempotent; an execution-time failure
reports completed and incomplete actions so the operator can correct the cause
and rerun it. Setup also does not write to `${HOME}/.codex` or another Runtime's
user-level configuration, create global profiles, modify credentials or user
defaults, or silently mark a project as trusted. A Runtime that requires
project trust must obtain it through its normal user-controlled trust flow.

Machine-local paths, executable bindings, and Runner session mappings remain
outside the committed project configuration under
`<git-common-dir>/agent-runner/`, as defined in ADR 0001. Repository engineering
metadata remains separately owned by `setup-matt-pocock-skills`: this setup does
not create or update `AGENTS.md` or `docs/agents/`. For Codex in particular,
project-local custom-agent files are Runtime resources rather than user-level
profiles; the Codex Adapter still owns the internal translation from Main's
logical role to a top-level `codex exec` launch without exposing paths or Codex
arguments to Main.

Setup installs or verifies `setup-matt-pocock-skills` but never invokes it or
starts an LLM on the operator's behalf. On completion, setup tells the operator
to invoke that Skill separately when the target project still needs its
`AGENTS.md`, tracker binding, triage labels, or domain-document layout.

Role definitions and Harness workflows identify Skill dependencies only by
their declared names. They do not expose Skill paths or source coordinates, and
the Harness does not add target-project Skill lock files, file hashes, content
attestation, or automatic semantic compatibility checks. `doctor` only needs to
verify that the required Skill names are discoverable. Multiple discoverable
Skills with the same name may be resolved differently by different Agent
Runtimes; exhaustive cross-Runtime collision detection is not a V1 priority and
this risk must be documented as a README limitation. A Runtime Adapter may
report a collision when it can observe one, but callers must avoid installing
duplicate names.

These named dependencies are workflow requirements, not per-role Skill
allowlists. V1 does not isolate Skill discovery by role, write path-based
enablement filters, or prevent a role from seeing other Skills made available
by Codex. Main is deliberately unrestricted and may use any available Skill
that helps it interpret user intent or orchestrate the Harness. Engineer role
instructions direct Junior, Senior, and Expert to `implement`, `tdd`, and
`code-review`; the Merge Resolver is directed to
`resolving-merge-conflicts`. Reviewer threads and the Delivery State Agent have
no required Skill. These are developer-instruction responsibilities rather
than Runtime-enforced isolation.

Upstream Skill compatibility remains a maintainer decision rather than Runner
or `doctor` behavior. The maintainer follows upstream changes, reviews whether
new Skill semantics alter the Harness workflow, and keeps backups of multiple
Skill versions. If an upstream dependency is removed, the Harness can continue
to distribute the last compatible backed-up version. Each product release
selects one supported Skill set for project-local installation; setup does not
expose the maintainer's historical backups as a version selector. This manual
governance keeps Skill prompt semantics out of the Python implementation and
preserves the ability to follow upstream quickly without coupling delivery-time
execution to an updater or version-verification system.
