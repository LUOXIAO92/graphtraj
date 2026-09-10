---
name: implement
description: "Implement software from an engineering spec or code tickets."
disable-model-invocation: true
---

Implement the software behavior described by the user in the spec or code tickets.

Use /tdd where possible, at pre-agreed seams.

Use the assigned validation plan and the narrowest public-interface checks that
can falsify the change. For Runtime, permissions or recovery work, first
exercise the affected real boundary with a narrow probe; a test double that
bypasses that boundary cannot establish it works. Stub unrelated work.
Carry forward valid results for unchanged code. Run a
full suite for a final candidate when wider behavior may change; after bounded
follow-up work, validate the affected delta. When shared validation belongs to
Main, return your focused results for that check rather than duplicating it.

When assigned to a GraphTraj Team, self-review the work and return the candidate
and validation evidence to the Team Leader, who schedules both Reviewers.
For standalone implementation, use /code-review once done.

Commit authorized tracked project changes before ending the modifying turn or
handing off, including unfinished work with its status stated honestly. A commit
is not Team acceptance.
