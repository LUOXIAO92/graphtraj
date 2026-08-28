---
status: accepted
---

# Address Agent Runtime sessions by semantic alias

> **Partial supersession:** [ADR 0025](0025-preserve-a-time-normalized-delivery-worldline.md)
> requires the complete Agent event stream for each turn to be preserved in
> Run state before cleanup removes the live alias and its transport storage.

Main controls launched Engineer and Reviewer sessions through Runner aliases
rather than shell job IDs, opaque Runtime session IDs, or Runtime-specific
resume commands. The Runner exposes three transport operations: `status`,
`send`, and `interrupt`.

Although a successful launch result includes the raw Runtime session as opaque
evidence, these operations accept the alias only. Main does not interpret or
feed the raw identifier back to the Runtime.

- `status` observes Runtime activity without choosing or changing a ticket
  status. For the addressed alias, a successful result is `running` while its
  turn is active or `idle` when it has no active turn and is eligible to be
  resumed by `send`.
- `send` delivers a concise follow-up through the Adapter's live-input or
  resume mechanism.
- `interrupt` requests that the current Runtime execution stop while
  preserving the alias, mapping, branch, and Ticket Worktree when recovery is
  possible.

Their V1 command forms are:

```text
agent-runner status <alias> [<alias>...]
agent-runner send <alias> --instruction <text> \
  --caused-by-worldline-seq <seq> [--caused-by-worldline-seq <seq> ...]
agent-runner interrupt <alias>
```

`status` accepts one or more aliases explicitly supplied by Main so one call
can inspect a dispatched frontier without making the Runner discover sessions
from a Delivery Run. `send` and `interrupt` each address one exact alias. There
is no run-wide session lookup in this transport Interface.

V1 does not expose or emulate a next-turn message queue. Main may send to an
idle session or use native live input when an Adapter supports it. The Runner
does not defer a rejected message.

Last-turn outcome is separate from current activity. When available, `status`
reports `completed`, `interrupted`, or `runtime-error`; none means that the
ticket completed or failed. An interrupted but resumable session is `idle`
with an `interrupted` last-turn outcome. `launching` is internal: launch
succeeds only after the Runtime session and durable alias mapping exist.
Unknown aliases, corrupt mappings, unreachable Runtimes, and non-resumable
sessions are structured operation errors rather than a public `unavailable`
activity.

Each active Agent turn is owned by a short-lived internal Runner worker.
The worker starts and owns the Adapter process group, captures Runtime events
and stderr, persists the terminal outcome, and exits when that turn ends. A
batch launch returns after the Adapter has obtained the Runtime session and the
Runner has durably established its alias mapping; it does not wait for the turn
to finish. An idle-session `send` starts a new worker that resumes the mapped
Runtime session while retaining the alias. These workers are private
implementation processes, not a resident daemon or another Main-facing
command.

The V1 `codex exec` Adapter cannot accept live input during a running turn.
`send` therefore fails without changing that turn and tells Main that, if the
instruction must take effect immediately, Main may explicitly `interrupt` the
alias and then `send` to resume it. The Runner never performs this sequence
automatically because interruption is a semantic decision. An Adapter with
native live input may implement running-turn `send` directly.

An alias identifies one immutable logical Runtime session. It combines the
unambiguous `ticket-stem` from
[ADR 0009](0009-integrate-ticket-worktrees-through-dev.md) with a role marker
and that marker's session ordinal: `@jN`, `@sN`, and `@eN` identify Junior,
Senior, and Expert Engineer sessions, while `@rN` identifies either Reviewer
role. Examples are `2-42-payment-retry@j1`, `2-42-payment-retry@e1`, and
`2-42-payment-retry@r1`. The ordinal counts fresh sessions for that marker, not
review failures or review rounds. Rework that resumes a session retains the
alias; replacement or tier escalation creates a new alias. Because one ticket
may have only one live Ticket Worktree across the Harness Project, the alias
does not repeat the project or Delivery Run identity.

Alias uniqueness and immutability apply to live Runner mappings. Successful
cleanup retires the mapping, so a later Delivery Run may reuse the same alias
text for a new logical Runtime session. Persistent history identifies a
session by `(run_id, alias)`; a historical alias without a live mapping is not
a transport address.

The Runner persists each narrow alias-to-Runtime-session, process, role,
worktree, and ticket-file mapping at
`<harness-project-root>/.codex/agent-runner/sessions/<alias>/` in the Harness
Runtime Store. The Delivery State Agent may record current and historical
aliases, but this does not make the Runner the semantic ticket ledger.
Successful ticket cleanup deletes all live aliases and transport diagnostics
bound to the removed worktree; aliases retained in evidence become history
rather than transport addresses.

`idle` describes only the addressed alias and does not reserve its Worktree.
A batch launch or `send` must pass the applicable Worktree reservation
preflight. Engineer exclusivity and ADR 0019's narrow concurrent-Reviewer
exception remain launch policy owned by
[ADR 0019](0019-main-dispatches-reviewers.md); this ADR owns only their live
alias and transport identity. This is mechanical resource safety, not a
decision about readiness, retries, or escalation.

The launch path makes that preflight atomic across separate Runner processes:
before provisioning or starting a turn it creates one project-private
reservation for the derived Ticket Worktree under
`<harness-project-root>/.codex/agent-runner/active-worktrees/`.
The reservation records `starting`, becomes `running` with the durable session
mapping, and is released by the owning worker only after the Runtime turn is
terminal. An existing or unexpected reservation fails closed; it is never
treated as permission to start a concurrent Engineer.

Every Runner command, including launch, `status`, `send`, `interrupt`, and
`cleanup`, writes one YAML result document to stdout. Human-readable
diagnostics go to stderr and the process exit status independently reports
success or failure. V1 does not offer JSON, JSONL, or selectable output.

Main decides when and why to use these operations. A transport result never
updates the Delivery State Agent's semantic state or infers retry, escalation,
or the meaning of a user's direction. Durable mappings remove the need for a
resident Runner supervisor. Recovery uses the same accepted alias and Runtime
session mapping as interruption: when both remain usable, `status`, `interrupt`,
or `send` can observe, stop, or resume the session. A missing mapping, lost
Runtime session, or non-resumable session produces a structured operation
error; V1 adds no second recovery identity or reconstruction mechanism. Main
decides whether to start a fresh session in the retained Ticket Worktree.

## Considered options

- Exposing only background shell jobs was rejected because job identity,
  signals, output, and resume behavior differ across Runtimes.
- Addressing sessions by `ticket_name` was rejected because one ticket may
  have multiple replacement and escalation sessions.
- Opaque hashes, UUIDs, and raw Runtime session IDs were rejected as Main's
  normal handle because they make active sessions difficult to recognize.
