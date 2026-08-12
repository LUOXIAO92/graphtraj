---
status: accepted
---

# The Runner dispatches only Main-selected ticket batches

Engineer dispatch crosses a narrow Agent Runner seam exposed as
`agent-runner`. Main selects the tickets and logical Engineer roles, then passes
logical task objects rather than Runtime commands. Main does not supply branch
names, physical worktree paths, profile or configuration paths, or
Runtime-specific syntax.

A launch uses `agent-runner --batch-input <yaml-file>`. `batch` means only that
one YAML file may contain multiple task objects; it does not imply DAG
discovery, scheduling, transactionality, or atomic execution. The top level
contains one `run_id`; each task contains:

- `ticket_id`
- `ticket_name`
- logical Engineer `role`
- canonical `ticket_file` reference
- optional plain-text `instruction`

The Runner attempts exactly the objects supplied and no others. It does not
query the tracker, inspect the DAG, discover a ready frontier, add omitted
tickets, or change Main's role selection.

`ticket_file` is either a canonical local ticket or a complete local snapshot
materialized by the target project's tracker binding. The Runner verifies that
the path resolves to a readable regular file, reads it without modifying it,
and passes its contents to the Runtime Adapter as the Engineer's initial task.
That ticket contains the complete task definition, including requirements,
acceptance criteria, dependencies, and references to specs, ADRs, and design
material; it is not a second dispatch document written by Main. The Runner
neither copies the file into a worktree nor makes the Engineer access its source
path, and it never creates, rewrites, or deletes the canonical ticket or
snapshot.

The optional `instruction` is a concise delivery note for a temporary priority,
environment constraint, evidence reference, or point to check. It cannot
restate the ticket, change scope or dependencies, add acceptance criteria, or
become a detailed technical plan. Material changes return to spec or ticket
planning. This is Skill guidance, not a machine-enforced semantic schema.
The Runtime Adapter appends the note to the canonical ticket content when
constructing the Engineer's initial task; it does not create or persist a
second task specification.

`ticket_id` is the stable identity supplied by the target project's tracker
binding. It is stable within that project and otherwise opaque, allowing local
keys, GitHub repository numbers, or GitLab project IIDs. It is 1-32 ASCII
characters drawn from letters, digits, `.`, `_`, and `-`. `ticket_name` is a
non-identity, human-readable label fixed for the Delivery Run; it is 1-64 ASCII
characters in lowercase kebab-case. The Runner never truncates either value.
Different IDs may share a name, although the Delivery State Agent should choose
distinguishable names.

Complete input preflight rejects invalid YAML and repeated ticket IDs before
starting any task. After preflight, launches are independent rather than
transactional: one failure does not stop or roll back Engineers already
started. The process returns one compact YAML result covering every requested
task and exits zero only when every launch succeeded.

Every task result includes its ticket ID, ticket name, logical role,
`launch_status`, worktree path, and ticket-file path. Success also returns a
semantic session `alias` and raw Runtime session; failure instead returns a
structured error code and message. Launch status is transport evidence, not a
Delivery State Agent ticket status. The command returns after starting the
Engineer processes, so V1 does not require streaming output or JSONL.

The Runner resolves logical roles through an allowlisted registry, provisions
or recovers the ticket branch and worktree, launches the Runtime Adapter, and
collects transport results. Runtime selection and command construction stay
behind [ADR 0007](0007-hide-runtime-cli-details-behind-adapters.md), while
follow-up session operations use [ADR 0008](0008-address-engineer-sessions-by-alias.md).

## Considered options

- A formal normalized dispatch packet was rejected because Engineers already
  have the accepted ticket and its referenced planning material.
- Using a full tracker title as identity was rejected because identity and
  readable navigation are separate concerns.
- Using `instruction` as a second task specification was rejected because
  complex delivery scope belongs in the canonical ticket.
