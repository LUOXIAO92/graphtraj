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

## Recover with the selected reviewer

Use `agent-runner recover <alias>` or the shared `approved_recovery` operation
to perform one concrete repair and continuation of the original Session. Supply
the reason, continuation instruction, allowed and forbidden scope, and actual
causal event IDs. Include `additional_minutes` only for the time increment
being requested, and `restore_active` when the retained administrative state
needs repair. The proposal retains the original clock, randomized allowance,
stop history, source acceptance, Git integration and Session identity.

Use `--no-resume` (shared `resume: false`) when only the administrative repair
should run. In particular, restoring a closed Team's delivery state without
adding time must preserve its budget stop. After the approved repair succeeds,
explicitly authorized sampled-stop continuation can use the existing public
`continue` operation. Do not treat an administrative repair as permission for
the original execution to run.
The administrative-only result is `applied`, with the actual changes and
`recovery_event_id`. It does not claim that continuation occurred. Adding zero
minutes does not clear a budget stop when continuation is requested either.

A retained retired alias can request a positive Ticket budget increment with
`--no-resume` and without `--restore-active`. The same reviewer and caller
authority checks apply. Approval changes only the retained budget; it neither
restarts Sessions nor reverses retirement. Main can then separately use
`continue --ticket-id <id> --budget-only --caused-by-event-id <recovery_event_id>`
and ordinary swarm dispatch with explicit first instructions for a new member.
Original accounting, stops and identities remain retained.

Recovery within existing spending authority does not need another approval
merely because a parent interrupted the Session. Additional spending requires
the selected human or automatic reviewer. The same recovery operation requests
that decision and executes after approval; callers do not transport a proposal
or invoke a second apply command. A rejected or failed review leaves the
unapproved repair unapplied. Causal references and caller-supplied claims are
not approval tokens.

For Codex, configured HTTP review uses the existing `codex.approval` settings,
including role overrides. Managed Codex executions configured for human review
use the existing pending request and reply channel. Plain CLI calls require
the selected HTTP route; other local hosts must bind an actual selected reviewer.
A host-bound reviewer must actually be available; selecting a
native reviewer without a callable host route does not grant approval. HTTP
review is not evidence that Codex's native automatic reviewer ran. Do not
replace an unavailable route with a temporary script or internal Python call.

Read the actual recovery result, whether review was required or existing
authority was reused. `stale` means the retained snapshot no
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
request through the same recovery operation. Existing authority,
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

## Return an accepted artifact to integration after recovery

When authorized recovery work leaves the committed artifact unchanged, the
original executing Session can write its new verification evidence and use
`submit-result` with the same commit. Its actual parent accepts that new
submission ID with `decide-result`, then the accepted result can be integrated
through `graphtraj ticket integrate`. The original submission and acceptance
remain historical facts. Do not decide the old submission a second time or
manufacture an empty commit, a rejection or another Round to change the state.
A new submission describes completed recovery work; it does not waive its
required verification, ownership or budget constraints.

## Adopt retained results

A genuinely assigned successor may submit an unchanged committed artifact as its
own handoff result. Credit the original authors and the valid evidence relayed by
its actual parent; write its own assigned report before submission. A new commit
or repeated implementation is not required. Its actual parent decides that new
submission, while the old submission and original Session relationships remain
unchanged. This does not grant control of old children or access to their private
reports, and is not permission to claim another Agent's work or checks as its own.

## Stop and replace

Retirement releases an Agent from its task and removes its active mapping while
retaining its native Session, evidence and original parent relationships. Use
the public `retire` operation only after the target and its entire descendant
subtree have stopped. Active or unconfirmed execution prevents retirement;
retirement does not implicitly interrupt work or delete the shared Worktree.
An interrupted or failed execution alone is not retirement.

When the caller's relationship requires approval, the public retirement
operation obtains the selected Runtime review and executes only after approval.
Callers do not run an internal Python bridge or supply an approval flag. A
refusal or review error leaves that retirement unapplied. Cleanup and replacement
use the same retirement operation and retain completed steps if a later step
fails; retry through their public entries without reviving retired members.

Ask the direct child to stop when possible; interrupt an out-of-control
descendant subtree through Runner when needed. That control exception does not
permit cross-level messages, approvals or replacement. Confirm the target and
all descendants have stopped before replacing it. Replacement requires the
actual direct parent or user; preserve the Runtime's native approval mechanism
when the requested relationship requires it. An actor flag grants no authority.

A replacement root retains the original owning host's notification connection.
Replacement composes retirement and the existing role registration operation.
If registration fails after retirement, handle the reported partial outcome
through the public retry path; do not resume the retired Agent or claim that
replacement succeeded. Ticket cleanup uses the same retirement operation before
removing an unused Worktree and branch.

If that root has no recorded connection, replacement uses the caller's existing
host binding or the Runtime's actual host context when available. The replacement
is a new entity; it preserves the old Session and records. Use the public
replacement operation in the actual owning Main context, then verify that its
resulting events reach and are processed by Main. A successful replacement call
or a hook allowing Main to wait does not prove later notification delivery.

Use public control/replacement operations and report a missing capability through
the direct parent. Retain prior Sessions and useful evidence and give the new
executor the accepted scope, committed candidate and concrete remaining work.
Commit authorized tracked changes before handoff or turn end; mark unfinished
work honestly. A commit is neither acceptance nor permission for more time.
