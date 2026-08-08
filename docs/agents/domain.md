# Domain Docs

How engineering skills should consume this repository's domain documentation
when exploring or changing the harness.

## Before exploring, read these

- `docs/pure_agent_harness.md` — the current V1 architecture, role boundaries,
  safety invariants, and end-to-end state flow.
- `CONTEXT.md` at the repository root — the shared domain language, when it
  exists.
- `docs/adr/` — ADRs relevant to the area being changed, when they exist.

If `CONTEXT.md` or `docs/adr/` does not exist, proceed silently. Do not suggest
creating them upfront. The domain-modeling workflow creates them lazily when
terminology or architectural decisions are actually resolved.

## File structure

This repository uses a single-context layout:

```text
/
├── CONTEXT.md
├── docs/
│   ├── pure_agent_harness.md
│   └── adr/
│       ├── 0001-example-decision.md
│       └── 0002-another-decision.md
└── codex/
```

## Use the glossary's vocabulary

When output names a domain concept—in a spec, ticket, review finding, test
name, or architecture proposal—use the term defined in `CONTEXT.md`.

Do not casually replace established concepts such as Master, Engineer,
Reviewer, Merge Resolver, control plane, integration queue, or project-level
binding with ambiguous synonyms.

If a required concept is missing, reconsider whether new terminology is
necessary or note the gap for the domain-modeling workflow.

## Preserve harness invariants

Treat the settled boundaries in `docs/pure_agent_harness.md` as constraints
unless the task explicitly revisits them. In particular, surface any proposal
that changes role ownership, worktree isolation, review authority, escalation,
or serialized integration.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly
instead of silently overriding it:

> Contradicts ADR-0007 — but worth reopening because…
