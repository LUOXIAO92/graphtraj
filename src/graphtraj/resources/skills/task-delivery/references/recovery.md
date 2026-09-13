# Recovery decisions

Identify the failing action and who can change its cause before assigning work.
Return an Agent-correctable error to its existing Session with the concrete
failure, evidence and expected result for reflection and correction. A dispatch
mistake belongs to the dispatcher. System/provider outages or throttling return
to the superior for a later retry; permission/configuration failures go to the
role authorized to correct that configuration. Do not treat them as bad work.

Keep the candidate, author-attributed reports, tests and completed steps when
still valid. Report transport failure calls for report delivery, not a new
implementation or unchanged review. Check that the actual continuation input
contains the failed step and reusable evidence, not merely a generic handoff.

When the same defect recurs at another entrypoint, inspect the shared cause
and the adequacy of the existing check before assigning another isolated fix.
Judge Session health from evidence. Repeated same-kind errors, expanding repair
scope or demonstrated context decay may justify a fresh member Session.
Preserve the previous scene and provide accepted goals/constraints, current
commit, valid checks/reports, attempted fixes and remaining work. Reuse only
still-applicable evidence; a changed candidate needs proportionate validation
and affected review. Whole-Team replacement is a last resort when local
continuation cannot recover; explain why. A failure count does not select a
model, replacement or escalation by itself.

An enforced execution-budget stop is reported automatically by the timer to
Leader and the calling Main. After receiving that notice and the limited
wrap-up, the caller's host integration explicitly invokes `$retro` for this stop.
Preserve the Skill's invocation policy; a name in CLI output is not an invocation.
Ordinary budget reminders do not trigger retro. Handle each stop once using
its existing event and decision; delivery retries do not repeat the analysis.
For a Codex Main, use [Codex recovery delivery](codex-recovery.md). Other hosts
use their supported input mechanism, not Codex app-server. Report a missing
host integration instead of claiming delivery or enabling implicit discovery.

Reuse existing findings and inspect only missing decision evidence.
Separate necessary implementation/review from avoidable scheduling, repeated
polling, evidence replay and dispatcher errors. If a concrete code defect needs
diagnosis, use the relevant debugging Skill for that defect, not another full
delivery replay.

Choose a response supported by that analysis: repair the Harness or dispatch,
replace a damaged Session, revise task boundaries, or continue. Apply warranted
corrections within existing authorization before resuming; do not invent a
Harness change just because a stop occurred. Record the cause, correction or
reason none is warranted, remaining work and estimate, and next decision event
in the existing Worldline. Any fallback polling follows Harness Guidance.
Continue only when authorized with `agent-runner continue --ticket-id <id>
--caused-by-event-id <decision-event-id>`. Preserve original accounting and stop
history; budget edits alone do not resume work, and a user pause stays in effect.

An external observer timeout is not necessarily a stopped Team. Retain the
timeout, hand off that event and inspect the owned execution as needed; do not
suspend the observer to evade its deadline or start a duplicate driver.

Before ending a modifying turn or handing off, commit authorized changes to
tracked project files of every type. Mark unfinished or failed work honestly.
Continuous user-interactive drafting may batch adjacent turns, with a commit
before that editing segment ends or ownership changes. Preserve untracked
Harness state and traces outside Git; do not initialize a repository or
force-add ignored records to satisfy this rule. Commit does not mean acceptance.
