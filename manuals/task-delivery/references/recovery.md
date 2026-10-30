# Recovery decisions

Identify the failing action, its concrete cause and the direct parent able to
address it. A dispatcher corrects its own scope/input errors. The responsible
executor handles implementation defects through its parent. A provider failure
is not failed work; normal tool, watchdog and approval waits are not failures.

Keep one existing execution. Send changed instructions through its live channel;
after an actual failure ends execution, use the supported public continuation
operation with the causal event. MCP `agents` supplies Agent status and control;
`tasks` supplies Task participation and delivery state. An installed legacy
Task control route is a defect, not a second supported Agent interface.
`session_reports` exposes only directly owned reports. Follow the delivery
guide's MCP-first rule; CLI examples below are fallback syntax only. Apply the
project's shared polling limit. A send acknowledgement is not completion. Never wake a second Driver to
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

Use MCP `approved_recovery`
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

A retained retired alias can request a positive Task budget increment with
`--no-resume` and without `--restore-active`. The same reviewer and caller
authority checks apply. Approval changes only the retained budget; it neither
restarts Sessions nor reverses retirement. Main can then separately use
`continue --task-id <id> --budget-only --caused-by-event-ids '["<recovery_event_id>"]'`
and ordinary swarm dispatch with explicit first instructions for a new member.
Original accounting, stops and identities remain retained.

Recovery within existing spending authority does not need another approval
merely because a parent interrupted the Session. Additional spending requires
the selected human or automatic reviewer. The same recovery operation requests
that decision and executes after approval; callers do not transport a proposal
or invoke a second apply command. A rejected or failed review leaves the
unapproved repair unapplied. Causal references and caller-supplied claims are
not approval tokens.

For a direct Codex MCP client advertising form elicitation, `approved_recovery`
requests sensitive, synchronous native automatic review through that same
connection. It keeps the original call pending and requires the matching
`auto_review` response before applying the repair. Refusal, cancellation,
disconnect or an unavailable reviewer applies nothing. There is no separate
approval token or apply command. Reload the adopted MCP server through the
host's normal path before using new server behavior; changing disk files alone
does not update an already running server.

For Codex, configured HTTP review uses the existing `codex.approval` settings,
including role overrides. Managed Codex executions configured for human review
use the existing pending request and reply channel. Plain CLI calls require
the selected HTTP route; forwarded managed calls retain their owner's reviewer
binding, and other local hosts must bind an actual selected reviewer.
A host-bound reviewer must actually be available; selecting a
native reviewer without a callable host route does not grant approval. HTTP
review is not evidence that Codex's native automatic reviewer ran. Do not
replace an unavailable route with a temporary script or internal Python call.

For a Codex stdio MCP server using HTTP review, forward the configured key's
environment-variable name through `mcp_servers.<name>.env_vars`; a variable
available in your shell is not necessarily available to the MCP process.
Keep key values out of configuration and reports. After changing the host
configuration, use its normal reload or restart path and verify actual adoption.
See [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
An `api_key_env` error reports only the variable name and presence/nonempty
booleans; it means review failed before sending an HTTP request.

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
agent-runner continue --task-id <id> --caused-by-event-ids '["<authorization-or-decision-event>"]'
```

The default resumes existing roots with a generic continuation message. A revised
Task or causal event alone does not deliver new execution limits. For an
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
Read retained reports through the public report operation without waking the
Agent. If a new message is necessary, use `agents` within existing authority.
Report collection grants no implementation window and
does not bypass a manual subtree stop. Use the selected Runtime's actual notification channel and report a delivery failure through the caller.

## Continue after a conflict resolver ended

A resolver with a Session can end before submitting, through interruption, failure
or a stop. Its staged work stays in dev. Repeating the original `task_integrate` call
while it still runs changes nothing. Choose by the Task's state:

| State | Continuation | Conditions and authorization |
| --- | --- | --- |
| `resolving-integration` | Plain `approved_recovery` on the resolver | The direct parent; the resolver's subtree has stopped; it was not replaced |
| `resolving-integration`, new resolver wanted | Repeat the original `task_integrate` call, which escalates; then use the next row | The caller that may integrate; the resolver has ended without a submission |
| `escalated`, new resolver | `task_integrate` with `resolve_conflict` and `role` | The conflict's original parent; every earlier resolver has confirmably ended; same candidate, dev commit and validation command; role_tree, Task authority and budget apply at launch |
| `escalated`, same Session | `approved_recovery` with `restore_active` on the resolver | The direct parent; the resolver's subtree has stopped; it was not replaced |
| `escalated`, committed result | `task_integrate` with `confirmed_commit` | The caller that may integrate; same validation command; no work starts |

Resuming the resolver of an `escalated` integration without `restore_active` is
refused and records nothing. `restore_active` reopens the conflict assignment only
from these two states. The resumed Session keeps its identity and stop record, whose
`resumed` flag records the authorized continuation. A parent's reply, native
approvals, the stop checks and the budget still apply. `additional_minutes` still
needs the selected reviewer.

A new resolver is a new entity working on the staged merge. It may use another role
and diagnosis. The earlier resolver keeps its Session, mapping, Team seat and stop
record, but it loses the assignment once the dispatch is attempted, even if that
launch fails: `send` and `approved_recovery` refuse it, including a budget-only
recovery, which can use another member of the Task. Its parent can still collect its
reports. A failed launch is continued by dispatching again.

If the continued resolver also ends without submitting, repeating the original call
escalates again with the same conflict facts. A submission and its acceptance
complete through the ordinary path.

## Return an accepted artifact to integration after recovery

When authorized recovery work leaves the committed artifact unchanged, the
original executing Session can write its new verification evidence and use
MCP `submit_result` with the same commit. Its actual parent accepts that new
submission ID with MCP `decide_result`, then the accepted result can be integrated
through MCP `task_integrate`. The original submission and acceptance
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

A Native Process can exist before its Session is ready. Runner retains its owned
execution control during this interval; the existing `interrupt` operation can
stop an attributed start still owned by a live Worker. A Worker PID or an empty
Trace alone does not establish Runtime termination. Cleanup of a failed allocation
still requires verified attribution and a confirmed terminal outcome; historical
records missing that proof remain refused.

Retirement releases an Agent from its task and removes its active mapping while
retaining its native Session, evidence and original parent relationships. Use
the public `retire` operation only after the target and its entire descendant
subtree have stopped. Active or unconfirmed execution prevents retirement;
retirement does not implicitly interrupt work or delete the shared Worktree.
An interrupted or failed execution alone is not retirement.

When the caller's relationship requires approval, the public retirement
operation obtains the selected Runtime review and executes only after approval.
Callers do not run an internal Python bridge or supply an approval flag. A
refusal or review error leaves that retirement unapplied. Replacement uses the
same retirement operation and retains completed steps if a later step fails;
retry through its public entry without reviving retired members.

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
replacement succeeded.

Task cleanup is separate from Agent retirement. After validated integration,
it removes the clean Task Worktree and merged branch, moves unstarted allocations
into their retained Traces, and returns started members as `standby_aliases`.
Their identities and native Sessions remain available for continuation.
Retire a member separately only when its removal is authorized. A later
reports-only continuation uses the original Session and recreates its recorded
cwd when needed; this empty directory does not restore removed source files.

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
