---
status: accepted
---

# Task Delivery is soft Agent orchestration and owns review escalation

The V1 Harness needs to deliver an accepted ticket DAG through isolated
Engineers without prematurely turning the observed workflow into an executable
orchestration engine. We will implement `task-delivery` as a soft Harness: a
skill that teaches the Main Agent how to orchestrate delivery, delegate record
keeping, and apply review escalation. It is not a deterministic controller,
scheduler, normalizer, dispatcher, or enforced state machine.

## Decision

### Planning and delivery are separate

The planning flow precedes `task-delivery`:

1. The existing design and user intent enter an iterative alignment loop using
   the grilling skills and `$to-spec`.
2. The accepted spec is converted into accepted tickets and explicit
   dependencies by `$to-tickets`.
3. `task-delivery` consumes that accepted ticket DAG.

Spec alignment is not a separate step after `$to-spec`; the grilling skills and
`$to-spec` together perform alignment and intent solidification.

`task-delivery` does not generate a spec, split work into tickets, silently
invent missing dependencies, rewrite acceptance criteria, or redesign settled
scope. If the accepted tickets are incomplete, cyclic, ambiguous, or conflict
with the spec, the affected work returns to Main for planning or user
clarification.

The task map used during delivery is an Agent-readable working representation
of the accepted tickets and their explicit dependencies. V1 does not impose a
machine-enforced normalized graph schema or require Engineers to consume a
formal dispatch packet.

### Main orchestrates the Delivery Run

`task-delivery` is a Main/control-plane skill. A logical Delivery Run defaults
to driving the whole accepted task DAG through successive frontier waves until
every task is integrated, externally blocked, or escalated to the user. An
`awaiting-integration` point is an internal checkpoint, not the default end of
the run. A user instruction can interrupt or redirect the run at any time.
Main interprets that instruction in context and acts on its meaning; V1 does
not define pause, stop, cancellation, resume, or replanning commands, nor a
control-state machine for them.

Main retains authority over dependency readiness, complexity classification,
Engineer tier, dispatch, review adjudication, retry/escalation, integration
ordering, and exceptions. The skill supplies behavioral guidance for these
decisions; no V1 program enforces them. Engineers consume the accepted ticket,
an optional concise instruction from Main, and the ticket's referenced specs,
ADRs, and design material, then inspect and implement within their assigned
worktree. They do not need the entire DAG or Main's historical reasoning.

### A Delivery State Agent maintains working state

Delivery Run state lives in a project-level persistent **Harness State
Directory** at `<worktree_root>/<project>/state/`, outside every Git worktree.
The Integration Worktree exposes that directory through an ignored `.scratch`
symlink, preserving the Matt Skills scratch convention; the ledger is visible
to Main and the Delivery State Agent at
`.scratch/task-delivery/<run-id>/ledger.md`. Main is the semantic authority but
does not maintain the ledger or Mermaid itself. A Delivery State Agent acts on
Main's behalf as the sole writer of both artifacts, reducing Main's output and
context load. When it initializes the accepted task graph, the Delivery State
Agent creates the Delivery Run's short, stable `run_id` and returns it to Main.
Main only relays that identifier at the top level of Runner batch input; the
Runner treats it as an opaque grouping identifier and does not assign it
semantic state. The ID uses the ASCII form `YYYYMMDD-short-name`, with a numeric
suffix such as `-2` when necessary. The Delivery State Agent chooses the
semantic short name and avoids a collision; the Runner only validates that the
identifier is path-safe, within its allowed length, and not inconsistent with
an existing run mapping. Its role is broader than record entry: it pulls and
understands the current working state from the artifacts left by active
Engineers.

The Delivery State Agent is a project-level custom Agent role launched and
coordinated directly by Main through the Agent Runtime's native agent tools. It
shares Main's Integration Worktree context and does not cross the Agent Runner
seam. The Merge Resolver is likewise a Main-coordinated custom role in the
Integration Worktree. In V1, the Runner is limited to mechanically launching,
isolating, and transporting Engineer sessions for the tickets and logical roles
already selected by Main; it does not perform semantic scheduling, operate the
Delivery State Agent, or replace Main as the orchestrator.

