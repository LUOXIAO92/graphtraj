---
status: accepted
---

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
setup resources for Codex, OpenCode, and future Agent Runtimes. Setup installs
those resources through the selected Runtime Adapter; the Runner itself is a
shared host tool and is not installed into an Agent profile.

After the host tool is installed, the operator runs
`you-are-a-product-architect setup` from the target Git project. The selected
Runtime Adapter writes its reviewable resources into that Runtime's native
project-local layout: for Codex this includes `.codex/config.toml`,
`.codex/agents/`, and `.codex/hooks/`; OpenCode and future Runtimes use their
own project-local equivalents. These resources are intended to be reviewed and
committed so that `dev`-derived Integration and Ticket Worktrees inherit the
same role and isolation configuration. Setup does not write to `${HOME}/.codex`
or another Runtime's user-level configuration, create global profiles, modify
credentials or user defaults, or silently mark a project as trusted. A Runtime
that requires project trust must obtain it through its normal user-controlled
trust flow.

Machine-local paths, executable bindings, and Runner session mappings remain
outside the committed project configuration under
`<git-common-dir>/agent-runner/`, as defined in ADR 0001. Repository engineering
metadata remains separately owned by `setup-matt-pocock-skills`: this setup does
not create or update `AGENTS.md` or `docs/agents/`. For Codex in particular,
project-local custom-agent files are Runtime resources rather than user-level
profiles; the Codex Adapter still owns the internal translation from Main's
logical role to a top-level `codex exec` launch without exposing paths or Codex
arguments to Main.
