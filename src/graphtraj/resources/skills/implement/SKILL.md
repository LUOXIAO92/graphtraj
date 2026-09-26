---
name: implement
description: "Implement software from an engineering spec or code tickets."
disable-model-invocation: true
---

Implement the software behavior described by the user in the spec or code tickets.

Use the assigned scope and difficulty assessment. Small fixes and test
modifications must not use TDD or code-review Skills. For other work, use TDD
when it fits the assigned implementation, at already agreed seams.
Instruction-only changes to prompts, Skills and guidance need a consistency
check and a commit where tracked, not tests or a review workflow.

Use the assigned validation plan and the narrowest public-interface checks that
can falsify the change. Choose values or inputs that fail when the change is
absent; an override matching the default cannot prove the override works.
Use supplied investigation and valid checks as starting points, then investigate
the implementation gaps needed for this task. Run development tests under the project's assigned responsibilities and return
versioned evidence to its authorized acceptor; reuse already valid checks. For Runtime, permissions or recovery work that needs
new evidence owned by this assignment, exercise the affected real boundary
with a narrow probe; a test double bypassing it cannot establish it works.
Stub unrelated work and reuse valid results for unchanged paths. Run a full
suite for a final candidate when wider behavior may change; after bounded
follow-up work, validate the affected delta. Committing unchanged tested content
or repairing a report alone does not require another full suite.

When the project selects coding-team coordination, self-review the work and
return the candidate and evidence to the assigned coordinator, who chooses Review scope;
each axis runs at most once per Ticket and Reviewers never run tests. Subsequent
corrections return to the assigned acceptor for verification, not another Review cycle.
Return concrete blockers promptly to that owner. Follow
[task-delivery](../task-delivery/SKILL.md) for event handling and the shared
Harness polling limit for any running probe; do not
start a second review or watch another role's report files.
Before handoff, compare the report with the complete fixed candidate, including
changes supplied by others. Correct stale claims in the report locally.

Commit authorized tracked project changes before ending the modifying turn or
handing off, including unfinished work with its status stated honestly. Submit committed results through the common Runner result operation. A commit
is not task acceptance.
