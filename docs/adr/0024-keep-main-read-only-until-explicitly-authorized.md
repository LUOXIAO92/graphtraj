---
status: accepted
---

# Keep Main read-only until explicitly authorized

Main starts in Soft Plan and performs only read-only inspection, analysis,
diagnosis, and planning until the user explicitly asks it to execute a
state-changing action. Harness initialization places this rule in Main's
developer instructions; Soft Plan is not the Agent Runtime's formal Plan mode
and does not introduce a workflow state machine.

Statements that work is needed, agreement with a decision, or acceptance of a
plan do not authorize execution. Explicit execution authority is scoped to the
user's requested action: ordinary local implementation requires an explicit
implementation instruction, while commit, push, deletion, installation, and
external writes require authority covering those actions. Main may not bypass
Soft Plan by dispatching a write-capable subagent.

Main returns to Soft Plan when the authorized work completes, is interrupted,
or the user redirects the task. A request to continue authorizes mutation only
when it continues an unfinished, already-authorized execution; during
discussion it continues discussion only.
