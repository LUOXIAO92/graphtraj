# Delivery operation inputs

Use MCP `agents` / `tasks`, following the delivery guide. Describe the selected
feature with `schema: true`, then execute with structured arguments. The
installed schema determines supported fields. Agent communication and execution
belong to `agents`; Task policy, participation and delivery belong to `tasks`.
An installed duplicate control route is a defect, not an ownership rule. Read
current Task state before updates. CLI examples below apply only when that
MCP entry is unavailable or failing; use block-style YAML for fallback files.

| Outcome | MCP feature |
| --- | --- |
| Register / inspect / revise Tasks | `task_register` / `task_graph` / `task_revise` |
| Record readiness / complete a non-file Task | `task_update` / `task_complete` |
| Dispatch Task participation | `tasks`: `swarm` |
| Communicate / observe Agent hierarchy | `agents`: `send` / `status` |
| Wait / interrupt / resume / retire Agents | Discover the needed `agents` feature |
| Handle native Agent permission requests | `agents`: `requests` / `reply` |
| Deliver / read reports | `submit_report` / `session_reports` |
| Submit / decide a result | `submit_result` / `decide_result` |
| Repair Task authorization / accounting | Discover the needed `tasks` recovery feature; Agent execution remains in `agents` |
| Integrate / clean up | `task_integrate` / `cleanup` |

Discover migration and host-maintenance capabilities when needed. An absent MCP
feature can justify its public CLI fallback; other operations still use MCP.

## Register a missing Task

Execute MCP `task_register` with:

- `task_id`: stable Task ID.
- `task_name`: Task name.
- `source`: a nonempty reference to the accepted work, such as `local:task/12`
  or an external Issue URL. It does not determine the local Task ID.
- `title` and `body`: complete accepted Task, including acceptance criteria.
- `dependencies`: prerequisite Task IDs, registered first.
- `schema_version: 2`, `parent_id`, `disposition`, `replaced_by`, and
  `retirement_reason`: explicit task relationships and retirement facts.
  `parent_id: null` means a confirmed project root. Active tasks use
  `disposition: active`, `replaced_by: []` and `retirement_reason: null`.
  Superseded tasks name their direct replacements and reason; cancelled tasks
  have a reason and no replacements. Both retain their parent.

Describe MCP `task_graph` for the common task projection schema.
The default graph expands open work in the caller's Task, or the whole project
for Main, and folds completed history into summaries. Use `--view full` to list
all Tasks, `--task-id <id>` to select another scope, or `--details <id>` to include
full definitions and execution facts.
Children, progress and `active` are derived. Existing Tasks use their
`current_definition`; `task.md` is the immutable initial
definition. Do not register an existing Task again.

For a project retaining the old Ticket format, complete the explicit migration
before adopting the Task interfaces. Keep the old installation with its old data
until the cutover; installing a CLI alone does not upgrade an already-running
host. Normal Task operations use the current format rather than old field or
command aliases. Migration must preserve actual relationships; an unknown parent
cannot be silently changed to a confirmed root.

### Migrate a retained Ticket project

Use the candidate's `graphtraj migrate-tickets` command on a representative
project copy first, then verify the converted objects and relationships through
the new public Task entries. The command converts explicit structural fields,
event names and state paths, including `state/tickets` to `state/tasks`,
`ticket.yml` to `task.yml`, and `ticket.md` to `task.md`. User text and native
Runtime content retain their original meaning.

Stop project writers before the actual cutover. The command retains a backup
under `.graphtraj/backups` and restores the previous data if conversion fails.
Keep the matching old installation available with that backup. A successful
sample is not a full-project migration or permission to switch active Workers;
complete the project's planned full-data validation and coordinated adoption.
If an old definition lacks required relationship facts, resolve those facts from
the retained evidence and record them through the old installation's public
revision operation before conversion. Migration must report unresolved IDs and
leave the old data usable rather than inventing parents or treating them as roots.

## Record readiness