At the start of a run, the Delivery State Agent reads the accepted tickets and
their explicit dependencies and creates the working task map, ledger, and
Mermaid DAG. Each task is keyed by its tracker-supplied `ticket_id` and has a
short, stable `ticket_name` that carries human-readable meaning without copying
the potentially long ticket title. An accepted ticket may provide this name;
otherwise the Delivery State Agent assigns it once while initializing the
working task map. Main only resolves a collision or a materially misleading
name. When Main dispatches a task, its worktree, branch, tier, and Engineer
session are registered once. After an Engineer turn or another meaningful
event, Main only asks the same Delivery State Agent to synchronize the task.
The Agent reads the registered worktree's result, review evidence, validation
evidence, and Git state itself; archives the evidence; updates the ledger and
Mermaid; and returns a short summary, ready-task suggestions, and
inconsistencies or semantic questions requiring Main attention.

Each ticket has one persistent evidence directory at
`state/task-delivery/<run-id>/tickets/<ticket-id>-<ticket-name>/`; retries and
tier escalation reuse it rather than creating a directory per Engineer
session. When provisioning the Ticket Worktree, the Runner creates a scoped
`.scratch/task-delivery` symlink to that ticket directory and writes or updates
`metadata.yml` with the hard launch facts it owns. The Engineer writes only the
valuable semantic outputs: the current result, validation summary, and raw
Standards and Spec Reviewer reports. Reviewer report filenames include the
session alias and review round so prior evidence is not overwritten. Other
Matt Skills scratch material remains local to the Ticket Worktree because only
the `task-delivery` child is linked to persistent state.

The Delivery State Agent reads this evidence directly through the Integration
Worktree's persistent `.scratch` view and maintains the central ledger and
Mermaid DAG; it no longer copies evidence out of Ticket Worktrees. Main reads
the evidence to adjudicate but does not repeat or rewrite it for the Delivery
State Agent. The ledger links to the evidence instead of embedding the reports.

The central Delivery Run ledger, Mermaid task map, archived Engineer results,
validation evidence, and Reviewer reports are not deleted automatically when a
ticket is cleaned up or when the Delivery Run ends. Only the operator may
explicitly remove these run artifacts, by deleting the corresponding directory
through the filesystem or a file manager. V1 provides no Runner or product CLI
command for deleting persistent Delivery Run state because the Runner is an
Agent-facing Engineer transport tool, not a user-facing state manager. The
persistent ticket evidence remains when successful integration makes the Ticket
Worktree and its scoped symlink eligible for cleanup.

The Engineer roles' static developer instructions define this evidence-output
contract, including the required result, validation summary, and raw Standards
and Spec Reviewer reports. The Delivery State Agent supplies the `run_id`, and
the tracker binding supplies each `ticket_id`; the Runner validates these
identities and writes the hard launch metadata it owns, including IDs, alias,
role, session, branch, and worktree. The Engineer applies its developer
instructions to that metadata and writes only the semantic result and review
evidence. Main does not construct, append, or repeat an evidence contract for
each ticket, and the Runtime Adapter does not own a second dynamic task
description.

The Delivery State Agent does not adjudicate review, choose an Engineer tier,
dispatch work, change tickets or dependencies, accept integration, or
otherwise replace Main's authority. It records a review verdict only after
Main supplies the compact semantic decision, such as `PASS` or `FAIL` with the
blocking finding. A fresh Delivery State Agent may recover by reading the
artifacts if its prior session is unavailable. In the soft Harness, Main must
still trigger synchronization after meaningful changes; an autonomous watcher,
hook-driven Agent, or event-loop controller is outside V1.

The Delivery State Agent maintains the shared soft status vocabulary for the
whole Delivery Run:

- `pending` — explicit dependencies have not all been integrated.
- `ready` — the task is a candidate for Main to dispatch.
- `implementing` — an Engineer is implementing the task.
- `reviewing` — the two Reviewers are examining the candidate work.
- `reworking` — Main adjudicated the review as `FAIL` and the Engineer is
  addressing the evidence.
- `awaiting-integration` — Main adjudicated the review as `PASS` and the
  reviewed commit is queued for integration.
- `integrating` — the commit is being merged and validated in `dev`.
- `resolving-integration` — the Merge Resolver is reconciling a textual or
  semantic integration conflict.
- `integrated` — the commit is present in `dev` and integration validation
  passed; this is the successful terminal task status.
- `blocked` — an external condition prevents autonomous progress.
- `escalated` — autonomous review escalation is exhausted and Main or the user
  must decide what happens next.

