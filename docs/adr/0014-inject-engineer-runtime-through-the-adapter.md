---
status: accepted
---

# Inject Engineer Runtime configuration through the Adapter

Main selects an Engineer with a semantic role such as `engineer-senior`; it
does not supply a role file path, Runtime profile, physical Worktree path, or
raw command. Runner resolves the canonical role from the Harness Runtime Store
and the selected Adapter creates the effective Runtime invocation.

For the Codex Adapter, the Ticket Worktree is marked `untrusted` for that
invocation with the equivalent of
`projects.<absolute-worktree-path>.trust_level = "untrusted"`. Codex therefore
skips the Source Repository's project-scoped `.codex/` layer, including its
configuration, Hooks, and Rules. The Harness does not merge, replace, rename,
or temporarily shadow a Source Repository's `.codex/` directory. Repository
`AGENTS.md` instructions remain visible because they describe the codebase and
are not Runtime configuration. Repository Skills are governed separately by
ADR 0015.

Canonical role files live under `<harness-project-root>/.codex/agents/`.
The Harness-root `.codex/config.toml` is Main's orchestration configuration,
not an Engineer role or preflight contract; `resolve_codex_role()` neither
reads it nor compares it with the packaged root template. Engineer-required
Skill availability is resolved separately for each launch by
`resolve_effective_skills()`.
Codex V1 has no supported top-level `--agent` or arbitrary `--config-file`
selector for `codex exec`, so the Adapter mechanically serializes the selected
role's supported TOML configuration into dedicated CLI flags and repeated
`-c key=<toml-value>` overrides. This is an Adapter translation, not a request
for Main to understand individual Codex settings. Unsupported role keys fail
preflight rather than becoming arbitrary command syntax.

The same invocation supplies the Harness-owned Hook configuration and exact
evidence and Git-management access required by the Engineer. Static role
settings come from the canonical role; ticket identity, Worktree, evidence,
prompt, and session transport remain dynamic Runner inputs. `--profile` stays
rejected because it selects user-level `${CODEX_HOME}` state and would require
global installation. CLI details and physical Harness paths stay private to
Runner and the Adapter.

Launch records the effective role and Runtime inputs needed for recovery.
Resume reuses that immutable context rather than consulting a newly changed
Source Repository `.codex/` layer or accepting a new role from Main. System and
administrator-enforced Runtime policy remains in force; project isolation is
not a mechanism for bypassing managed constraints.

Codex Adapter acceptance must exercise a real installed process and prove that
the invocation-level trust override is applied before project configuration,
that Source Repository project agents and Hooks are not activated, and that
the Harness Hook remains active. Fake command tracing alone is insufficient
for those discovery semantics.

## Considered options

- Materializing a temporary `.codex/config.toml` in each Ticket Worktree was
  rejected because an arbitrary Source Repository may already own that path.
- Overriding only familiar scalar settings while still loading the target
  `.codex/` layer was rejected because Hooks, agents, MCP configuration, and
  future valid settings could still affect the Engineer.
- Writing profiles into `${CODEX_HOME}` was rejected because Harness Project
  setup must not pollute or depend on global user configuration.