Execute MCP `task_update` for a selected pending
Task whose prerequisites have validated integration. Supply:

- `task_id` and `status: ready`.
- Current `active_team_ordinal`, `worktree`, `branch`, and `current_candidate`.
  Preserve these values; all four are null for a new Task.
- `caused_by_event_ids` and `evidence_refs` supporting the authorized caller's readiness decision.

## Revise the graph

Execute MCP `task_revise` with:

- `product_preserving: true`.
- `caused_by_event_ids` and Harness-root-relative `evidence_refs`.
- `tasks`: every affected full definition. Supply the registration
  fields above plus the observed `current_definition` (`null` only for a new
  task). Preserve stable IDs and direct replacement history.
- `reopen_task_ids`: explicitly include completed tasks and affected ancestors
  that must reopen when required work or relationships change.
- Optional `dry_run: true` (or CLI `--dry-run`) validates without writing.
- A changed `execution_budget` states its reason as
  `execution_budget.revision_reason` in that task's `body` front matter;
  without it the revision is rejected:

  ```yaml
  ---
  execution_budget:
    estimated_minutes:
      total: 105
    revision_reason: 45 minutes moved to Task 343 by the recorded decision.
    # remaining existing budget fields unchanged
  ---
  ```

Include definitions whose relationships change and evidence for parentage,
retirement and scope changes. A stale definition fails instead of overwriting
newer work. Apply confirmed relations through the native revision, preserving
original definitions and delivery history.

## Complete a task without a file result

Use MCP `task_complete` for an active v2 task with its own accepted outcome and no
file-delivery history. Supply `task_id`, observed `current_definition`, a
nonempty `reason`, `caused_by_event_ids`, existing `evidence_refs`, and
`cancelled_scope`: a map of each required cancelled task ID to the reason that
scope is no longer required, or `{}` when none applies.

The operation checks required child and dependency results through replacement
chains. Child completion alone does not accept the parent. Tasks with a Team,
worktree, branch, candidate or file-delivery history continue through submission,
acceptance and integration below; `complete` cannot replace those steps.

## Submit and decide a result

The executing Session commits its file results, then uses MCP `submit_result`
to record the exact version. CLI fallback:

```text
agent-runner submit-result --commit <commit> --result-ref <result-path> --completion <statement> [--evidence-ref <evidence-path>] [--unresolved <remaining-work>]
```

Use the Session's assigned report/result destinations and actual task binding.
Keep unresolved work explicit. A report does not substitute for the submission.
For versioned results, `result_refs` must name files or directories present in
the submitted commit. Put retained reports, test logs and installation evidence
in `evidence_refs`; a report stored outside Git is not a committed result path.

Within a managed Session, use MCP with its prepared caller context. If that
entry is unavailable or fails, the public CLI must use the host connection
prepared by the Runner. Both paths verify the same caller and authority.
This does not permit direct access to
private control records or caller-selected identity. A refused or broken prepared
connection must not fall back to executing the operation with broader authority.
Installing a new CLI alone does not establish adoption by an existing Session;
use supported Runner preparation and verify an actual call in that Session.

The authorized caller assesses that version and uses MCP `decide_result`
to record its decision. CLI fallback:

```text
agent-runner decide-result --submission-id <submission-event> --commit <commit> --decision accepted|rejected --reason <reason> --evidence-ref <evidence-path>
```

Use the returned submission identity and real caller authority; a role name or
report filename grants neither authority nor completion. Preserve previous
submissions, decisions and evidence. A missing acceptance fact must come from
its authorized owner, not inferred text or direct state-file edits.

## Observe the owning host

From a bound root Agent, MCP `parent_status` reads its recorded host
parent's activity and latest turn metadata once. The shared `parent_status`
operation takes `timeout_seconds`, defaulting to zero. A finite positive value,
also available as CLI `--timeout-seconds`, waits for native idle events up to
that duration. Keep the wait within the execution budget. No alias, recipient
or connection override is accepted, and no input is sent to the parent.
Timeout and observation errors are returned as failures, not successful idle
observations. Main and children without a recorded Runtime host parent cannot
use this operation to choose another Session to observe.

