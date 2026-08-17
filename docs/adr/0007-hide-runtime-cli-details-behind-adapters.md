---
status: accepted
---

# Hide Agent Runtime CLI details behind Runner Adapters

> **Partial supersession:** [ADR 0013](0013-own-runtime-resources-at-the-harness-root.md)
> replaces current-Git-project discovery as Main's control-plane entrypoint,
> and [ADR 0014](0014-inject-engineer-runtime-through-the-adapter.md)
> replaces the Source Repository `.codex` loading model. [ADR 0018](0018-main-selects-runtimes-outside-task-objects.md)
> replaces V1's Runtime-selection authority and defaulting policy. The
> Runner/Adapter abstraction, semantic role selection, and private Runtime
> transport remain accepted.

Main addresses logical Engineer roles without constructing or supplying
Runtime commands, profile paths, or machine-local worktree and state paths.
The Runner may return resolved paths and an opaque Runtime session as launch
evidence, but Main uses the semantic alias rather than those values for normal
transport. Runtime differences are isolated behind the Runner's built-in,
allowlisted Adapter registry.

Harness Project setup creates a machine-local Project Runner Config at the
Source Repository's `<git-common-dir>/agent-runner/config.yml`. It is shared by
all linked Worktrees of that repository, is not committed, and records the
config version, default Runtime, project-private `worktree_root`, integration
branch, Runtime executable, and private logical role bindings. The registered
root is `<harness-project-root>/.agent-worktrees/` as defined by
[ADR 0012](0012-isolate-each-harness-project-at-its-own-root.md). The Runner
discovers the config from the current Git project; Main does not locate or pass
it.

V1 allowed an explicit `AGENT_RUNTIME` environment value to override the
configured default, while normal `task-delivery` calls omitted the override.
ADR 0018 replaces that selection policy for V2. Runtime selection remains
outside batch task objects, and unknown or unconfigured Runtimes still fail
preflight before launch.

The selected Runtime name resolves only through the Runner's built-in Adapter
registry, and only that selected Adapter is loaded. Project config may supply
values understood by an Adapter, but it cannot name an arbitrary Python
module, shell template, or raw command. Each Adapter privately resolves role
configuration, renders its command, starts the Engineer in the Ticket Worktree,
captures the Runtime session, and translates transport results to the shared
Runner interface.

For Codex, a configured role binding names one project-local custom Agent in
`.codex/agents/`. The Adapter validates an explicit supported role schema and
materializes its session settings as top-level `codex exec` arguments and
configuration overrides. It never translates the binding to `--profile`:
Codex profiles layer files from `CODEX_HOME` and are not project custom-Agent
selectors. Before using Codex's invocation-scoped hook-trust bypass, the
Adapter verifies that the role contains the exact packaged Engineer Hook
declaration and that `.codex/hooks/worktree_guard.py` is byte-for-byte the
installed packaged guard. A mismatch fails closed before Runtime launch. This
does not persist trust, write global Runtime configuration, or bypass the
configured sandbox, approval, or network controls.

V1 implements only the Codex Adapter. It privately performs the equivalent of:

```text
codex exec -C <ticket-worktree> \
  --add-dir <ticket-evidence-dir> \
  --add-dir <git-common-dir>
```

The Source Repository's `.codex/config.toml` uses `workspace-write` and adds
the Worktree-local `.scratch` path to
`sandbox_workspace_write.writable_roots`. Main and the native Delivery State
Agent therefore reach the external Harness State Directory through the
Integration Worktree symlink, while each Engineer receives its exact evidence
directory and the Source Repository's Git common directory through the
Adapter's invocation-local `--add-dir` arguments. The Git common directory is
required for a linked Ticket Worktree to stage and create its candidate
commit; the Worktree Guard still rejects explicit paths outside the current
Ticket Worktree and rejects unmodelled Git commands. Setup verifies that
`.scratch` resolves to the registered writable state directory. None of these
paths or raw Codex syntax enter Main's task object.

These settings use Codex's normal project configuration. The product does not
add a mechanical or interactive Main launcher. OpenCode and other Runtime
Adapters are explicit later work; their CLI flags, configuration layout,
interpretation and reuse of session identifiers, and live-input behavior must
remain private behind the same logical interface. An Adapter may surface a raw
session identifier as opaque evidence without making it Main's transport
address.

## Considered options

- Exposing raw commands, profile paths, or config paths to Main was rejected
  because it leaks Runtime implementation into the soft Harness.
- Letting project config load an arbitrary Adapter module or shell command was
  rejected because it turns configuration into an unbounded execution seam.
- Hard-coding Codex syntax into `task-delivery` was rejected because Runtime
  portability belongs in the Runner, not in Main's reasoning.
- Native Agent spawning is not used for V1 Engineer dispatch because it cannot
  yet bind the spawned Engineer to the required Ticket Worktree. It may become
  another Adapter when the needed worktree and session controls exist.
