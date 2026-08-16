---
status: accepted
---

# Install Harness Skills under the Harness-root `.agents` directory

For V2, setup installs release-supported core Skills that are absent from the
Runtime user's global Skill scope under
`<harness-project-root>/.agents/skills/`, not `.codex/skills/`. Doctor and setup
use those two scopes for core Skill discovery, and setup installs only missing
names so globally installed Skills are not duplicated.

The Harness-root `.codex/` directory continues to own the packaged
orchestration Runtime configuration, roles, Hooks, and Runner configuration.
Its root config has no persistent `[skills]` or `skills.config` list regardless
of whether required core Skills are available from the Harness Project Root or
Runtime-user scope; it is not read or compared as an Engineer preflight
contract. `resolve_effective_skills()` verifies Engineer-required Skill
availability separately for each launch. Source Repository Skills remain a
separate explicitly selected Engineer capability.
This supersedes only the Harness Skill installation and discovery directory
statements in ADR 0013 and ADR 0015.
