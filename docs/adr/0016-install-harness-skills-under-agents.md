---
status: accepted
---

# Install Harness Skills under the Harness-root `.agents` directory

For V2, setup installs release-supported core Skills that are absent from the
Runtime user's global Skill scope under
`<harness-project-root>/.agents/skills/`, not `.codex/skills/`. Doctor and setup
use those two scopes for core Skill discovery, and setup installs only missing
names so globally installed Skills are not duplicated.

The Harness-root `.codex/` directory continues to own Runtime configuration,
roles, Hooks, and Runner configuration. Source Repository Skills remain a
separate explicitly selected capability. This supersedes only the Harness
Skill installation and discovery directory statements in ADR 0013 and ADR
0015.
