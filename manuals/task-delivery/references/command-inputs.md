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
| Read or search another project Session's history | `agents`: `session_read` (the last 5 conversation events by default; `start`/`stop` slice, `content`, `search`). `tasks` `session_read` is transitional and forwards to it |
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
`current_definition`. Every definition version, including the initial text, is
a read-only file `definitions/<event_id>.md` in the Task directory, named by the
Worldline event that recorded it (`task-registered` for the initial text,
`task-graph-revised` for a revision). Event IDs are capture times such as
`20261122T021401.150004+0900`, so names sort oldest to newest. Read the current
version through `current_definition` in `task.yml` or `task_graph --details`,
never by choosing a file name. Do not register an existing Task again.

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
The conversion also gives each converted first definition its versioned name
as described below.

### Rename unversioned Task definitions

State written before versioned names keeps each Task's initial text in
`task.md`; Task reads refuse such a Task and name this command. Run
`graphtraj migrate-task-definitions --preview` from the Harness Project Root,
then the same command without `--preview` after project writers stop. Each
`task.md` moves unchanged and read-only to `definitions/<event_id>.md`, using
the Worldline event that created the Task, and `current_definition` is updated
where it named `task.md`. One `task-definitions-renamed` event maps each old path
to its new path, so earlier events that cite `task.md` still resolve. Changed
files and the Worldline are first copied under `.graphtraj/backups`. Running it
again after success reports that nothing remains. A Task without a matching
creation event, with irregular definition files or links, or without
`task.yml`, stops the command before any change.

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
Exception: a Session launched with read Worktree access (`worktree_access: read`,
for example an investigator) changes no file, so it may name its own assigned
report, already written with `submit_report`, in `result_refs` in the same
`.state/...` form, alone or beside committed files. Runner takes the access from
the Session's own records: the explicit value in its launch record (DSH
`sandbox: read-only` counts as read), otherwise the role preset its mapping
names; a missing or inconsistent record counts as write. It also checks the
assignment and that the report exists, and retains a copy in the
submission's `evidence_refs`. The commit is still the Worktree `HEAD`. A Session
with write access must name committed files.

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
If the Task Worktree is checked out on another branch that contains the accepted
candidate, name it in `worktree_branch` (CLI `--worktree-branch`); the clean,
integrated Worktree is removed and both branches are kept.

For a retained integration conflict, select the permitted role explicitly:

```bash
graphtraj task integrate --task-id <id> --resolve-conflict '<diagnosis>' --role <role-reference> -- <validation-command> <arguments>
```

`--role` also accepts the same inline YAML role definition as swarm, which refuses
`api_key_env` and `pass_env`: select `connection: runtime/provider/model` instead. The role's
configured instructions, Skills, reports and access apply. The call returns once
the member is launched, with the Task in `resolving-integration`; the member's
notices and permission requests reach its parent, which answers them as for any
child. The selected member commits and submits its result, its actual parent uses
MCP `decide_result`, and the integrator repeats the original validation command to
complete integration. If the member ends without submitting a result, that repeated
call escalates the integration instead. A Session's final message cannot accept a
result.

When the member ended before submitting, continue by the Task's state. See
[recovery decisions](recovery.md#continue-after-a-conflict-resolver-ended):

- `resolving-integration`: resume it with plain `approved_recovery`. To dispatch a
  new member instead, first repeat the original call, which escalates.
- `escalated`: resume it with `approved_recovery` and `restore_active`, or dispatch a
  new member with `--resolve-conflict` and `--role`. The role and diagnosis may
  change once every earlier member has ended.
- `escalated` with a committed result: adopt it as below.

To adopt an already committed escalated integration without starting work, inspect
the changed contents and supply `--confirm-resolution <full-commit>` with the
original validation command. This confirms that exact version under the caller's
task authority; it does not resume or reset a stopped execution budget.

## Back up Tasks to Issues

The local Task is the original, authoritative record. Backing it up to an Issue
platform is optional and one-way. The current adapter is GitHub. Use MCP `tasks`
feature `task_backup` with the local Task ID and `repository` as `owner/name`;
`host` defaults to `github.com`. Requests go through the installed `gh` login or
`GH_TOKEN` / `GITHUB_TOKEN`. Registering a Task needs no Issue, an Issue number is
not the Task ID, and closing an Issue is not local acceptance or integration.

Choose the repository per Task and call. The project's state keeps one mapping
per Task, host and repository with a creation marker in the Issue body; repeat
the call to retry or update the same Issue, including one whose creation response
was lost. The Issue holds the Task title, explicit definition and state fields
only, and is closed when the Task is integrated, superseded or cancelled. A Task
with children also shows integrated / required child counts and a dependency
diagram with a legend; a child kept in another repository shows `owner/name#N`.

The result `outcome` is `created`, `updated`, `unchanged`, `conflict` or `failed`.
`failed` records the error in the mapping and leaves local Tasks unchanged;
repeat the call. `conflict` means the Issue changed since the last backup: remote
edits are reported in `differences` with a `remote_digest` and never imported.
Revise the local Task through Task operations when the evidence warrants it, then
repeat with `confirm_remote` set to that digest. It applies only to that exact
remote copy.

Parent-child relations become GitHub Sub-issues between mapped Issues, reported
in `hierarchy`:

- `linked`: the child Issue is placed under its parent's Issue.
- `unchanged`: it already was.
- `moved`: it was under another mapped Issue and now follows the local parent.
- `unlinked`: the local Task has no parent, so its link to a mapped remote parent
  is removed.
- `other-parent`: the remote parent maps to no Task; reported, never changed.
- `pending`: the parent's Issue is not resolved; nothing is written.

A related Task's Issue comes from its mapping on the same host in the backed-up
repository, otherwise its only mapping on that host, once that mapping has an
Issue; both sides must resolve each other this way. A Task mapped only on
another host, or in two or more other repositories, is not resolved, so keep each
Task backed up to one repository. An Issue number in another repository comes
with `parent_repository`, `child_repository`, `previous_parent_repository` or
`remote_parent_repository`. Unmapped children are not published automatically and
unresolved children are omitted from a parent's `hierarchy`. Read `hierarchy`
rather than inferring links from the Issue body.
