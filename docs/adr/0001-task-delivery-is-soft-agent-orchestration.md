---
status: accepted
---

# Task Delivery is soft Agent orchestration

The V1 Harness delivers an accepted Ticket DAG through isolated Engineers
without turning the observed workflow into a deterministic orchestration
engine. `task-delivery` is therefore a Main-facing Skill: it teaches Main how
to orchestrate delivery while leaving semantic judgment with the Agent.

The planning and delivery sequence is fixed:

1. The existing design and user intent enter an iterative alignment loop using
   the grilling Skills and `$to-spec`.
2. `$to-tickets` converts the accepted spec into accepted tickets with explicit
   dependencies.
3. `task-delivery` consumes that accepted Ticket DAG.

`task-delivery` does not generate the spec, split work into tickets, invent
missing dependencies, rewrite acceptance criteria, or redesign settled scope.
Incomplete, cyclic, ambiguous, or contradictory work returns to Main for
planning or user clarification. Its task map is an Agent-readable working view
of the accepted tickets, not a machine-enforced normalized graph or formal
Engineer dispatch packet.

A Delivery Run defaults to driving the entire accepted DAG through successive
ready frontiers until every ticket is integrated, externally blocked, or
escalated. `awaiting-integration` is an internal checkpoint, not the default
end of the run. The user may interrupt or redirect delivery at any time; Main
interprets that request in context. V1 does not add pause, stop, cancellation,
resume, or replanning commands or a Delivery Run control-state machine.

Main retains authority over dependency readiness, complexity classification,
Engineer tier, dispatch, review adjudication, retry and escalation,
integration ordering, and exceptions. No V1 program enforces those semantic
decisions. Engineers receive the accepted ticket, an optional concise
instruction, and the ticket's referenced material; they do not need the whole
DAG or Main's historical reasoning.

`task-delivery` does not merge reviewed commits into `dev`. Main performs the
serialized integration and validation flow outside the Skill, records the
result through the Delivery State Agent, and then continues the same Delivery
Run from its updated ledger.

Two supporting components remain deliberately narrower than Main:

- The Delivery State Agent maintains the ledger and Mermaid task map as
  described in [ADR 0003](0003-delivery-state-agent-maintains-run-state.md).
- The Agent Runner performs mechanical Engineer launch, isolation, session
  transport, and cleanup, beginning with the interface in
  [ADR 0006](0006-runner-dispatches-main-selected-ticket-batches.md).

Review escalation is policy inside `task-delivery`, not a separate Skill; its
thresholds and evidence rules are recorded in
[ADR 0005](0005-review-failures-escalate-within-task-delivery.md).

## Considered options

- A deterministic normalizer, scheduler, transition command, watcher, or event
  loop was rejected because V1 exists to observe and improve a soft Agent
  workflow before hardening stable rules.
- Folding `$to-spec` and `$to-tickets` into `task-delivery` was rejected because
  planning settles scope while delivery consumes it.
- Letting the Runner discover ready tickets or choose roles was rejected
  because those are semantic orchestration decisions owned by Main.

## Consequences

Reliability comes from explicit role instructions, Main's judgment, durable
evidence, isolated worktrees, and review rather than enforced semantic
transitions. A later decision may harden a proven part of this workflow, but it
must not silently turn the V1 soft Harness into a controller.
