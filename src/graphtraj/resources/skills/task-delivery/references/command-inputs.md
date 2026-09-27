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
- `caused_by_event_ids` and `evidence_refs` supporting Main's readiness decision.

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
