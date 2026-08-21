---
status: accepted
---

# Diagnose review failures before choosing an action

This supersedes ADR 0005's mechanical tier thresholds. A review `FAIL` is
evidence that Main must diagnose, not proof that the current Engineer tier is
incapable; Main records the cause and next-action rationale before retrying,
replacing an Agent, escalating, or returning work to planning.

Small implementation corrections remain with the same Engineer and tier. Main
may choose a fresh-context Engineer at the same tier when the task remains
suitable but the session context is polluted. Main chooses a higher tier only
when the accepted Ticket is clear and the evidence shows genuine difficulty or
a capability mismatch; this may happen before three failures. Three failures
at one tier require explicit reassessment but never trigger automatic
escalation.

When Main's tier choice, decomposition, dependencies, acceptance mapping, or
dispatch instruction caused the failure, Main corrects its orchestration
within the accepted Spec instead of counting an Engineer failure. Main-created
overengineering is a distinct cause: mechanisms, assumptions, validations,
edge cases, or tests without user or Spec authority are removed, the polluted
Ticket and candidate are not refined further, and the corrected minimal work
is classified again. Main must not relabel complexity it created as an
Engineer capability mismatch.

Reviewer error, transport failure, implementation-test failure, integration
failure, and external blockers do not justify tier escalation. Product or Spec
changes remain user-owned. Failure counts remain historical evidence only;
the Delivery State Agent records Main's decision but neither it nor the Runner
infers causes or chooses the next action.