`completed` is not a task status because it ambiguously conflates
implementation, review, and integration. `failed` is not a task status because
review failure, transport failure, test failure, and integration failure have
different consequences; the Delivery State Agent records those as
evidence-bearing events and applies the task status chosen by Main. The
Delivery State Agent may record Main's current intent or the user's latest
direction in plain language, but those notes are not canonical Delivery Run
control states and do not drive orchestration.

Engineer handoff remains a soft convention with two outcomes: review evidence
returned, or blocked. On a review return, the Engineer supplies the resulting
commit, validation summary, the raw Standards and Spec reports, and any
outstanding concern; it does not claim that review passed. On a blocker, it
supplies the blocker, evidence, attempted work, and the decision or condition
needed to continue. Session, worktree, tier, escalation counters, and the whole
DAG are already held by the Delivery State Agent and are not repeated by the
Engineer. `task-delivery` does not prescribe `$implement`'s internal commit,
amend, or review ordering.

### Review escalation remains inside Task Delivery

The skill does not merge reviewed commits into `dev`. After a frontier wave
produces reviewed commits, the Delivery Run enters `awaiting-integration`.
Master's serialized integration flow merges and validates those commits; only
commits verified as present in `dev` unlock dependent tasks. The same Delivery
Run then resumes from its ledger.

Review escalation is an internal `task-delivery` policy, not a separate skill:

- Reviewers return evidence; Master alone decides `PASS` or `FAIL` for each
  review round and records the rationale.
- Only a Master decision of review `FAIL` increments the escalation counter.
  TDD red states, test or typecheck failures during implementation, transport
  failures, and external blockers do not count.
- A failed review below the threshold resumes the same Engineer session in the
  same worktree.
- Three review failures at one tier replace the Engineer with a fresh-context
  agent in the same worktree: Junior to Senior, then Senior to Expert. The new
  tier starts its own failure count while retaining canonical work state and
  review evidence, not the previous conversation.
- Three Expert review failures stop autonomous delivery and escalate to
  Master/user exception handling.

The V1 skill source lives in `codex/skills/task-delivery` as a configuration
template. A later setup workflow will install it into the target repository's
`.agents/skills` directory.

Engineer dispatch crosses an Agent Runner seam supplied alongside
`task-delivery`; its executable name is `agent-runner`. Main chooses an Engineer
tier and gives the Runner logical task objects rather than individual runtime
commands. Main does not plan or pass a branch or physical worktree path, select
or pass a profile or agent-configuration path, or construct `codex exec`,
`opencode run`, or another runtime command.

### Target-project setup binds the runtime adapters

Target-project setup creates a machine-local Project Runner Config at
`<git-common-dir>/agent-runner/config.yml`. The file is not committed and is
shared by the primary checkout and all linked worktrees through their Git
common directory. It records the configuration version, default runtime,
machine-local `worktree_root`, integration branch, and the configured runtimes'
executable and private logical-role bindings. Main neither locates this file nor
passes its path.

At invocation, the Runner discovers the config from the current Git project,
uses an explicit `AGENT_RUNTIME` environment override when one is present, and
otherwise selects `default_runtime`. Normal `task-delivery` invocation omits
the override, and runtime selection never appears in the batch YAML. An unknown
or unconfigured runtime fails preflight before any task launch.

The selected runtime name resolves through the Runner's built-in allowlisted
Adapter registry, such as `codex` to the Codex Adapter and `opencode` to the
OpenCode Adapter. Only the selected Adapter is loaded. Project config may
supply values understood by that Adapter, including its executable and private
role bindings, but cannot name an arbitrary Adapter module, shell template, or
raw runtime command. This keeps runtime variation behind the Runner seam while
allowing setup to bind machine-specific configuration once.

For the Codex Adapter, project setup keeps the external state writable without
adding a separate Main launcher. Its project-local `.codex/config.toml` uses
`workspace-write` and adds the Worktree-local `.scratch` path to
`sandbox_workspace_write.writable_roots`. Main and its native Delivery State
Agent therefore access the physical Harness State Directory through the
Integration Worktree's symlink. When the Runner launches an Engineer, the
Codex Adapter internally supplies both the Ticket Worktree with `-C` and the
resolved persistent ticket-evidence directory with `--add-dir`; neither path nor
raw Codex syntax enters Main's task object. Setup mechanically verifies that
the configured path resolves to the registered Harness State Directory and is
writable before reporting success. These settings take effect through the
Runtime's normal project-config loading; the Harness does not introduce an
interactive Main-start command.

