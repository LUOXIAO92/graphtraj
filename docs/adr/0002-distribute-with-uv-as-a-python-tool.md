---
status: accepted
---

# Distribute you-are-a-product-architect with uv as a Python tool

`you-are-a-product-architect` is distributed as one auditable Python package
rather than through npm or a mixed Node-to-Python launcher. A persistent host
installation uses:

```text
uv tool install "git+https://<repository-url>@<tag-or-commit>"
```

The reviewed tag or commit is pinned instead of installing from a moving
branch. `uv tool` supplies an isolated host environment and stable executables
without binding the product to a target project's virtual environment.

The distribution is named `you-are-a-product-architect`, its import package is
`you_are_a_product_architect`, and it exposes two console entries:

- `you-are-a-product-architect` performs explicit project setup and
  configuration.
- `agent-runner` provides delivery-time Engineer transport for Main.

The same distribution carries `task-delivery`, shared templates, role
definitions, backed-up supported Skills, and Runtime-specific setup resources.
The V1 `task-delivery` source template lives at `codex/skills/task-delivery`
inside this product. If that Skill name is missing and the operator chooses
project-local installation, setup writes the release's supported copy to the
repository-relative `.agents/skills/task-delivery/` path through the
Integration Worktree. An already discoverable same-name Skill satisfies the
name-only check and is not replaced.
The host CLI uses Click. Project setup remains a separate responsibility
described in [ADR 0010](0010-configure-target-projects-locally.md), while Skill
dependency policy is described in
[ADR 0011](0011-resolve-core-skills-by-name.md).

V1 implements and verifies the Codex Adapter. OpenCode and other Runtime
Adapters remain explicit follow-up work behind the Adapter seam in
[ADR 0007](0007-hide-runtime-cli-details-behind-adapters.md); the distribution
does not claim that support before those Adapters exist.
