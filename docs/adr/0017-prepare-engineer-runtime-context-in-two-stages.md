---
status: accepted
---

# Prepare Engineer Runtime Context in two stages

V2 deepens the Engineer Runtime Context introduced by ADR 0014 into one
side-effect-free preparation boundary. It resolves and freezes the effective
role, Hook, Skills, fixed trust policy, Runtime request inputs, and recovery
evidence, but it does not create Worktrees, reserve tasks, write durable state,
start a Runtime process, or own a Runtime session; Runner retains the first
three responsibilities and the selected Adapter retains native process and
session mechanics.

Preparation has two stages because batch preflight occurs before a Ticket
Worktree exists while Repository Skill paths can be finalized only afterward.
The preflight stage validates every fact available before provisioning, and the
final stage returns the immutable Context after Worktree-local facts resolve;
both stages use the same rules rather than duplicate role or Skill logic.

This change is scoped to Engineer Runtime Context rather than setup actions or
a general Skill-semantics rewrite. Except for separately accepted V2 Runtime
selection and Reviewer-dispatch decisions, it preserves observable launch
behavior, error semantics, file layout, and persistence ownership.
