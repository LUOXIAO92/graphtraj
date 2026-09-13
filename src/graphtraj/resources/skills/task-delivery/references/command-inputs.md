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
