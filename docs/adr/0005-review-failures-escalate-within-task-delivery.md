---
status: accepted
---

# Review failures escalate within Task Delivery

Review escalation is an internal `task-delivery` policy rather than a separate
Skill. It has the same ticket, tier, review, session, worktree, and evidence
context already used by delivery; extracting it would create a shallow module
with one natural caller.

The policy is:

- Standards and Spec Reviewers return evidence. Main alone adjudicates the
  round as `PASS` or `FAIL` and records the rationale.
- Only Main's review `FAIL` increments the escalation counter. TDD red states,
  implementation test or typecheck failures, transport failures, and external
  blockers do not count.
- Below the threshold, a failed review resumes the same Engineer session in
  the same Ticket Worktree.
- Three review failures at one tier replace the Engineer with a fresh-context
  Agent in the same worktree: Junior to Senior, then Senior to Expert. The new
  tier starts its own failure count while retaining canonical work and review
  evidence, not the previous conversation.
- Three Expert review failures stop autonomous delivery and escalate the
  exception to Main or the user for a decision.

`task-delivery` does not prescribe `$implement`'s internal commit, amend, and
review order; Engineer roles follow the Matt Skills workflow. A successful
review only moves the ticket to `awaiting-integration`. Outside the
`task-delivery` Skill, Main performs serialized merge and validation in `dev`
as described in
[ADR 0009](0009-integrate-ticket-worktrees-through-dev.md); only work verified
there unlocks dependent tickets.
