---
name: implement
description: "Implement software from an engineering spec or code tickets."
disable-model-invocation: true
---

Implement the software behavior described by the user in the spec or code tickets.

Use /tdd where possible, at pre-agreed seams.

Use the assigned validation plan and the narrowest public-interface checks that
can falsify the change. Choose values or inputs that fail when the change is
absent; an override matching the default cannot prove the override works.
Use supplied investigation and valid checks as starting points, then investigate
the implementation gaps needed for this task. For Runtime, permissions or recovery work, first
exercise the affected real boundary with a narrow probe; a test double that
bypasses that boundary cannot establish it works. Stub unrelated work.
Carry forward valid results for unchanged code. Run a
full suite for a final candidate when wider behavior may change; after bounded
follow-up work, validate the affected delta. When shared validation belongs to
Main, return your focused results for that check rather than duplicating it.

When assigned to a GraphTraj Team, self-review the work and return the candidate
and validation evidence to the Team Leader, who schedules both Reviewers.
Before handoff, compare the report with the complete fixed candidate, including
changes supplied by others. Correct stale claims in the report locally.
For standalone implementation, use /code-review once done.

Commit authorized tracked project changes before ending the modifying turn or
handing off, including unfinished work with its status stated honestly. A commit
is not Team acceptance.
