---
status: superseded by ADR-0027
---

# Keep Project Documents read-only for subagents

Main alone modifies Source Repository Project Documents, including ADRs,
READMEs, specifications, design and operating guidance, and Agent instruction
documents. Engineers, Reviewers, Merge Resolvers, and every other subagent may
read those documents but must not create, modify, move, or delete them; tasks
that require document changes keep that work with Main.

The Harness enforces this before a subagent can write rather than relying on a
prompt or later review. Codex subagent Role TOML selects a native permissions
profile whose configured Project Document paths have `read` access, and the
Codex Adapter carries that native configuration into the finalized Runtime
Context. This decision does not add a document-classification Hook, custom
permission framework, ACL, or container.

Harness State records and delivery evidence are not Project Documents and
retain their existing role-owned write scopes. Main does not receive the
subagent document restriction.
