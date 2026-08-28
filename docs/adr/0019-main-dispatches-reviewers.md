---
status: accepted
---

# Main dispatches Reviewers

This supersedes earlier Engineer-owned Reviewer creation and report-handoff
wording in ADRs 0004, 0005, 0008, 0009, and 0011; their evidence retention,
transport, integration, and Skill-discovery decisions otherwise remain
accepted. ADR 0022 now owns review-failure diagnosis and escalation.

When candidate work requires review, Main dispatches the Standards and Spec
Reviewers rather than delegating Reviewer creation to the Engineer, and Main
continues to adjudicate their evidence. Review applicability remains a soft
delivery judgment owned by Main; merge and integration are Main-owned actions
outside Reviewer dispatch.

For one review round, Main first fixes one candidate commit and comparison
point, then launches the Standards and Spec Reviewer Turns concurrently through
separate Runner tasks against that same Ticket Worktree. Neither axis gates the
other. The candidate is read-only to both Reviewers, and each Reviewer may write
only its Main-supplied, non-overwriting report. Engineer Turns remain
Worktree-exclusive; concurrent sharing is limited to these two Reviewer roles
under the read-only candidate boundary defined here and the live identity
boundary in [ADR 0008](0008-address-engineer-sessions-by-alias.md).

Main waits for both attributable reports, verifies that the fixed candidate and
Git state are unchanged, and adjudicates one review-round `PASS` or `FAIL`.
This concurrency does not make review mandatory, create a mechanical
applicability rule, or require Review Diversity.

Finding admissibility is inherited from the one managed Reviewer-guidance
section defined by [ADR 0026](0026-manage-inherited-reviewer-guidance.md). That
policy does not become a second owner of dispatch, concurrency, or Main's
adjudication defined here.

Reviewer dispatch follows ADR 0018's Runtime-selection policy. Choosing a
different Runtime or model provides Review Diversity and helps counter one
Agent family's systematic biases, but diversity is not a hard precondition for
review and the Harness must not claim it when the selected Reviewer is not
actually diverse.
