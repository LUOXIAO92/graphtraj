# Recovery decisions

Identify the failing action, its concrete cause and the direct parent able to
address it. A dispatcher corrects its own scope/input errors. The responsible
executor handles implementation defects through its parent. A provider failure
is not failed work; normal tool, watchdog and approval waits are not failures.

Keep one existing execution. Send changed instructions through its live channel;
after an actual failure ends execution, use the supported public continuation
operation with the causal event. Public `agent-runner status` supplies summaries;
`reports` exposes only directly owned reports. Apply the project's shared polling
limit. A send acknowledgement is not completion. Never wake a second Driver to
collect status or fill a missing report.

Preserve the candidate, author-attributed reports, original inputs, Session and
Trace references, and still-valid validation. A missing report copy calls for
report delivery through the direct relationship, not repeated implementation or
Review. Read the current state before requesting a transition; Runtime recovery
or scope correction alone does not establish an implementation rejection or
require another Round. Use the public operation that admits the retained state.
When continuation requires administrative or time repair, use the approved
recovery entry below instead of cycling through incompatible state transitions.
Return an unavailable capability or rejected repair to the actual parent with
its evidence; do not manufacture a Round or edit private state files.

For a confirmed implementation defect, cite its accepted requirement and actual
violation. Keep the correction with its responsible executor. Reuse unchanged
checks and reviews, verify only the affected correction and submit the new
version through the common result protocol. A new Round or Session does not
reset project-specific validation limits or expand the task's budget.

## Recover through the selected native approval

Use `agent-runner recover <alias>` or the shared `approved_recovery` operation
to prepare one concrete repair and continuation of the original Session. Supply
the reason, continuation instruction, allowed and forbidden scope, and actual
causal event IDs. Include `additional_minutes` only for the time increment
being requested, and `restore_active` when the retained administrative state
needs repair. The proposal retains the original clock, randomized allowance,
stop history, source acceptance, Git integration and Session identity.

`requires-native-approval` means the result contains a pending native execution
request. It is not approval and has not applied the repair. Submit that exact
returned request through the Runtime's configured human or automatic reviewer.
Existing authority references are evidence for that reviewer, not approval
tokens the model can manufacture. Preserve the proposed command and scope;
denial or approval failure does not authorize an alternate execution path.

After approval, read the actual result. `stale` means the approved snapshot no
longer matches the state to repair. `resume-failed` or `resume-stale` means the
result must be examined for already-applied changes and the continuation
failure; do not assume nothing happened or add the time again. `resumed`
confirms the reported continuation outcome, not completion of its work.
The resumed instruction carries the latest allowed and forbidden scope and
actual causal IDs to the original Session.

If a repair was applied but continuation needs retry, use only the original
alias and returned `recovery_event_id` as `retry_event_id`:

```text
agent-runner recover <alias> --retry-event-id <applied-recovery-event>
```

This retries the retained continuation rather than applying another repair or
time increment. Changed circumstances requiring a different repair need a new
concrete proposal through the same approval mechanism. Existing authority,
relationship, stop and permission checks still apply. For full parameters see
[command inputs](command-inputs.md#approved-recovery).

## Budget stops

Honor Runner's enforced stop. The task's actual parent receives its budget
notice and coordinates the children; physical stopping does not wait for the
parent to process a notice. Retain elapsed accounting, allowance, stop history,
files and evidence. A stored flag or log line alone does not demonstrate actual
interruption or timely notification delivery.

Use the delivered stop and limited wrap-up for a project-authorized recovery
assessment. Apply any user-selected stop instruction within its authorized scope; a
particular Skill is not a prerequisite for receiving or handling a stop. A notice, recovery,
report collection or replacement does not authorize extra execution time.

For a sampled stop that needs no additional administrative or time repair, the
existing narrow continuation after actual authorization remains:

```text
agent-runner continue --ticket-id <id> --caused-by-event-id <authorization-or-decision-event>
```

The default resumes existing roots with a generic continuation message. A revised
Ticket or causal event alone does not deliver new execution limits. For an
explicitly restricted sampled-stop recovery, restore permission with
`continue --budget-only`, then use `send` to deliver the allowed work, prohibited
work, any explicitly authorized deadline and actual causal event ID to the
original root. Use the returned continuation event for that second call. Check each result; restoring permission
does not mean the Session has resumed. Manual subtree stops still reject this
sequence and must not be bypassed.

When the authorized plan selects new participants, use ordinary configured root
swarm dispatch after any necessary budget restoration. Its first instruction can
state the exact handoff scope. A new root may join an active Team; it is a new
member, not an implicit replacement of another seat. Old entities retain their
parents and stop records. Authorization for more time remains separate.

Check that it admits the task's current state, preserve original accounting and
handle its actual return. Do not repeatedly invoke continuation to manufacture
acceptance. For an already committed integration escalation, use the retained
candidate and unchanged validation through the public integration entry as
specified in [command inputs](command-inputs.md).

Where execution permission still admits the Session,
`agent-runner send <alias> --reports-only` can collect retained reports using an
explicit instruction and causal event. It grants no implementation window and
does not bypass a manual subtree stop. Use the selected Runtime's actual notification channel and report a delivery failure through the caller.

## Adopt retained results

A genuinely assigned successor may submit an unchanged committed artifact as its
own handoff result. Credit the original authors and the valid evidence relayed by
its actual parent; write its own assigned report before submission. A new commit
or repeated implementation is not required. Its actual parent decides that new
submission, while the old submission and original Session relationships remain
unchanged. This does not grant control of old children or access to their private
reports, and is not permission to claim another Agent's work or checks as its own.

## Stop and replace

Ask the direct child to stop when possible; interrupt an out-of-control
descendant subtree through Runner when needed. That control exception does not
permit cross-level messages, approvals or replacement. Confirm the target and
all descendants have stopped before replacing it. Replacement requires the
actual direct parent or user; preserve the Runtime's native approval mechanism
when the requested relationship requires it. An actor flag grants no authority.

Use public control/replacement operations and report a missing capability through
the direct parent. Retain prior Sessions and useful evidence and give the new
executor the accepted scope, committed candidate and concrete remaining work.
Commit authorized tracked changes before handoff or turn end; mark unfinished
work honestly. A commit is neither acceptance nor permission for more time.
