# Recovery decisions

Identify the failing action and who can change its cause before assigning work.
Return an Agent-correctable error through its direct parent with the concrete
failure, evidence and expected result. Communicate only with your own direct
parent and children; Main does not contact a Team member to recover it. A dispatch
mistake belongs to the dispatcher. System/provider outages or throttling return
to the superior for a later retry; permission/configuration failures go to the
role authorized to correct that configuration. Do not treat them as bad work.

## Choose the Round before continuing

Use the Leader's diagnosis, not the choice to resume an existing Agent:

- Process corrections, such as scope expansion or unsupported Review findings,
  stay in the current Round.
- Runtime recovery or delivery of a missing report resumes the interrupted work;
  neither alone opens a Round.
- A supported implementation defect that the Leader confirms requires rework
  closes the current Round and opens the next Round in the same Team. The same
  Agents may continue; their Session identity does not determine the Round.

The Leader records the rework through the existing delivery-state workflow.
Before the implementation follow-up, Main and Leader use the registered new
Round and its report destinations. A send, resume or budget restart alone does
not record this transition. Keep the existing budget and Review-axis limits.

Read still-valid evidence from previous Rounds and reference it where needed.
Write the new candidate's implementation, validation and Leader decision in the
new Round; do not copy old reports or append new-round results to a closed Round.
Each new report covers that Round's work and result, with references to reused
evidence rather than a running history of all attempts. Reusing earlier Review
reports does not require another Review or writing back into their Round.

## Recover the execution

Permission requests notify the direct parent immediately through its existing
execution; notification does not approve them. Use actual available capabilities
and report a missing delivery path instead of creating a second execution.
Normal watchdog, member, tool and approval waits are not failures. State queries
return summaries; lack of output or a stale heartbeat alone is not proof of death.

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
still-applicable evidence. A changed candidate needs proportionate checks, but
does not reset the once-per-Ticket Review-axis limit. The Leader verifies later
corrections and owns test acceptance. Whole-Team replacement is a last resort when local
continuation cannot recover; explain why. A failure count does not select a
model, replacement or escalation by itself.

Replacement belongs to the target's direct parent or the user. Prefer a stop
request, using interrupt when needed or immediately for an out-of-control child.
Confirm the target and all descendants have stopped before replacing any of
them. Use Runner's descendant-stop capability when available; a single-Agent
stop receipt does not prove a subtree stopped. A legacy Main-only gate does not
authorize cross-level recovery. On a confirmed abnormality, notify its direct
parent and stop its descendants through the supported control interface; do not
automatically replace Agents or increase budgets.

An enforced execution-budget stop is delivered by the timer to the Leader and
the calling Main. Under the user's explicit standing authorization, Main runs
the named retro from that event and the limited wrap-up; it does not require
a fresh user input for each stop. Keep explicit-only Skill discovery and the
scope of the user's authorization. Ordinary reminders do not trigger retro.
Handle each stop once using its event and retained decision. For a Codex Main,
use [Codex recovery delivery](codex-recovery.md). Return the event through the
active tool call; a log entry or accepted queue row is not delivered recovery.

Read retained reports returned by your direct child. Missing member evidence
is handled through that child, not by contacting its members. Do not wake a
Leader again while the Ticket execution is running merely to collect reports.
After an execution has ended, use report-only collection through the same
hierarchy when necessary; it must not start another work-budget sampler or new
implementation.

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

That command accepts only a sampled-stopped Ticket. Its return may report missing
Engineer evidence or `not-accepted` without running a new Leader turn. When a
stopped implementation needs a new Round, finish this retained-evidence recovery
in the old Round first, then register the new Round before sending implementation
work. Otherwise recovery can copy the old incomplete result into the new Round. After the
Driver ends, send the remaining implementation or acceptance work to the same
Leader through the causal event; use the existing execution while it is active.
An old stopped-before-acceptance report supplies neither acceptance nor rejection.
Once the Leader has delivered a decision, finish missing registration through
[the semantic state commands](command-inputs.md#finish-retained-delivery), rather
than invoking `continue` again on a Ticket whose stop has already been cleared.

An external observer timeout is not necessarily a stopped Team. Retain the
timeout, hand off that event and inspect the owned execution as needed; do not
suspend the observer to evade its deadline or start a duplicate driver.

Before ending a modifying turn or handing off, commit authorized changes to
tracked project files of every type. Mark unfinished or failed work honestly.
Continuous user-interactive drafting may batch adjacent turns, with a commit
before that editing segment ends or ownership changes. Preserve untracked
Harness state and traces outside Git; do not initialize a repository or
force-add ignored records to satisfy this rule. Commit does not mean acceptance.
