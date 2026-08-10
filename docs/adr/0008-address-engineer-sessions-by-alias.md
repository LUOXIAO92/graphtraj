---
status: accepted
---

# Address Engineer Runtime sessions by semantic alias

Main controls launched Engineer sessions through Runner aliases rather than
shell job IDs, opaque Runtime session IDs, or Runtime-specific resume commands.
The Runner exposes three transport operations: `status`, `send`, and
`interrupt`.

- `status` observes Runtime activity without choosing or changing a ticket
  status. A successful result is `running` while a turn is active or `idle`
  when no turn is active and `send` can continue the session.
- `send` delivers a concise follow-up through the Adapter's live-input or
  resume mechanism.
- `interrupt` requests that the current Runtime execution stop while
  preserving the alias, mapping, branch, and Ticket Worktree when recovery is
  possible.

Their V1 command forms are:

```text
agent-runner status <alias> [<alias>...]
agent-runner send <alias> --instruction <text>
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

Each active Engineer turn is owned by a short-lived internal Runner worker.
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

An alias identifies one immutable logical Runtime session. It combines ticket
ID and short name with Engineer tier and that tier's session ordinal, for
example `42-payment-retry@j1`, `42-payment-retry@s1`, and
`42-payment-retry@e1`. The ordinal counts fresh sessions at that tier, not
review failures. Rework that resumes a session retains the alias; replacement
or tier escalation creates a new alias.

The Runner persists the narrow alias-to-Runtime-session, process, role,
worktree, and ticket-file mapping under the Git common directory. The Delivery
State Agent may record current and historical aliases, but this does not make
the Runner the semantic ticket ledger. Successful ticket cleanup deletes all
live aliases and transport diagnostics bound to the removed worktree; aliases
retained in evidence become history rather than transport addresses.

At most one Engineer turn may actively write one Ticket Worktree. A batch
launch or `send` that would start a second turn there is rejected with the
alias already running. This is mechanical resource safety, not a decision
about readiness, retries, or escalation.

Every Runner command, including launch, `status`, `send`, `interrupt`, and
`cleanup`, writes one YAML result document to stdout. Human-readable
diagnostics go to stderr and the process exit status independently reports
success or failure. V1 does not offer JSON, JSONL, or selectable output.

Main decides when and why to use these operations. A transport result never
updates the Delivery State Agent's semantic state or infers retry, escalation,
or the meaning of a user's direction. Durable mappings remove the need for a
resident Runner supervisor. This ADR does not yet decide Adapter-specific
process reattachment after a host restart; durable identity and mapping are the
accepted prerequisite rather than a claim of completed recovery semantics.

## Considered options

- Exposing only background shell jobs was rejected because job identity,
  signals, output, and resume behavior differ across Runtimes.
- Addressing sessions by `ticket_name` was rejected because one ticket may
  have multiple replacement and escalation sessions.
- Opaque hashes, UUIDs, and raw Runtime session IDs were rejected as Main's
  normal handle because they make active sessions difficult to recognize.