One invocation uses `agent-runner --batch-input <yaml-file>`. The YAML contains
the Delivery State Agent's `run_id` once at its top level and a list of one or
more task objects; `batch` only disambiguates this from a one-ticket-per-file
interpretation and does not add DAG, scheduling, transactional, or
atomic-execution semantics. Each task supplies its ticket ID, short ticket
name, logical Engineer role, canonical `ticket_file` reference, and an optional
plain-text `instruction`. The ticket file contains the complete task
definition, including its requirements, acceptance criteria, dependencies, and
references to specs, ADRs, and design material. It is not a second dispatch
document written by Main. Runtime choice and raw command syntax do not appear
in each task object.

The Runner attempts exactly the task objects present in that batch and no
others. It does not query the tracker for more tickets, inspect the DAG for a
ready frontier, add tasks that Main omitted, or change the logical Engineer
role selected by Main.

`ticket_file` is either the canonical local ticket or a complete local snapshot
materialized by the target project's tracker binding for a remote GitHub,
GitLab, or other ticket. The Runner resolves the supplied path, verifies that
it is a readable regular file, reads it without modifying it, and gives its
contents to the Runtime Adapter as the Engineer's initial task. It does not
copy the ticket file into a worktree or require the Engineer or its Reviewers
to access the source path. Ownership and retention of the ticket file remain
with its tracker binding; the Runner never creates, rewrites, or deletes the
canonical ticket or its supplied snapshot.

The optional `instruction` is a concise delivery note appended to the ticket
content by the Runtime Adapter. It may communicate a temporary priority,
environment constraint, review-evidence reference, or a specific point Main
wants checked. It does not restate the ticket, add acceptance criteria, change
scope or dependencies, or introduce a detailed technical plan. Material that
complex belongs in the canonical ticket or its referenced planning artifacts;
if it changes accepted work, delivery returns to the ticket/spec planning flow.
This semantic limit is skill guidance rather than a Runner-enforced schema.

Main may create the `--batch-input` YAML as a temporary file. After validating
it and before launching any Engineer, the Runner copies the exact input,
including any inline instruction, into the Delivery Run's physical Harness
State Directory outside every Git worktree and returns the retained path in its
result. The caller may then remove the temporary source file. The retained copy
is not cleaned after a successful launch, at the end of the Delivery Run, or
during Ticket Worktree cleanup; only the operator may explicitly delete it. Its
lifetime is independent of canonical ticket retention and Ticket Worktree
retention.

`ticket_id` is the stable identity supplied by the target project's tracker
binding. It is stable within that target project but otherwise opaque to the
Runner, so repository-scoped GitHub numbers, project-scoped GitLab IIDs, and
local tracker keys can all cross the same interface. `ticket_name` is a short
semantic name fixed for the Delivery Run; it improves human navigation but is
not an identity key and is not the full tracker title. Both fields use ASCII:
`ticket_id` is 1-32 characters and accepts letters, digits, `.`, `_`, and `-`;
`ticket_name` is 1-64 characters in lowercase kebab-case. The Runner does not
silently truncate either field. Before starting any task from one batch, the
Runner validates the complete input and rejects a repeated `ticket_id`; this
preflight check does not make launch execution transactional or atomic.
Different ticket IDs may share a ticket name because the name is not an
identity key, although the Delivery State Agent should normally choose names
that remain easy to distinguish.

The Runner resolves the logical role through an allowlisted role registry and
uses a runtime-specific adapter to load the corresponding configuration, render
the command, provision or recover the ticket's branch and worktree, start the
Engineer process there, and surface its result or transport failure. Codex and
OpenCode adapters may use different configuration layouts, flags, output
formats, and session identifiers; those details remain inside the Runner. For
each task, the Runner returns at least `alias`, `ticket_id`, `ticket_name`,
`session`, `worktree_path`, and `ticket_file`. The raw runtime session remains
available for durable state and recovery but is not Main's normal transport
address.

After attempting the launches, the Runner emits one compact YAML result
document rather than a streaming JSONL protocol. Every requested task has one
result containing its ticket ID, ticket name, logical role, `launch_status`,
worktree path, and ticket-file path. A successful launch also contains the alias
and raw runtime session. A launch error leaves alias and session absent and
contains a structured error code and message; launch status is transport
evidence, not a ticket status in the Delivery State Agent's vocabulary.

Invalid batch input starts no tasks. After preflight succeeds, launches are
independent: one failure does not stop or roll back Engineers that have already
started, and the result document reports every success and error explicitly.
The process exits zero only when all launches succeed and nonzero for a partial
or total launch failure. Because this command returns after starting the
Engineer processes rather than waiting for their work to finish, V1 does not
need streaming output.

