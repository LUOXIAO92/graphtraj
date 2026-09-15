# Delivery failure examples

These historical cases explain recurring mistakes in task boundaries, evidence
reuse and execution. Their Ticket numbers identify the examples; they do not
add requirements, dependencies or validation steps to another project.

## A local task inherits an undefined global testing obligation

**Observed — Ticket 117:** The task required an MCP entrypoint and its behavior
checks. The Leader's dispatch combined focused test instructions, “do not replay
unrelated or unchanged suites” and “keep the default suite green.” The Engineer
ran the full suite, then investigated its failures. Main clarified the shared
regression arrangement only afterwards. Execution and failure investigation
took about twenty minutes; that does not prove every minute was avoidable.

**Wrong inference:** A general quality goal requires every task to rerun all
tests. The two dispatch phrases could have been satisfied together, but no
change-impact rationale supported expanding this task's validation scope.

**Correct boundary:** Select checks for the task's promised behavior and the
actual effects of its changes. Keep cross-task validation ownership in Main's
overall plan. A task consumes predecessor results; it does not acquire another
task's acceptance criteria. Scope expansion needs a concrete affected behavior,
not a generic instruction to keep everything green.

## A report correction invalidates unchanged implementation evidence

**Observed — Ticket 118:** Incorrect diff counts required an Engineer report
correction; candidate `897a20f` stayed unchanged. The installed Runner treated
any Engineer correction as affecting both Reviewers, removed their current
reports and resumed them sequentially. They repeated validation. This was a
concrete scheduling behavior, not merely a Reviewer choosing extra tests.

Source commit `74ac18a` had already changed that behavior to retain reviews
when the candidate stayed unchanged, but the actual Driver still invoked an
older installation. Having the fix in the source branch did not make the
running tool contain it.

**Wrong inference:** Correcting an author makes all of that author's downstream
evidence invalid; a source fix also guarantees the active installation is fixed.

**Correct boundary:** Determine affected evidence from what changed, including
candidate, comparison, requirements and relevant execution conditions. Correct
report claims while retaining still-valid tests and reviews. Independent review
and integration checks can have distinct purposes. When adopting a tool fix,
use an installation containing it; do not diagnose old behavior as a new Agent
failure or add another rule for a fix that is already implemented.

## Reusing a function is mistaken for reusing an entire caller connection

**Observed — Tickets 118 and 122:** Caller budget-notice delivery had been
verified through a CLI wrapper. The MCP entrypoint called the shared business
operation directly, without that wrapper's caller binding. The Team treated
the earlier CLI evidence as covering MCP delivery. It then interpreted “do not
inject Main instructions” as forbidding the missing event connection.

ADR 0038 concerned generating, installing, appending or restoring Main's
developer instructions. It did not prohibit the separately requested stop
event and explicit Skill input. The Leader withdrew that interpretation after
Main challenged it; Ticket 122 supplied the missing connection. Its necessary
implementation cannot all be counted as waste.

**Wrong inference:** A shared function carries every surrounding caller
guarantee; a prohibition on one kind of input also prohibits a different input
that happens to reach the same recipient.

**Correct boundary:** Reuse only the behavior established at the predecessor's
actual boundary. Check the connection needed by the new entrypoint. Interpret
a requirement by its stated action and scope, alongside related accepted
requirements. Return a concrete source conflict to Main instead of silently
turning a required behavior into an out-of-scope feature.
