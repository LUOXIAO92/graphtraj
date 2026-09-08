---
name: retro
description: Review an execution session and suggest evidence-backed improvements to its instructions, information access and tools.
disable-model-invocation: true
---

# Retro

Read the primary evidence for the requested session; use the current session
when none is specified. Reconstruct what the Agent tried, what happened and
which conditions affected the result.

Look for improvements supported by observed friction or failure:

- **Navigation:** missing or hard-to-find information; prefer a useful pointer
  to copying the same information into more places.
- **Checks:** mistakes that a cheap, repeatable check could have caught.
- **Instructions:** missing distinctions, misleading guidance or rules that had
  no effect. Put a correction where the responsible participant reads it.
- **Tool economy:** expensive calls or repeated work with a concrete simpler path.
- **Information access:** evidence unavailable when a decision needed it.

For a software delivery session, read [coding retrospective](references/coding.md).

For each candidate, cite the session evidence, explain the resulting cost or
failure, and propose the smallest change that would address it. Reject changes
based only on hypothetical trouble. Present candidates in order of impact.

If an authorized improvement edits Agent guidance or Skills, read the installed
`writing-for-agents` skill when available; otherwise keep instructions scoped,
concise and linked to their existing authority. The retrospective itself
proposes changes; apply them only within the user's execution authorization.