Every Runner command, including launch, `status`, `send`, `interrupt`, and
`cleanup`, writes one YAML result document to standard output. Human-readable
diagnostics go to standard error, and the process exit status independently
indicates success or failure. V1 does not offer JSON, JSONL, or a selectable
output format; YAML is both the machine contract and the readable operator
representation.

`alias` is the short, semantic reference to one immutable Engineer runtime
session. It combines the ticket ID and short name with the Engineer tier and
that tier's session ordinal, for example `42-payment-retry@j1`,
`42-payment-retry@s1`, and `42-payment-retry@e1`. The ordinal counts fresh
runtime sessions at that tier, not review failures. Rework that resumes the
same session retains the alias; tier escalation or another fresh-context
replacement creates a new alias. An alias remains a valid Runner transport
address only while its Ticket Worktree and durable mapping are retained.

### Runner owns runtime-session transport

After launch, Main controls Engineer runtime sessions through an alias-based
Runner interface rather than shell job IDs or runtime-specific resume commands.
V1 exposes three transport operations: `status`, `send`, and `interrupt`. The
Runner delegates each operation to the selected runtime Adapter and translates
its process and session behavior into the shared interface.

- `status` observes the runtime session without choosing or changing a ticket
  status. A successful result exposes only `running`, when a turn is active,
  or `idle`, when no turn is active and `send` can continue the session.
- `send` delivers an additional concise instruction to the logical session,
  using the Adapter's live-input or resume mechanism as appropriate.
- `interrupt` requests that the current runtime execution stop while preserving
  the alias, session mapping, branch, and Ticket Worktree when recovery is
  possible.

V1 does not expose or emulate a next-turn message queue. Main may send to an
idle session or use an Adapter's native live-input capability when available;
the Runner does not defer a rejected message for later delivery.

The last turn's outcome is orthogonal to current session activity. When
available, `status` reports it separately as `completed`, `interrupted`, or
`runtime-error`; none of these values claims that the ticket completed or
failed. In particular, an interrupted but resumable session is `idle` with a
last-turn outcome of `interrupted`.

`launching` is an internal transient rather than a public activity: a launch is
not reported as successful until the Runner has obtained the runtime session
and durably established its alias mapping. An unknown alias, unreachable
runtime, corrupt mapping, or non-resumable session is a structured operation
error rather than an `unavailable` activity. This keeps defensive failures out
of the normal session vocabulary.

When the selected runtime entry point cannot accept live input, as with the V1
`codex exec` Adapter, `send` against a running turn must fail without changing
the execution. Its structured result must do more than report that the session
is busy: it identifies that live steering is unsupported and tells Main that,
if the instruction must take effect immediately, Main can explicitly
`interrupt` the alias and then `send` the instruction to the resumed session.
The Runner never performs this sequence automatically because interrupting
in-flight work is a semantic decision. This fallback is an interrupted turn
followed by resumed work, not native same-turn steering. An Adapter backed by a
runtime entry point with native live-input support may deliver `send` directly
instead.

Main decides when and why to call these operations. The Runner does not infer
retry, escalation, ticket transitions, or the meaning of a user's direction
from them, and a transport result does not itself update the Delivery State
Agent's semantic state. Runner invocations are backed by durable alias,
runtime-session, process, role, and worktree mappings rather than a resident
supervisor. The behavior of `send` against a running turn for other runtime
Adapters remains to be settled.

The Runner also enforces one mechanical worktree-safety invariant: at most one
Engineer turn may be active in a Ticket Worktree at a time, regardless of how
many historical aliases that ticket retains. A batch launch or `send` that
would start a second active turn in the same Ticket Worktree is rejected with
the alias of the turn already running. This does not decide whether a ticket is
ready, which session Main should use, or whether escalation is warranted; it
only prevents concurrent processes from modifying the same checkout.

Main uses `alias`, not `ticket_name`, for follow-up, resume, interrupt, and
session-status transport operations. The Runner owns the narrow mapping from
alias to the underlying runtime session, role, worktree, and ticket-file
reference. The Delivery State Agent records the ticket's current and historical
aliases with the other Delivery Run facts, while the Runner resolves aliases
for transport operations. This mapping does not make the Runner the ticket
ledger or semantic state authority. When successful-merge cleanup removes a
Ticket Worktree, the Runner also deletes every alias mapping bound to that
worktree; later transport against one of those aliases fails as an unknown
alias. Any alias text already recorded with delivery evidence is historical
ledger data, not a retained transport address. Alias escaping remains a
separate implementation detail.