## Approved recovery

Use MCP `approved_recovery` with the original Session alias, exact repair
reason, permitted work and continuation instruction. CLI fallback:

```text
agent-runner recover <alias> --reason <reason> --instruction <continuation> --allowed-scope <allowed-work> --forbidden-scope <excluded-work> --caused-by-event-ids '["<actual-authority-event>"]' [--additional-minutes <increment>] [--restore-active] [--no-resume]
```

`--caused-by-event-ids` takes one JSON array of strings, such as
`'["event-a", "event-b"]'`, for all actual causal references. The
shared `approved_recovery` operation uses `alias`, `reason`, `instruction`,
`allowed_scope`, `forbidden_scope`, `caused_by_event_ids`, optional
`additional_minutes`, `restore_active` and `resume` with the same semantics.
`resume` defaults to true; CLI `--no-resume` sets it to false for a repair that
must leave the original execution stopped.

This one operation obtains any required human or automatic review and then
executes the approved repair. Recovery within existing spending authority,
including an ordinary parent interruption, does not require another approval.
Additional spending requires the selected reviewer; refusal or review failure
does not apply the unapproved repair. There is no separate `recover-apply`
command, caller-supplied approval flag or proposal execution step. Codex HTTP
review reuses `codex.approval`. Managed Codex executions configured for human
review use the existing request/reply channel. Plain CLI calls require the
selected HTTP route; other local hosts must bind an actual selected reviewer.
An unavailable selected reviewer is reported rather than bypassed.

For administrative repair only, use `--restore-active --no-resume` without a
time increment. This restores the retained delivery state while preserving the
budget stop. Restoring delivery state does not itself authorize execution;
use the existing public budget continuation only with explicit authorization.
An `applied` result reports the repair and its `recovery_event_id`; it does not
mean the Session resumed. A zero-minute administrative repair never clears a
budget stop, even if continuation was requested.

Keep the returned applied changes and `recovery_event_id`. A `stale` result
does not apply an outdated proposal. For `resume-stale` or `resume-failed`,
inspect which changes were already applied and the actual continuation failure.
Retry an applied recovery using only the original alias and its event:

```text
agent-runner recover <alias> --retry-event-id <applied-recovery-event>
```

The corresponding tool arguments are `alias` and `retry_event_id`; do not add
another time increment or repair request to that retry. `resumed` reports the
continuation outcome, not that the task is complete. See
[recovery decisions](recovery.md#recover-with-the-selected-reviewer)
for retained history, native rejection and changed-state handling.

## Integrate accepted files

Use MCP `task_integrate`. CLI fallback:

```text
graphtraj task integrate --task-id <id> -- <validation-command> <arguments>
```

Use the task's necessary validation and the project's assigned executor. For a
retained committed integration escalation, the existing operation validates the
accepted candidate, retained ancestry and original validation command before
adopting the result. Keep the original argv and causal/stop history; it is not a
shortcut for missing acceptance or failed validation. Use `--resolve-conflict`
only for an actual conflict requiring a specialist.

After successful integration use MCP `cleanup` with the Task ID and
regenerate the task graph. These operations retain the original task evidence.

For a retained integration conflict, select the permitted role explicitly:

```bash
graphtraj task integrate --task-id <id> --resolve-conflict '<diagnosis>' --role <role-reference> -- <validation-command> <arguments>
```

`--role` also accepts the same inline YAML role definition as swarm. The role's
configured instructions, Skills, reports and access apply. The selected member
commits and submits its result, its actual parent uses MCP `decide_result`, and the
integrator repeats the original validation command to complete integration. A
Session's final message cannot accept a result.

To adopt an already committed escalated integration without starting work, inspect
the changed contents and supply `--confirm-resolution <full-commit>` with the
original validation command. This confirms that exact version under the caller's
task authority; it does not resume or reset a stopped execution budget.
