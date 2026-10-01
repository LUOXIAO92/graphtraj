# Delivery command inputs

Use block-style YAML for Ticket command inputs. Read current Ticket state before
updating it; commands validate and persist the supplied decisions.

## Register a missing Ticket

Run `graphtraj ticket register --ticket-file <issue.yml>` with:

- `ticket_id`: stable Ticket ID.
- `ticket_name`: Ticket name.
- `source`: accepted GitHub Issue URL.
- `title` and `body`: complete accepted Ticket, including acceptance criteria.
- `dependencies`: prerequisite Ticket IDs, registered first.

Existing Tickets use their `current_definition`; `ticket.md` is the immutable
initial definition. Do not register an existing Ticket again.

## Record readiness

Run `graphtraj ticket update --state-file <state.yml>` for a selected pending
Ticket whose prerequisites have validated integration. Supply:

- `ticket_id` and `status: ready`.
- Current `active_team_ordinal`, `worktree`, `branch`, and `current_candidate`.
  Preserve these values; all four are null for a new Ticket.
- `caused_by_event_ids` and `evidence_refs` supporting the authorized caller's readiness decision.

## Revise the graph

Run `graphtraj ticket revise --revision-file <revision.yml>` with:

- `product_preserving: true`.
- `caused_by_event_ids` and Harness-root-relative `evidence_refs`.
- `tickets`: every affected full definition, each containing `ticket_id`,
  `ticket_name`, `source`, `title`, `body`, `dependencies`, `active`, and
  `replaced_by`.

Keep existing GitHub identities stable; new nodes refer to accepted GitHub
Tickets. Include dependent definitions whose edges change. Deactivate removed
or superseded Tickets and identify replacements where applicable. Preserve
accepted behavior and acceptance coverage across the complete correction.

## Submit and decide a result

The executing Session commits its file results, then records the exact version:

```text
agent-runner submit-result --commit <commit> --result-ref <result-path> --completion <statement> [--evidence-ref <evidence-path>] [--unresolved <remaining-work>]
```

Use the Session's assigned report/result destinations and actual task binding.
Keep unresolved work explicit. A report does not substitute for the submission.

The authorized caller assesses that submitted version and records its decision:

```text
agent-runner decide-result --submission-id <submission-event> --commit <commit> --decision accepted|rejected --reason <reason> --evidence-ref <evidence-path>
```

Use the returned submission identity and real caller authority; a role name or
report filename grants neither authority nor completion. Preserve previous
submissions, decisions and evidence. A missing acceptance fact must come from
its authorized owner, not inferred text or direct state-file edits.

## Observe the owning host

From a bound root Agent, `agent-runner parent-status` reads its recorded host
parent's activity and latest turn metadata once. The shared `parent_status`
operation takes `timeout_seconds`, defaulting to zero. A finite positive value,
also available as CLI `--timeout-seconds`, waits for native idle events up to
that duration. Keep the wait within the execution budget. No alias, recipient
or connection override is accepted, and no input is sent to the parent.
Timeout and observation errors are returned as failures, not successful idle
observations. Main and children without a recorded Runtime host parent cannot
use this operation to choose another Session to observe.

## Approved recovery

Use the alias of the original Session with the exact repair reason, permitted
work and continuation instruction:

```text
agent-runner recover <alias> --reason <reason> --instruction <continuation> --allowed-scope <allowed-work> --forbidden-scope <excluded-work> --caused-by-event-id <actual-authority-event> [--additional-minutes <increment>] [--restore-active]
```

Repeat `--caused-by-event-id` for additional actual causal references. The
shared `approved_recovery` operation uses `alias`, `reason`, `instruction`,
`allowed_scope`, `forbidden_scope`, `caused_by_event_ids`, optional
`additional_minutes` and optional `restore_active` with the same semantics.

The initial `requires-native-approval` result contains a concrete native
execution request. Submit that exact request to the selected Runtime's existing
human or automatic approval mechanism. Receiving it, or citing an authority
event, is not permission to execute it by another route. No repair is applied
before the approved execution runs.

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
[recovery decisions](recovery.md#recover-through-the-selected-native-approval)
for retained history, native rejection and changed-state handling.

## Integrate accepted files

```text
graphtraj ticket integrate --ticket-id <id> -- <validation-command> <arguments>
```

Use the task's necessary validation and the project's assigned executor. For a
retained committed integration escalation, the existing operation validates the
accepted candidate, retained ancestry and original validation command before
adopting the result. Keep the original argv and causal/stop history; it is not a
shortcut for missing acceptance or failed validation. Use `--resolve-conflict`
only for an actual conflict requiring a specialist.

After successful integration use `agent-runner cleanup --ticket-id <id>` and
regenerate the task graph. These operations retain the original task evidence.

For a retained integration conflict, select the permitted role explicitly:

```bash
graphtraj ticket integrate --ticket-id <id> --resolve-conflict '<diagnosis>' --role <role-reference> -- <validation-command> <arguments>
```

`--role` also accepts the same inline YAML role definition as swarm. The role's
configured instructions, Skills, reports and access apply. The selected member
commits and submits its result, its actual parent uses `decide-result`, and the
integrator repeats the original validation command to complete integration. A
Session's final message cannot accept a result.

To adopt an already committed escalated integration without starting work, inspect
the changed contents and supply `--confirm-resolution <full-commit>` with the
original validation command. This confirms that exact version under the caller's
task authority; it does not resume or reset a stopped execution budget.