Raw Runtime event output and standard error are transport diagnostics rather
than durable delivery evidence. The Runner retains them with the machine-local
session mapping under `<git-common-dir>/agent-runner/sessions/<alias>/` so its
Adapter can observe, diagnose, and recover the background process. Successful
ticket cleanup deletes these session diagnostics together with the aliases and
worktree. Engineer results, validation summaries, and raw Reviewer reports
remain separately preserved in the Harness State Directory.

The Runner does not accept an arbitrary runtime command from Main. It does
not read the ticket DAG, decide readiness or Engineer tier, adjudicate reviews,
increment escalation counters, integrate commits, or maintain Delivery Run
state. Those remain soft Agent decisions. Its hard responsibility is narrowly
limited to safe role resolution, worktree-bound process launch, session
transport, and result collection.

The Runner mechanically derives branch names and physical worktree paths from
the project, Delivery Run, and stable ticket ID, with the short ticket name as
a readable suffix rather than an identity key. A worktree is a complete
isolated repository checkout and defines the Engineer's editable repository
root; it is not a Main-designed allowlist of individual files or directories.
Retries and tier escalation reuse the same branch and worktree. The Runner
recovers and validates an existing mapping when one is present instead of
creating a duplicate. When a ticket ID appears in a later batch, it continues
to resolve to the same Ticket Worktree while that worktree exists, but every
batch launch creates a fresh runtime session and alias. `send` against an
existing alias is the only V1 entry point that resumes that same runtime
session. If successful-merge cleanup has already removed the Ticket Worktree, a
later batch launch provisions a new Ticket Worktree and fresh session from the
then-current validated `dev` state.

Physical worktrees live under a machine-local `worktree_root` outside the
repository, organized by project identity, Delivery Run, and ticket. Setup
chooses this root once, with a repository-parent `.agent-worktrees` directory as
the normal default and a local override when required. The root is neither
committed project configuration nor batch-task input. It must not resolve
inside the repository or to an ephemeral system temporary directory, and setup
must grant the Runner the required filesystem and sandbox access. The Runner
canonicalizes and validates the root and verifies created or recovered
paths against `git worktree list`.

### Integration has a dedicated project-level worktree

Each target project has one long-lived **Integration Worktree** under
`<worktree_root>/<project>/integration`, fixed to the `dev` branch. Ticket
Worktrees remain run-scoped under
`<worktree_root>/<project>/runs/<run-id>/<ticket-id>-<ticket-name>` and use
their own ticket branches. The persistent Harness State Directory is their
project-level sibling at `<worktree_root>/<project>/state`; setup creates an
ignored `.scratch` symlink in the Integration Worktree that points to it. The
Integration Worktree is project-scoped rather than Delivery Run-scoped because
Git permits a local branch to be checked out in only one worktree at a time and
`dev` is the project's unique development integration state. Concurrent
Delivery Runs for one project therefore share serialized integration through
this worktree and the persistent state directory without storing that state in
Git.

Ticket branches are created from the current validated `dev` state when Main
dispatches them. Independent tickets may share the same `dev` base snapshot;
a dependent ticket does not start until its prerequisites have been integrated
and validated in `dev`, so it starts from that newer integration state. Review
PASS makes a ticket eligible for the integration queue but does not update
`dev`. Merging, conflict reconciliation, and integration validation occur only
in the Integration Worktree. Promotion from `dev` to `main` is a release
concern outside `task-delivery` and the Delivery Run.

After a ticket's reviewed commit has been successfully merged into `dev`, Main
instructs the Runner to clean up that ticket with
`agent-runner cleanup --run-id <run-id> --ticket-id <ticket-id>`. Cleanup is an
idempotent ticket-lifecycle operation rather than a fourth session-transport
operation, and it is addressed by stable Delivery Run and Ticket identity
rather than by one of the ticket's potentially many session aliases. It removes
the Ticket Worktree, deletes its merged ticket branch, and deletes every Runner
alias mapping bound to the removed worktree. Before deleting anything, the
Runner mechanically verifies that the registered ticket branch is merged into
the registered `dev` branch, the Ticket Worktree has no uncommitted changes,
and the mapping and canonical path still belong to the supplied `run_id` and
`ticket_id`. A failed check refuses cleanup with evidence; an already-cleaned
ticket succeeds idempotently. It does not delete the canonical `ticket_file` or
tracker ticket, which remains available to the Delivery State Agent and Main
while the accepted DAG is still being delivered. Ticket retention remains
owned by the target project's tracker binding rather than by worktree cleanup.

