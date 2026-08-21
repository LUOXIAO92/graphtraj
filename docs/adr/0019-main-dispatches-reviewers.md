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

Reviewer dispatch follows ADR 0018's Runtime-selection policy. Choosing a
different Runtime or model provides Review Diversity and helps counter one
Agent family's systematic biases, but diversity is not a hard precondition for
review and the Harness must not claim it when the selected Reviewer is not
actually diverse.
