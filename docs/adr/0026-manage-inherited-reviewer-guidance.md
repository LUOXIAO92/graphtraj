---
status: accepted
---

# Manage inherited Reviewer guidance during Project Setup

This narrowly supersedes ADR 0010's prohibition on product-managed
`AGENTS.md` content. Project Setup owns exactly one marked Reviewer-guidance
section in the Source Repository root `AGENTS.md`; it owns no surrounding user
content and does not manage other repository instruction or domain documents.

The managed block begins with
`<!-- you-are-a-product-architect:reviewer-guidance:start -->`, contains the
`## Reviewer guidance` heading and the repository's canonical minimum-review
body, and ends with
`<!-- you-are-a-product-architect:reviewer-guidance:end -->`. That root block is
the sole prose authority. Runtime config, role prompts, Skills, ADRs, and other
operational documents may reference it but must not copy its body. In
particular, Main's Soft Plan policy from ADR 0024 is not Reviewer guidance.

When `AGENTS.md` is absent, setup creates it with `# AGENTS.md` followed by the
managed block. When it exists, setup preserves all content outside the managed
markers and places exactly one current managed block at the end. A rerun
updates that block in place without duplicating it. Setup treats this managed
merge as a declared exception to ADR 0010's otherwise fail-closed handling of
different repository files; it does not gain a general Markdown merge
facility or a document synchronization mechanism.

Setup applies the change in the registered Integration Worktree. The operator
reviews and commits it to `dev` before launching Ticket Worktrees, so Agents
started at a Ticket Worktree inherit the same Source Repository instruction.
Codex discovers project guidance from the project root, normally the Git root,
and then walks toward the current working directory; the Harness Project Root
is therefore not a substitute inheritance source. See the official
[Codex guidance discovery documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md#how-codex-discovers-guidance).

Agents read the accepted finding-admissibility policy only from that root
block. Main remains the adjudicator under ADR 0019; this ADR installs the
policy but does not restate or redefine it.

Historical whole-system designs, pre-split ADR sources, audit reports, and
generated previews remain available as non-authoritative evidence. Repository
exploration starts with `CONTEXT.md` and `docs/adr/README.md`; it does not revive
those historical sources as a second owner of current behavior.

## Considered options

- Managing guidance only in the Harness Project Root was rejected because a
  Ticket Worktree is rooted in the Source Repository and would not inherit it.
- Copying the body into Reviewer roles or `task-delivery` was rejected because
  copies drift and create competing review authorities.
- Letting setup rewrite all repository instructions was rejected because one
  marked block is sufficient and surrounding content is user-owned.