The target-project setup establishes or registers the Integration Worktree;
Main does not choose or type its physical path. The Runner may mechanically
recover and validate the registered worktree without gaining authority to
order integrations, merge commits, or adjudicate validation. Setup must detect
when `dev` is already checked out in another worktree and report the conflict
rather than silently switching the user's current branch. The repository's
primary `main` worktree remains outside routine ticket implementation and
development integration.

Normal planning and delivery Main sessions run from this registered `dev`
Integration Worktree. Main performs serialized merge and integration validation
there without locating or changing into a separate worktree, while the primary
`main` checkout remains reserved for release work. `task-delivery` verifies its
current project workspace is the registered Integration Worktree before it
starts dispatching a Delivery Run.

If the configured `dev` branch does not yet exist, setup shows the exact base
branch or commit it proposes to use and requires explicit operator confirmation
before creating `dev` and its Integration Worktree. If `dev` already exists,
setup validates and registers it. It never guesses the base, silently creates
the integration branch, or switches the branch checked out in the user's
primary worktree.

Starting the Engineer process with the resolved worktree as its initial
workspace lets the existing worktree guard derive the correct immutable root.
The Engineer may then use native Agent tool calling for its two Reviewers,
because those children inherit the Engineer's correctly bound workspace. A
retry resumes the opaque Engineer session in the same worktree; tier escalation
starts a fresh session for the new logical role in that worktree.

V1 targets at most four tickets concurrently, for a maximum topology of four
Engineer processes and eight Reviewer threads in addition to Main and the
Delivery State Agent. Each Engineer process owns its runtime session and bounds
its own Reviewer children, so the Main runtime's native subagent limit is not
treated as a global limit for externally launched Engineers.

## Considered Options

- **Separate escalation skill** — rejected because it would have one natural
  caller and would expose the same task, tier, review, session, and worktree
  state already owned by `task-delivery`, creating a shallow module.
- **Put `$to-spec` and `$to-tickets` inside `task-delivery`** — rejected because
  planning and delivery have different responsibilities. Delivery consumes
  settled scope rather than recreating it.
- **Require Main to construct a normalized graph, ledger, or Mermaid** —
  rejected because mechanical record keeping consumes Main's output and
  context budget. A Delivery State Agent maintains those artifacts instead.
- **Require Main to relay Engineer or Reviewer output to the state keeper** —
  rejected because Main would remain a high-volume information intermediary.
  The Delivery State Agent pulls registered worktree artifacts and Git state;
  Main supplies only semantic decisions that cannot be derived from them.
- **Build a deterministic normalizer, dispatcher, transition command, or
  event-loop controller for V1** — rejected because the current goal is to
  observe and improve a soft Agent workflow before hardening its rules.
- **Automatically trigger a ledger or drawing Agent** — rejected for the soft
  Harness because it requires hooks or a controller. Main explicitly invokes
  or resumes the Delivery State Agent after meaningful state changes.
- **Expose a raw runtime command, profile path, or configuration path to Main**
  — rejected because it would make Main aware of role-loading implementation
  details and permit runtime syntax to leak into the Harness interface. The
  Runner accepts a logical role and owns that translation.
- **Use native Agent tool calling for Engineer dispatch before it can bind the
  spawn to a worktree** — rejected because the Engineer would inherit Main's
  `dev` workspace and the existing guard would lock it to the wrong worktree.
  Native dispatch can become another Runner adapter when it supports the
  required worktree and session controls.
- **Hard-code one runtime's command in `task-delivery`** — rejected because
  Codex and OpenCode already expose different role, worktree, output, and
  session interfaces. Runtime-specific syntax belongs behind the Runner
  seam, not in the skill or Main's reasoning.
- **Require Main to select a runtime on every normal invocation** — rejected
  because runtime selection is a target-project machine binding. Setup records
  the default once; `AGENT_RUNTIME` remains only an explicit operator override.
- **Allow project config to load an arbitrary Adapter module or shell command**
  — rejected because it would turn the config into an unbounded code-execution
  interface and leak runtime command construction back across the seam.
