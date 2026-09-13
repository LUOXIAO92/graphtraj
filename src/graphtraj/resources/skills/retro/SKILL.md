---
name: retro
description: Review an execution session and suggest evidence-backed improvements to its instructions, information access and tools.
disable-model-invocation: true
---

# Retro

Start from the question being investigated and existing findings; use the
current session when none is specified. Select evidence that can resolve the
question instead of replaying the entire session. For scheduling analysis,
first scan assistant messages and tool-call requests in time order, previewing
roughly the first 200 characters and expanding unclear or relevant entries.
Read tool results only when needed and permitted by the user's evidence limits.

Distinguish observed behavior, requested actions and author-reported outcomes.
A gap between calls is not measured tool time; call counts alone do not establish
token use or cost. Keep overlapping work separate from the elapsed critical path.
Explain necessary work and avoidable overhead separately. An opportunity visible
in hindsight is not proof of a mistake: use what was known at the time.

Look for improvements supported by observed friction or failure:

- **Navigation:** missing or hard-to-find information; prefer a useful pointer
  to copying the same information into more places.
- **Checks:** missing or repeated checks with demonstrated benefit or redundancy;
  the possibility of adding a check is not enough to justify one.
- **Instructions:** missing distinctions, misleading guidance or rules that had
  no effect. Put a correction where the responsible participant reads it.
- **Tool economy:** expensive calls or repeated work with a concrete simpler path.
- **Information access:** evidence unavailable when a decision needed it.
- **Scheduling:** duplicate dispatch, polling despite available notifications,
  ignored known dependencies and repeated budget extensions. Assess these against
  the governing Harness and workflow; keep their rules in those sources.

For a software delivery session, read [coding retrospective](references/coding.md).

For each candidate, cite the evidence, explain the impact and propose the
smallest change, preferring removal of repeated work or correction of an existing
instruction. Separate facts, inferences and unknowns; do not invent savings.
Reject hypothetical problems and present supported candidates in impact order.
Finish when the evidence supports a conclusion, its limits and any warranted
change; finding no justified change is a valid result. On follow-up, inspect new
or newly relevant evidence and revise affected conclusions, not the whole retro.

If an authorized improvement edits Agent guidance or Skills, read the installed
`writing-for-agents` skill when available; otherwise keep instructions scoped,
concise and linked to their existing authority. The retrospective itself
proposes changes; apply them only within the user's execution authorization.
