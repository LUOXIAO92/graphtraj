---
name: domain-modeling
description: Sharpen a project's terminology, concept relationships and decisions. Use when changing the shared model, rather than merely reading its vocabulary.
---

# Domain Modeling

Read the existing glossary, context map and relevant decisions. Within a
Harness Project, Main owns `CONTEXT.md` and `docs/` at its root; delegated
roles use their Worktree views read-only and return proposed changes to Main.

Challenge a term when its actual use conflicts with the agreed definition.
Resolve vague or overloaded language through concrete scenarios that expose
where concepts differ and how they relate. Apply already accepted distinctions
instead of asking the user to decide them again.

Check descriptions against the task's actual sources and results. Distinguish
what has been observed, assumed and decided. Show a contradiction with its
evidence before proposing to change the shared model.

For software implementation or architecture questions, read
[coding checks](references/coding.md).

When a term is resolved, record it using [CONTEXT-FORMAT.md](CONTEXT-FORMAT.md)
within the authorized document scope. Keep the glossary about concepts, with
their definitions and important relationships. Create it only when there is
content to record; follow an existing context map rather than inventing one.

Record a decision only when it involves a real trade-off, is costly to reverse,
and would surprise a future reader without its rationale. Use
[ADR-FORMAT.md](ADR-FORMAT.md). Otherwise keep the conclusion with the work
that needed it. Return proposed text when writing is outside your authority.