- **Expose only background shell jobs after launch** — rejected because shell
  job IDs, signals, output collection, and session-resume behavior vary by
  runtime and process lifetime. Runner-owned alias operations keep those
  differences behind the Adapter seam.
- **Require Main to plan branch names or physical worktree paths** — rejected
  because these are mechanical isolation resources, not semantic delivery
  decisions. The Runner derives, validates, returns, and recovers them.
- **Use a full ticket title as the Runner's ticket identity or semantic name**
  — rejected because titles may be long and identity does not require display
  text. A stable tracker-supplied ID identifies the ticket, while a separate
  short name provides meaning.
- **Use an opaque hash, UUID, or raw runtime session as Main's session handle**
  — rejected because it makes active and rework Engineer sessions hard to
  recognize. While the mapping exists, the Runner exposes a semantic alias and
  keeps the runtime session behind the transport seam.
- **Use `ticket_name` as an interchangeable session address** — rejected
  because one ticket can create multiple Engineer sessions through replacement
  and tier escalation. The ticket name labels the work; an alias addresses one
  exact session.
- **Place or copy canonical ticket files into a Git worktree** — rejected
  because tickets are planning artifacts owned by their tracker binding, not
  implementation artifacts. The Runner can read a canonical ticket or supplied
  snapshot outside the worktrees and inject its contents through the Runtime
  Adapter without weakening Engineer isolation.
- **Use `instruction` as a second task specification** — rejected because
  complex scope, acceptance criteria, dependencies, or technical plans belong
  in the canonical ticket and its planning references. Instruction remains an
  optional concise delivery note.
- **Delete batch input files immediately after launch** — rejected because the
  exact inputs remain useful for Delivery Run tracing and recovery. Their
  directory is retained until the run ends.
- **Place linked worktrees inside the repository or in an ephemeral system
  temporary directory** — rejected because an in-repository checkout risks
  recursive discovery and accidental edits, while an ephemeral location cannot
  support durable Delivery Runs and handoff recovery.
- **Create one `dev` worktree per Delivery Run** — rejected because Git cannot
  check out the same local branch in multiple worktrees and `dev` must remain a
  single project-wide integration state. Runs share one project-level
  Integration Worktree and serialize integration there.
- **Merge reviewed ticket commits in the primary `main` worktree** — rejected
  because daily development integration must not switch or mutate the release
  worktree or bypass `dev` as the validated integration state.
- **Let `task-delivery` integrate into `dev`** — rejected because delivery and
  serialized integration have different authority, failure modes, and
  worktree permissions.
- **Start dependent work from unintegrated blocker commits** — rejected because
  stacked branches would bypass `dev` as the unique integration state and
  duplicate conflict handling.
- **Let an Engineer implement in Master's `dev` worktree** — rejected because
  sharing one index and working directory destroys ticket isolation and safe
  parallelism; every Engineer keeps an assigned implementation worktree.
- **Commit the ledger** — rejected because control-plane runtime state should
  not pollute product history or participate in integration merges.

## Consequences

`task-delivery` remains an Agent skill, not a software orchestration module.
Its reliability comes from explicit role instructions, Main's judgment,
durable working artifacts, isolated worktrees, and review evidence rather than
machine-enforced transitions. This makes V1 easier to observe and revise, but
it intentionally does not guarantee automatic recovery, schema validation, or
state-transition enforcement. The Agent Runner introduces a small
hard transport module specifically to preserve worktree isolation and hide
runtime differences; it does not turn delivery semantics into a hard Harness.
Agent configuration can move, change format, or switch between supported
runtimes without changing Main or the `task-delivery` skill, as long as the
Runner continues to expose the same logical roles and opaque session
operations.

The future setup workflow must install the skill, choose or derive the
machine-local `worktree_root`, create the persistent Harness State Directory,
and ensure that root is writable through the selected Runtime's project-local
sandbox configuration. It must generate and validate the Project Runner Config,
including the default runtime and its allowlisted role bindings, establish the
project-level Integration Worktree on `dev`, create its `.scratch` symlink to
persistent state, exclude that link from version control, and verify the
configured writable-root resolution, while detecting an existing conflicting
checkout without silently moving it. The Integration Worktree and Harness
State Directory are durable, while a Ticket Worktree, its merged branch, and
its Runner alias mappings are removed after its reviewed commit is successfully
merged into `dev`. Experience from real Delivery Runs may later justify
hardening a stable
part of the workflow, but that will require a separate architectural decision
rather than being smuggled into this soft Harness.
