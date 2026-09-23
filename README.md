# GraphTraj

GraphTraj is a Harness for delivering a graph of accepted Tickets through
Teams. Main manages the whole request, dependencies and integration. Each
Team Leader coordinates one Engineer, two Reviewers and the Team's decisions.
The installed commands provide setup, isolated execution and durable evidence.
This coding Team protocol applies to dispatched `coding-team.*` members.
Shared Delivery State and temporary Batch specialists retain their own duties
and permissions.

Main is started and configured by the user. It follows the user's instructions
and the `AGENTS.md` files applicable to the task, reading Skills as needed.
GraphTraj does not generate, install, append or restore developer instructions
for Main, and using GraphTraj does not assign Main to a coding Team. Setup
preserves existing user Runtime configuration and prompts without using them
as template validation conditions. It does not distribute this development
repository's `AGENTS.md` or operating procedures to user projects.

## Install and set up

Python 3.12 or newer is required. Install a reviewed tag or commit:

```text
uv tool install "git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>"
graphtraj doctor
graphtraj setup
```

Run setup from the Harness Project Root. An existing Git repository is the
default: its Primary Worktree remains on `main`, and the current directory
becomes both the Harness Project Root and Source Repository. In the separated layout, setup selects the sole direct Git
child, or asks for an explicit choice when there are zero or several candidates.
Later commands use the recorded paths.

`uv tool install` builds and installs this distribution's wheel, which carries
the core Skills, role definitions and Codex resources. To check a local
candidate, build that wheel and install the artifact. The documented flags skip
pip's build isolation, so the declared build requirement (`setuptools>=61`,
from `pyproject.toml`) must already be installed in the invoking environment,
for example with `python -m pip install setuptools`:

```text
python -m pip wheel --no-build-isolation --no-deps -w dist .
python -m pip install dist/graphtraj-<version>-py3-none-any.whl
```

Upgrading the installation does not reset an existing project: running
`graphtraj setup` again in a configured project keeps its recorded paths, user
Runtime configuration, role and Skill selections, and Ticket, Team and
Worldline history.

Setup is interactive and checks conflicts before writing. It preserves
project-owned content and valid operator configuration, creates or registers
the `dev` Integration Worktree, and installs every missing core Skill into the Harness Project Root’s
`.agents/skills` after confirmation, even when a user-global copy exists.
Existing project Skills are preserved; project-local copies take precedence
over user-global Skills. It does not clone a repository, configure credentials,
modify Runtime-global settings or promote `dev` to `main`.

The default layout is:

```text
<harness-project-root>/                  also the Source Repository by default
├── AGENTS.md                           user/project instructions
├── CONTEXT.md                          shared vocabulary
├── docs/                               Project Documents
├── .agents/skills/                     Harness Skills
├── .codex/                             user Runtime configuration
└── .graphtraj/
    ├── config.yml                      paths and Runner limits
    ├── roles.yml                       child-role Runtime settings
    ├── .agent-worktrees/
    │   ├── dev/                        Integration Worktree
    │   └── <ticket-id>-<ticket-name>/   disposable Ticket Worktree
    └── state/
        ├── batches/                    exact dispatch inputs
        ├── tickets/                    definitions, Team state and evidence
        └── worldline/                  append-only event shards
```

Runner-private execution records also live beneath `.graphtraj`, outside
durable state. Their filenames are implementation details. The separated
layout keeps the Source Repository in its configured child directory while
Project Documents remain at the Harness Project Root. Linked Worktrees expose
`CONTEXT.md` and `docs/` from their checkout when those already exist. Setup
and Runner preserve their contents and Git tracking; they create links to the
shared project documents only where those paths are absent. Existing documents
are the basis for later updates. Delegated Agents retain read-only document
access, and Main owns Project Document changes. Source Repository README
remains ordinary repository content within the assigned implementation scope.
Runtime-native permissions govern file access; GraphTraj installs no Worktree
Guard or command-parsing Hook. Selected Skills and their references remain
readable through their projected paths.

Generated document links use Worktree-specific Git ignore rules. Existing
repository documents and new files beneath them remain visible to Git unless
user rules exclude them. Setup preserves user ignore files and includes their
current rules in the Worktree-local copy, refreshed when setup or Worktree
preparation runs. Setup migrates the old installer's complete shared ignore
rule group; standalone user rules remain unchanged.

## Python operations

The CLI calls the Python operations below. Import them from their owning
modules; inputs and results do not require a Click context or terminal.
Use `configuration.project_configuration.load_project_configuration(root)`
with the Harness Project Root to obtain configured paths.

All module names in this table are beneath `graphtraj`.

| Module | Operation and input | Result |
| --- | --- | --- |
| `workspace.project_initialization` | `plan_project_setup(root, source_repository)`; then `plan.preflight()` and `plan.apply()` | Existing plan and preview objects; apply returns `ProjectSetupResult` with `integration_worktree`, `integration_action` (`created`, `registered`, `reused`) and `completed_actions`. |
| `configuration.skill_check` | `diagnose_project(root, user_skill_root)` | `ProjectDiagnosis`: Skill statuses, whether roles were checked, role diagnostics and `succeeded`. |
| `graph.ticket_graph` | `register_ticket(state, root, issue)` | Registered Ticket directory as a `Path`. |
| `graph.ticket_graph` | `revise_tickets(state, root, revision)`; `update_ticket_state(state, root, change)` | Recorded causal event as a dictionary. |
| `graph.ticket_graph` | `read_graph(state)` | Dictionary containing current Tickets and dependency readiness. |
| `graph.delivery_state` | `apply_delivery_state_request(state, root, request, authoritative_facts)` | Recorded Ticket/Team event; request must match the supplied authoritative facts. |
| `graph.delivery_worldline` | `append_project_worldline_event(state, root, event)`; `read_worldline(state, root)` | Recorded event, or chronological event dictionaries. |
| `execution.runner_batch` | `parse_swarm(document, caller_ticket_id, registered_tickets)`; `read_swarm(path, cwd, caller_ticket_id, registered_tickets)` | Existing validated `Batch` with each task's current Ticket projected into it. A launch input that already names its Tickets retains its exact bytes; one that leaves identity to the calling Session and the registered Ticket state retains the resolved document. |
| `execution.runner_launch` | `launch_swarm(document, cwd)`; `launch_swarm_file(path, cwd)` | Existing `LaunchResponse` with `document` and `succeeded`, including per-task failures. |
| `execution.runner_status` | `status_aliases(aliases, cwd, operation_total=False, baseline=None, candidate=None)`; `status_tree(cwd, operation_total=False, baseline=None, candidate=None)` | Existing `StatusResponse` with `document`, `succeeded` and `errors`. The tree operation returns one `agents` document without an alias list. |
| `execution.runner_control` | `send_instruction(alias, instruction, cwd, caused_by_event_ids)`; `interrupt_session(alias, cwd)` | Session operation result dictionary. |
| `execution.runner_cleanup` | `cleanup_ticket(cwd, ticket_id)` | Existing `CleanupResponse` with `document` and `succeeded`. |
| `teams.coding.team_round` | `continue_stopped_ticket(ticket_id, caused_by_event_ids, cwd)` | Continuation result and its causal event ID. |
| `teams.coding.team_replacement` | `replace_session(alias, actor, caused_by_event_ids, cwd)` | Replacement result dictionary. |
| `teams.coding.ticket_integration` | `integrate_ticket(configuration, ticket_id, validation_command, diagnosis=None)` | Candidate, integration status, event ID, evidence path and unlocked Ticket IDs. Validation argv is a tuple; failure retains evidence and a non-integrated status. |

Issue, revision, state request and event dictionaries use the same fields as
the corresponding CLI YAML inputs. Paths are `pathlib.Path` objects; causal
event IDs in Runner control calls are tuples of strings. For example, read a
configured project's current graph directly:

```python
from pathlib import Path
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.ticket_graph import read_graph

configuration = load_project_configuration(Path("/path/to/harness"))
graph = read_graph(configuration.state)
ready = [ticket for ticket in graph["tickets"] if ticket["ready"]]
```

Setup's `apply()` is the explicit mutation step. Pass
`install_missing_skills=True` to both preflight and apply when authorizing
missing Skill installation. The CLI supplies the repository-selection and
confirmation prompts and renders the same plan and result.

Graph and semantic-state validation raise `ValueError`; Setup raises
`ProjectSetupError`. Doctor returns missing-Skill and invalid-role diagnostics,
and raises `DoctorError` for a known child Worktree. Configuration, filesystem
and stored-document errors retain their existing exception types. Runner
operations use `RunnerError`; `error.as_document()` supplies the CLI's public
error code and message. Check response `succeeded` or integration `status`
as well: a retained failed outcome is a result, not necessarily an exception.
Only the CLI translates these into usage errors, terminal messages and exits.

Execution keeps the current Runtime backend and inherited Runner authority
and Session context. Python calls follow the same parent-child registration,
capacity, recovery, candidate and integration rules. Live budget JSONL can be
routed to an open descriptor with
`execution.execution_budget.budget_notice_output(descriptor)` around an
operation. Without a selected or inherited channel, budget accounting and
Leader notices remain retained and Python produces no terminal output; the
CLI selects stderr. Conflict integration retains notices in its evidence log.

For a Codex Main, `agent-runner` and the MCP server automatically bind that same
caller channel when the caller provides its Codex thread identity
(`CODEX_THREAD_ID`, or `params._meta.threadId` for a tool request).
`CodexMainRecovery` ignores ordinary estimate/allowance notices and retains only
a sampled stop: the deterministic stop identity, the stop's own absolute instant
with its explicit UTC offset, the elapsed work duration as a separate
expression, and the explicit `$retro` instruction with the absolute
`retro/SKILL.md` path. The document the awaited call returns carries that stop
as `stop_deliveries`, and the delivery instant is stamped when the call returns,
so Main handles the event inside its current turn instead of after the turn
ends. A delayed stop keeps the instant it actually happened and never reports
itself as just-happening. Nothing is queued into Main's native input, no second
Main or Driver is created, and the binding never continues the Ticket or clears
budget accounting automatically.

One delivery is retained per stop: a repeated stop notice or a repeated call
keeps the same stop identity without delivering again. Retained failure stays
visible - a caller-channel or delivery error inside the caller's lifetime is
raised by the recovery binding and remains chained to a wrapped Runner error.
Without the caller's Codex identity, Runner keeps its ordinary
inherited-channel or stderr behavior.

A stop sampled after the call that was awaiting it has already returned has no
in-band carrier: the resumed Worker keeps the caller channel, but that call
cannot be answered twice. Such a stop is retained in the Ticket's
`execution-budget.yml` and reported to the Team Leader; it is not placed in
Main's input box.

`agent-runner send --reports-only` collects a report a Session already holds.
It resumes that Session read-only without attaching the budget monitor, so
returning existing evidence advances no stopping check, repeats no sampled stop
and delivers no new retro instruction. Every other `send` and `continue` keeps
the Ticket under its budget control, and this mode changes no accounting,
identity or stop history.

```python
from pathlib import Path

from graphtraj.execution.execution_budget import budget_notice_output
from graphtraj.execution.runner_launch import launch_batch
from graphtraj.runtimes.codex.app_server import CodexMainRecovery


def launch_from_codex_main(
    batch,
    harness: Path,
):
    recovery = CodexMainRecovery.from_environment(harness)
    if recovery is None:
        return launch_batch(batch, harness)
    with recovery:
        with budget_notice_output(recovery.notice_fd):
            return launch_batch(batch, harness)
```

The environment thread identity only selects that same caller channel. A CLI
message, `thread/resume`, `thread/queue/add` or a second Main driver is not
used. Preserve the host's existing configuration and permissions; the delivery
adds no role or Skill discovery configuration. The delivered fields and the
late-stop boundary are in the Codex-only recovery reference.

## Core Skills and their sources

After `graphtraj setup` installs the core Skills, invoke `$setup-project` to
configure task tracking and domain documents. It explicitly asks whether the
project includes work needing software engineering delivery. Small helper
scripts remain direct work with proportionate validation, even in a project
that also has engineering tasks.
`setup-project` is GraphTraj's name for its adaptation of Matt Pocock's
`setup-matt-pocock-skills`. `graphtraj setup` prepares the Harness; the Skill
guides the project-document configuration.

The release bundles these 18 core Skills. The table describes the bundled
workflows and their GraphTraj adaptations; user-installed Skills outside this
set are managed separately. Matt Pocock sources are from
[mattpocock/skills](https://github.com/mattpocock/skills).

| Project Skill | Source | GraphTraj adaptation |
| --- | --- | --- |
| `setup-project` | Matt Pocock: `setup-matt-pocock-skills` | Asks which work the project includes; shared setup stays in the entrypoint, coding setup is read conditionally. Project Documents belong to the Harness Project Root. |
| `grill-with-docs` | Matt Pocock: same name | Retains the interview and domain-modeling composition. |
| `grilling` | Matt Pocock: same name | Retains the decision-tree interview workflow. |
| `domain-modeling` | Matt Pocock: same name | Shared terminology and decisions in the entrypoint; code checks and architecture examples in a conditional reference. Main owns Project Documents. |
| `to-spec` | Matt Pocock: same name | Retains the software specification workflow; refers to `setup-project` for configuration. |
| `to-tickets` | Matt Pocock: same name | Code tickets preserve accepted task nodes, acceptance and dependencies; add justified difficulty and execution budgets as YAML front matter. |
| `implement` | Matt Pocock: same name | Team Engineers self-review and return evidence to their Leader, who schedules Reviewers; standalone work retains the code-review step. |
| `code-review` | Matt Pocock: same name | Distinguishes Leader-owned Team Review from standalone review orchestration; assigned Reviewers perform only their supplied axis. |
| `resolving-merge-conflicts` | Matt Pocock: same name | A dispatched Resolver stages the result for Main to commit and validate; incompatible accepted requirements return to Main. |
| `tdd` | Matt Pocock: same name | Retains the upstream test-driven development workflow. |
| `ponytail` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | Bundled minimal-implementation guidance, with no GraphTraj-specific changes to its instructions. |
| `ponytail-review` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | Bundled over-engineering review guidance, with no GraphTraj-specific changes to its instructions. |
| `task-delivery` | GraphTraj | General readiness, executor selection, dispatch, acceptance and integration; coding dispatch is conditional and the coding Leader owns its specialist workflow. |
| `task-breakdown` | GraphTraj | General goal-to-task decomposition with observable results, completion criteria and genuine blocking dependencies. |
| `research` | Matt Pocock: same name | Primary-source investigation; software source checks are a conditional reference. |
| `retro` | Matt Pocock: same name | Session-based improvements to Agent work; coding checks and review standards are a conditional reference. |
| `wayfinder` | Matt Pocock: same name | Retains the shared decision map; general rough artifacts do not automatically invoke software prototyping. |
| `prototype` | Matt Pocock: same name | Retains the software UI and logic prototype workflows with an explicitly software-scoped description. |

General Skill entrypoints load only their shared method. They read a domain
reference when the current task calls for it; they do not load all references
before choosing. Software-specific Skills remain independent and are selected
for the coding role's work. Existing explicit-only invocation policies are
preserved; a returned Skill name is not assumed to activate another Skill.

When Main or the user retires a Team, Runner reads the packaged retirement
instructions as an ordinary Team Leader role resource and injects them only
into that Leader's final Session request. Normal Team completion and other
roles do not receive them. The final response remains in the Leader's Session
Trace for the successor, while a user-installed Matt Pocock `handoff` Skill
remains independent.

## Configuration and roles

All bundled Skill bodies and references live in `resources/skills` and install
through the same path. GraphTraj child definitions in `resources/roles` hold
responsibilities and required Skills independently of Codex configuration
syntax. `configuration/role_definitions.py` resolves these definitions and their logical
dispatch constraints with the Runtime, model and connection settings selected
in `.graphtraj/roles.yml`.

Runner passes the resolved child role to the Codex Adapter. The Adapter
locates its Skills and translates that role into native launch arguments,
permissions, Hooks and session calls. `resources/codex` contains only the
Codex integration: native child permission/Hook settings, reasoning settings
and tool-event handling. Main has no Runner child preset or managed Runtime
configuration template.

The default `.graphtraj/config.yml` is:

```yaml
version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state
agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
```

Paths resolve from the Harness Project Root. `dispatch_depth` limits formal
descendants below Main; a Team Leader is depth 1 and its children depth 2.
`max_concurrency` limits executing Agents across the project. Operating-system
locks enforce capacity; lock-file presence is not occupancy. A normal Batch
starts all its tasks or none. Team delivery also works at capacity one, with
the two Reviewers running sequentially in the same Round. A child Batch beyond
`dispatch_depth` returns `authority-denied` before registration. Runner counts
the retained parent Session chain; resuming a Leader adds no depth. Delegated
roles other than the Leader cannot launch Batches through Main's entry point.

`.graphtraj/roles.yml` groups coding presets under `roles.coding-team`; shared
`delivery-state` remains directly under `roles`. Batch references use names such
as `coding-team.team-leader` or `coding-team.spec-reviewer`. Each preset selects `runtime`
and `model`, with optional `reasoning_effort`, `base_url` and `api_key_env`. The latter names an
environment variable, never stores the credential. Omitted settings use the
Runtime's defaults. Team Leader additionally supports `allow_runtime_swarm`,
which defaults to true. Presets include Team Leader, one unified Engineer, both
Reviewer axes, Delivery State and Merge Resolver. Main's already selected
Runtime is outside these presets.

Set `reasoning_effort` on a role when its model needs a different reasoning
level. For example, this entry inside the existing `roles` mapping selects
`high` for the Engineer:

```yaml
coding-team:
  engineer:
    runtime: codex
    model: gpt-5.6-terra
    reasoning_effort: high
```

The Runtime Adapter interprets this setting. Codex maps it to
`model_reasoning_effort`; omission keeps the bundled role default. Invalid
values produce a configuration error. The effective setting is preserved on
Session continuation. Batch inline roles accept the same optional field.

A task can use a preset name or a one-entry inline role with the same Runtime
settings. Inline roles stay in their Batch and never become presets
automatically. Fixed role instructions, file access and dispatch permissions
are bundled policy; role settings cannot replace them. Setup does not generate
Runtime-specific child-role directories.

Engineer child tasks select Repository Skills explicitly through their `skills`
list. Other role tasks do not accept that field; Session resumption preserves
the original Adapter selection.
In the default same-directory layout, Source history distinguishes a tracked
Repository Skill from a Harness-owned Skill at the same physical path.

## Deliver accepted Tickets

Use the installed `task-delivery` Skill for the full workflow. Main registers
accepted GitHub Issue definitions and dependencies, generates the current
graph with `graphtraj ticket graph`, and selects ready Tickets.
Only validated `dev` integration satisfies a dependency.

Main activates ready Tickets' Team Leaders with a block-style YAML swarm input:

```yaml
tasks:
  - ticket_id: "123"
    role: coding-team.team-leader
    instruction: Deliver the current accepted Ticket.
```

`ticket_id` is Main's own DAG selection result; the Ticket name, scope,
investigation findings and completion conditions come from that registered
Ticket's current definition, so the input never repeats them. The input selects
work; its optional instruction adds concise dispatch details to the accepted
definition. Several ready Tickets may share one input when capacity permits. It
has no Delivery Run identifier or input-level Runtime setting. A Session that
already works inside one Ticket writes each task as its role and launch
instruction alone, and the entry resolves that Ticket from the calling Session.

Run public commands from the Harness Project Root:

```text
agent-runner --swarm-input swarm.yml
agent-runner status [<alias>...]
agent-runner status --operation-total [<alias>...]
agent-runner status --baseline <commit-or-ref> --candidate <commit-or-ref> <alias> [<alias>...]
agent-runner requests <alias> [--execution-id <native-execution-id>]
agent-runner reply <alias> --request-file request.yml --response '{"decision":"decline"}'
agent-runner send <alias> --instruction <text> --caused-by-event-id <event-id>
agent-runner send <alias> --instruction <text> --caused-by-event-id <event-id> --reports-only
agent-runner interrupt <alias>
agent-runner handle-abnormal <alias>
agent-runner continue --ticket-id <id> --caused-by-event-id <event-id>
agent-runner replace <member-alias> --caused-by-event-id <event-id>
agent-runner replace <leader-alias> --actor main --caused-by-event-id <event-id>
graphtraj ticket graph
graphtraj worldline read
graphtraj worldline render
graphtraj ticket integrate --ticket-id <id> -- <validation-command> <arguments>
agent-runner cleanup --ticket-id <id>
```

Each coding Team Leader schedules its Engineer and both Reviewers through the same
Runner, against a fixed candidate and comparison point, then makes the final
adversarial decision. Process corrections stay in the current Team Round.
Only a compliant implementation rejection confirmed by the Leader opens the
next Round. Main or the user can retire a Team; replacement retains the Ticket
branch and Worktree, and reads the prior Leader's final response from its Trace.
Replacing another member changes only that seat, and the Runner's recorded
direct parent decides who may replace it.

Continue an unfinished Team with its original Leader launch after deciding the
next action. Runner reuses retained Sessions, the Worktree, candidate, and valid
reports. A missing or invalid report returns to its author with the failure,
Trace, and expected report. A Leader can request correction in `leader.md` with
`Decision: CORRECT`, `Responsible: coding-team.spec-reviewer` (or the responsible
member), `Rule:`, `Reason:`, and `Candidate commit:`. A retained remaining-axis
Batch takes precedence over an older correction judgment; it needs no second
registration. Completing the last missing report needs no additional Review
Batch. System/provider failures return to the caller for an explicit later
retry through `send`; `status` reports the existing Session and last outcome.

After a sampled budget stop, Main analyzes the cause and records its chosen
action in the existing Worldline. Apply any required corrections or accepted
budget revision, then explicitly use `agent-runner continue` with that decision
to resume unfinished Team work. A budget edit alone does not resume execution.
Original elapsed time, consumption, sampling history and valid results remain;
continuation does not replace the Team or bypass acceptance.

Status diagnostics are on demand and do not affect delivery decisions. For a Codex
Session, `--operation-total` counts each native `response_item` tool request once
by its native identifier in that Session. `function_call` and `custom_tool_call`
use `call_id`; `local_shell_call` and `tool_search_call` use `call_id` or their
legacy `id`; `web_search_call` and `image_generation_call` use `id`, as defined by
the [Codex 0.153.0 protocol](https://github.com/openai/codex/blob/rust-v0.153.0/codex-rs/protocol/src/models.rs#L959-L1122).
This counts one `exec` request even when it runs a compound command, includes
failed requests, and excludes messages, tool outputs, and `event_msg` execution
views.
An inspected Codex 0.153.0 Session had 54 native `exec` wrappers alongside 135
`CommandExecution` and 11 `FileChange` execution views; those views are not added
to the native request total.
The `--baseline` and `--candidate` pair resolves both references to commits in the
selected Session's Worktree and reports Git `--numstat` records for their resulting
change. Binary additions and deletions are shown as `null`, matching Git's `-`
fields rather than inventing line counts.

The project graph keeps required predecessor relationships across delivery
stages, including completed predecessors. Completion removes waiting, not the
edge. Source-node descriptions record other origins without creating artificial
blocking dependencies.

Main corrects Ticket boundaries or dependencies when delivery evidence
disproves them, using `graphtraj ticket revise --revision-file <revision.yml>`.
Product-preserving graph corrections retain prior definitions and evidence;
product changes or new external authority require user direction. Delivery
State records supplied semantic decisions through validated commands; Runner
records only the execution facts it observes.

Main integrates accepted candidates serially into `dev` and supplies the
project's validation command. For an actual textual or semantic conflict,
the integration command accepts `--resolve-conflict <diagnosis>` to dispatch
a Merge Resolver. Successful Team Review alone does not merge a candidate.
Cleanup verifies integration and a clean disposable Worktree, removes safe
live mappings and the Ticket Worktree/branch, and preserves durable evidence.

## Codex Session interface in Python

`graphtraj.runtimes.codex.app_server.CodexAppServer` provides native Session
control using Codex 0.153.0's stdio app-server. Runner Session workers use this
Adapter and retain the connection and native Trace after a launch or send caller
returns. The existing registered-task inline-role launch returns `launched` with
an alias and native `session`; coding Team scheduling still follows its existing
workflow.

For a coding Team, `launch_batch(parse_batch(document), root)` runs the selected
Leader's normal Round through the same Worker and Adapter. The Leader registers
one Engineer, then both Reviewers for the fixed candidate, and makes the final
decision after collecting their reports. A two-Reviewer Batch that cannot fit
starts neither Reviewer and returns `insufficient-capacity` to the same Leader
Session. The Leader registers the Reviewers separately to proceed at capacity
one; the stopped parent's position transfers to each child in turn.

`read_graph(state)` exposes the Ticket's `implementing`, `reviewing`, and
`awaiting-integration` states. `read_worldline(state, root)` supplies the fixed
candidate and the final `team-round-accepted` event. A Leader can be idle while
its children execute; Session completion alone is not Team acceptance. Current
Round reports remain under `tickets/<id>-<name>/teams/<generation>/rounds/<round>/`.

Query `status_aliases([alias], root)` to get `session`, `execution_id`, and
`activity`. An idle execution has `last_outcome`: `completed`, `runtime-error`,
or `interrupted`. These describe native execution, independently of the service
PID. The native result, final answer and error details are retained in the
Session's `execution.yml`; `stderr.log` retains Runtime diagnostics.

`status_tree(root)` reads the Session records the Runner retained for this
project instead of an alias list, so one query reports the whole Agent tree:
each node's recorded `parent` and `children`, plus its status. A live Session
sees the subtree rooted at itself; Main and the user see each recorded
top-level Session and its subtree. The caller itself and its recorded direct
children keep the full status, and every deeper Session keeps the coarse
activity and last outcome. A record that cannot be read, or one Session whose
status cannot be judged, carries its own `error` while the rest of the tree
still returns. `agent-runner status` with no alias prints this document, and a
later caller reads the same tree from those records.

While a Worker holds an execution it publishes a heartbeat record in the
Session directory, including through every normal wait: a watchdog delay, a
waiting child, a running tool or a pending request reply. The record updates
independently of model output, so a quiet native Trace is not read as failure.
When the Worker does not answer a control request within the control timeout,
status reports `activity: unreachable` while the owner it recorded still holds
the process (lost contact, not death) and `activity: abnormal` when that owner
is gone, or its process identifier now belongs to another process, without a
terminal record; either report adds `heartbeat_at`, the last moment that owner
held the execution. Ownership is proven by the lock the Worker holds in the
Session directory, which the operating system releases when the process ends,
so a reused process identifier cannot pass for the recorded owner. An existing
terminal record is never overturned by a missing or stale heartbeat.

`send_instruction(alias, text, root, (event_id,))` uses native active input when
running. For an idle Session it starts a Worker that restores the same native
conversation and its resolved Context. A continuation gets a new execution ID
and preserves the alias and Session ID. Each send must cite an existing Project
Worldline event. `interrupt_session(alias, root)` stops the target and every
recorded descendant directly, without asking intermediate Agents to relay it.
Its `members` results distinguish `interrupted`, already `stopped`, and
`unconfirmed` members; the overall `interrupt_status` is `incomplete` if any
member cannot be confirmed. Other branches keep running. The stopped subtree
cannot create or resume work, including through `send` or report collection.
This prohibition persists on the old entities after replacement; Sessions,
aliases and evidence remain retained. Ordinary native completion still permits
continuation. A send racing native completion never silently queues input.

`handle_abnormal_session(alias, root)` handles one Session the existing
judgement reads as abnormal, which is an execution whose recorded owner is
gone without a terminal record. It sends the notice to that Session's recorded
direct parent through the parent's own execution, so the parent receives the
abnormal facts together with the stop result of every member, and stops the
whole descendant subtree exactly as `interrupt_session` does. A Session that
is running, normally waiting, unreachable or already finished changes nothing:
the result reports the observed `activity` instead. The CLI and MCP entries
are `agent-runner handle-abnormal <alias>` and `handle_abnormal`.

The Worker closes its connection after the terminal result. A send made
during that close waits for the prior owner to finish. The
private file control endpoint is shared by Runner callers; it needs no global
service or listening socket. Runtime permissions and the existing capacity and
budget checks still apply. Native requests without a response handler fail
visibly through the direct Adapter; managed Workers route them to public callers.

For a managed execution, `pending_requests(alias, root)` queries pending native
interactions after the launch caller has exited. The result contains `alias`,
`session`, `execution_id` and `requests`. Each request contains its native
`request_id` (integer or string), `method`, unmodified `params`, `session`,
`execution_id` and a `request_token`. Queries do not consume requests. Pass
`execution_id=...` to query only a previously observed execution; a successor
mapping is rejected. A completed execution returns an empty request list.

```python
from graphtraj.execution.runner_control import pending_requests, reply_to_request

pending = pending_requests(alias, root)
request = pending["requests"][0]  # Explicitly select and inspect the request.
print(request["method"], request["params"])
# After deciding to decline this command approval:
reply_to_request(alias, request, {"decision": "decline"}, root)
```

The installed CLI calls these same operations. `agent-runner requests <alias>`
emits YAML; save the selected entry from its `requests` list as `request.yml`.
Then use `agent-runner reply <alias> --request-file request.yml --response
'{"decision":"decline"}'`. Supply the native response for the reported method:
command approval accepts an explicit `{"decision":"accept"}` or
`{"decision":"decline"}`; user input uses its native `answers` object. GraphTraj
does not infer a decision or translate response schemas.

While waiting, status remains `activity: running` with
`waiting_for: runtime-request`. The Worker retains the execution and its capacity;
`interrupt` still targets that execution. Human replies have no RPC deadline.
Withdrawal, interruption or connection close ends the wait. Replies must match
the Session, execution and one-time request token; duplicate or stale replies
cannot answer another request, even if Codex reuses a native ID. `reply_status:
submitted` acknowledges delivery to the owner's callback; query status and the
native Trace for the eventual Runtime result. Requests live only in the Worker
and its existing temporary control channel, with no permanent interaction ledger.
Permissions, native response decisions and user Runtime configuration remain in
effect.

A real registered-task probe, including input consumption, continuation,
interruption and native Trace comparison, is available in the source checkout:

```sh
CODEX_MANAGED_REAL=1 python -m pytest -p no:cacheprovider -q \
  tests/test_managed_sessions.py -k real_registered
```

It uses an isolated project, installation and native store with the operator's
Codex connection settings. `CODEX_MANAGED_MODEL` can select the model;
`CODEX_MANAGED_WAIT` sets the observation timeout in seconds (default 120).
Model/network failures fail this check and retain the actual operations and
native diagnostics in the pytest temporary project.

A focused recovery probe uses one real Spec Session and controlled peers. It
loses the current report copy, then checks same-Session report delivery while
preserving the candidate and unaffected evidence:

```sh
CODEX_RECOVERY_REAL=1 python -m pytest -p no:cacheprovider -q -s \
  tests/test_team_recovery.py -k 'missing_current_review and native'
```

`CODEX_RECOVERY_MODEL` selects the model and `CODEX_RECOVERY_WAIT` sets each
operation's timeout (default 900 seconds). The probe prints its isolated root,
Runner and Reviewer alias. Use that Runner's `requests` and `reply` commands
from the printed root for any native approvals; the probe does not choose
responses or modify the operator's configuration.

The normal coding-Team probe uses real Agents for a tiny greeting implementation,
its validation, both Review axes and the Leader decision:

```sh
CODEX_TEAM_REAL=1 python -m pytest -p no:cacheprovider -q -s \
  tests/test_team_session_delivery.py -k real_small_team
```

It installs a clean candidate export in an isolated project and copies the
operator's native connection settings into a temporary store. It preserves the
operator's configuration. `CODEX_TEAM_MODEL` selects the model,
`CODEX_TEAM_CAPACITY` sets project capacity (default 1), and `CODEX_TEAM_WAIT`
bounds the check in seconds (default 900), including time for explicit approval
decisions. The probe prints its isolated root and installed Python/Runner paths
and saves them in `real-team-control.json`. Keep the probe running while handling
requests from another caller using that installation; no bootstrap tool upgrade
is needed.

The probe queries the existing `pending_requests` operation and prints each new
native request, retaining its full identity and contents in
`real-team-requests.jsonl`. Inspect each request's method, command or file changes,
cwd, and requested access against the isolated Ticket. Then query that alias's
current requests and explicitly submit the chosen native response using
`reply_to_request` or the installed `requests` / `reply` CLI described above. The
decision and reply result should be retained with the probe evidence. The
probe never chooses or sends an approval response, and it leaves native
permissions and the operator's Runtime configuration in effect.

The temporary project retains inputs, results, its control-operation results,
cleanup observations and native diagnostics. Before interrupting on timeout, it
also retains unresolved native requests for diagnosis; those observations are not
replies and their tokens expire with the execution. A network failure or an
unanswered request leaves the genuine Team check incomplete.

Pass the immutable `RuntimeContext` returned by the existing
`preflight_runtime_context(...).finalize()`. Its `session_document()` projects
the resolved role instructions, model, effort, selected Skills, Worktree and
native task/report permissions. It does not change persistent Codex configuration.

```python
from pathlib import Path
from graphtraj.runtimes.codex.app_server import CodexAppServer
from graphtraj.runtimes.runtime_adapter import RuntimeContext

async def execute(
    context: RuntimeContext,
    worktree: Path,
    trace_file: Path,
    prompt: str,
):
    async with CodexAppServer(
        cwd=worktree,
        environment=context.runtime_environment(),
    ) as adapter:
        session = await adapter.create_session(context)
        adapter.retain_native_trace(session, trace_file)
        execution = await adapter.start_execution(session, prompt)
        result = await adapter.wait(execution, timeout=600)
        return session.thread_id, session.rollout_path, result
```

Within the same connection, use `start_execution(session, text)` again for idle
continuation, `send_input(execution, text)` for active input, and
`interrupt(execution)` followed by `wait(execution)` to confirm interruption.
On a new connection, `resume_session(context, thread_id)` loads the same native
conversation with the supplied Context. Handles belong to the connection that
returned them. The result contains `outcome` (`completed` or `interrupted`),
`session_id`, `execution_id`, and `last_agent_message`. Native execution failures
raise `RuntimeAdapterError`; no service PID or process exit code substitutes for
an execution identity or result.

One connection can own independent Sessions with different roles, models,
efforts and permissions. Sessions with different endpoint or credential settings
need separate connections with their respective `runtime_environment()` overrides.
Use one asyncio event loop and close the Adapter explicitly or with `async with`.
Turn completion leaves the service usable. Explicit close affects every Session
on that connection and reaps its service process.

For interaction, pass an async `on_request(request)` callback to the constructor.
It receives `CodexServerRequest(request_id, method, params)` and returns the
native response mapping, such as `{"decision": "decline"}` for a command approval.
Requests are answered using their original IDs while other Sessions continue.
Return `None` for an unsupported method. Missing, failed or timed-out handlers
receive a native error response and surface `RuntimeAdapterError` to the owner;
connection requests without an execution identity invalidate the connection.
Handlers must yield to the event loop and cooperate with cancellation. Native
`serverRequest/resolved` cancels a withdrawn request's handler.

Call `retain_native_trace(session, trace_file)` once after `create_session` or
`resume_session` when the complete native Session record is required. It waits
for the Runtime to create the rollout at `session.rollout_path` and then makes
the Trace entry a symbolic link to that Runtime-owned file, so readers see the
native content, order, timestamps and encrypted fields unchanged, including
records appended while the Session runs. GraphTraj writes nothing through the
link. Reuse the same Trace entry after continuation: a resumed Session keeps
reading the same native file, so retained records are not copied again. A Trace
entry that already holds an earlier copied record set keeps that content
unchanged.

`create_session` and `resume_session` accept an optional native `approval_policy`,
including `"untrusted"` or `"never"`. By default, directory trust, approval policy
and approval reviewer are resolved by Codex from its native configuration;
GraphTraj does not impose overrides for them. Native requests that require a
client response are routed to the callback.
This is a thread parameter. Codex 0.153.0 rejects `approval_policy = "untrusted"`
in its configuration file. The callback routes native approvals, tool/input,
MCP elicitation, authentication and attestation requests without translating
their response schemas. Command approval has prior live evidence; the other
request types have controlled protocol checks, not equivalent live coverage.

An observer should drain `next_notification()` for raw native control events.
They retain native IDs and include retry/error notifications. They do not replace
the rollout at `session.rollout_path`; `retain_native_trace` links that
complete native record into the Trace.
The Adapter buffers notifications for that observer, accepts JSON lines up to
16 MiB, and retains the last 16 KiB of stderr in `stderr_tail` for diagnostics.

`request_timeout` bounds RPCs, request handlers and each shutdown grace period.
A separate `request_handler_timeout` overrides only the callback deadline;
`None` lets a caller wait for human input until native cancellation or close.
Managed Workers use this override while keeping RPC and shutdown timeouts bounded.
A timeout or cancellation while waiting for an execution leaves it owned and
allows another wait or targeted interrupt. An abandoned control RPC has an
uncertain native outcome: its connection becomes unusable and must be closed.
Native startup/completion races can return `CodexRPCError`, which retains
`method`, `request_id` and `native_error`. A newly accepted turn can still be
initializing; use native activity notifications when timing active control.

## MCP host tools

The installed `graphtraj-mcp` command serves the same Python operations to a
host Agent over MCP stdio. It is an ordinary console entry point of this wheel
and speaks newline-delimited JSON-RPC 2.0 (`initialize`, `tools/list`,
`tools/call`, `ping`) using only the standard library. Python 3.12 or newer plus
the dependencies already in this distribution are enough; no MCP SDK or other
dependency is added.

Install it like the other commands:

```text
uv tool install "git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>"
```

Register the server with Codex, either through the CLI:

```text
codex mcp add graphtraj -- graphtraj-mcp
```

or directly in the host configuration:

```toml
[mcp_servers.graphtraj]
command = "graphtraj-mcp"
args = []
cwd = "/absolute/path/to/harness-project-root"
startup_timeout_sec = 30
tool_timeout_sec = 30
```

The server reads the Harness Project Root from its own working directory,
exactly like the CLI, so set `cwd` to that root or start the host there. Keep
the host configuration isolated (a separate `CODEX_HOME`) when validating the
tools against a temporary project.

A host passes an MCP server a filtered environment. When the dispatched Runtime
needs a setting that the server does not inherit, declare it on the server
itself, for example:

```toml
[mcp_servers.graphtraj.env]
CODEX_HOME = "/absolute/path/to/codex-home"
```

The tools are the existing graph, execution, control and interaction operations:

| Tool | Structured input | Result |
| --- | --- | --- |
| `ticket_graph` | none | Current Tickets, states and dependency readiness; the same document as `graphtraj ticket graph`. |
| `ticket_register` | One accepted definition: `ticket_id`, `ticket_name`, `source`, `title`, `body`, `dependencies`. | `ticket_directory` of the registered Ticket; the same operation as `graphtraj ticket register`. |
| `ticket_revise` | One product-preserving revision: `product_preserving`, `caused_by_event_ids`, `evidence_refs`, `tickets`. | Recorded causal event; the same operation as `graphtraj ticket revise`. |
| `ticket_update` | One evidence-backed state change: `ticket_id`, `status`, `active_team_ordinal`, `worktree`, `branch`, `current_candidate`, `caused_by_event_ids`, `evidence_refs`. | Recorded causal event; the same operation as `graphtraj ticket update`. |
| `alias_status` | optionally `aliases`, `operation_total`, `baseline`, `candidate`. | Session status document, or the visible Session tree when `aliases` is omitted; the same document as `agent-runner status`. |
| `swarm` | One structured swarm input: `tasks` with `role` (a preset reference or one inline role), optionally `instruction` and `skills`, and the `ticket_id` Main selected from the DAG. | Each activated Agent's `launch_status`, `alias` and `session`; the same document as `agent-runner --swarm-input`. The call returns while those executions stay owned, and later calls address the returned alias. |
| `send_instruction` | `alias`, `instruction`, `caused_by_event_ids`, and optionally `reports_only`. | `send_status`; the same operation as `agent-runner send`. |
| `interrupt` | `alias`. | `interrupt_status`; the same operation as `agent-runner interrupt`. |
| `handle_abnormal` | `alias`. | `handled`, the observed `activity` and, for a handled abnormality, the `interrupt_status` with the `notice` delivery record; the same operation as `agent-runner handle-abnormal`. |
| `continue` | `ticket_id`, `caused_by_event_ids`. | The continued Team's result and `continuation_event_id`; the same D.3 stop/continue operation as `agent-runner continue`. |
| `pending_requests` | `alias`, and optionally `execution_id`. | The pending native approval or user-input requests, with the identity `reply_to_request` needs; the same document as `agent-runner requests`. |
| `reply_to_request` | `alias`, the `request` document returned by `pending_requests`, and an explicit `response` object. | `request_id` and `reply_status`; the same operation as `agent-runner reply`. |

Each tool calls the same Python operation as its CLI command, takes structured
input instead of file paths or terminal text, and returns the shared document as
`structuredContent`. The text content is the CLI's own YAML rendering of that
document. A rejected operation returns `isError: true` carrying the message the
CLI reports for the same input. Later tools register through
`graphtraj.interfaces.mcp.register_tool(name, description, input_schema,
handler)`.

A Codex host sends its calling thread on every tool request. When the server
receives `params._meta.threadId`, it routes live budget notices to that Main
through the same recovery binding the CLI uses: an enforced stop returns with
that tool call as `stop_deliveries`, carrying the deterministic stop identity,
the stop's own absolute instant, the elapsed duration and the explicit `$retro`
instruction with the `retro` Skill path, using the existing
`CodexMainRecovery` retention and deduplication. Ordinary elapsed and allowance
reminders stay ordinary notices. Without that request metadata, or without the
installed Skill at `.agents/skills/retro/SKILL.md` in the server's working
directory, the tools keep their generic behaviour and run without a caller
notice channel; such a stop is only retained in the Ticket's
`execution-budget.yml` and reported to the Team Leader. Nothing here writes Main
developer instructions or user Runtime configuration, and no stop is queued into
the host's native input.

A host can run the whole loop from tools alone: `swarm` a launch input, read
identity, activity and outcome with `alias_status`, steer the owned execution
with `send_instruction`, answer a waiting native request with `pending_requests`
plus `reply_to_request`, interrupt one execution with `interrupt`, and continue a
stopped Team with `continue`. Every call runs the same Python operation as its
CLI command against the same Harness Project, so a user can start work from the
terminal and control it from the host, or the other way round; no CLI text is
parsed and no second state store exists. `continue` is the existing stop/continue
path: it resumes the retained Team Batch, keeps the already consumed budget and
records one continuation event. Replace, retire and cleanup are not exposed.

To watch an isolated host discover and call the tools without a model turn, use
the Codex app-server MCP client requests:

```python
import json, os, subprocess

host = subprocess.Popen(
    ["codex", "app-server", "--listen", "stdio://"], cwd=project_root, text=True,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    env={**os.environ, "CODEX_HOME": isolated_codex_home},
)
def request(request_id, method, params):
    host.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                                 "params": params}) + "\n")
    host.stdin.flush()
    while True:
        message = json.loads(host.stdout.readline())
        if message.get("id") == request_id:
            return message

request(1, "initialize", {"clientInfo": {"name": "probe", "version": "0"}})
host.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "initialized",
                             "params": {}}) + "\n")
thread = request(2, "thread/start", {"cwd": str(project_root)})["result"]["thread"]["id"]
inventory = request(3, "mcpServerStatus/list",
                    {"threadId": thread, "detail": "full"})["result"]["data"]
called = request(4, "mcpServer/tool/call",
                 {"server": "graphtraj", "threadId": thread,
                  "tool": "ticket_graph", "arguments": {}})["result"]
print(inventory[0]["tools"].keys(), called["structuredContent"])
```

On this checkout the installed entry point and the real host client are
exercised together with:

```text
pytest -p no:cacheprovider -q tests/test_mcp_host_tools.py
CODEX_REAL_MCP_HOST=1 pytest -p no:cacheprovider -q tests/test_mcp_host_tools.py
```

The first command covers discovery, every tool and CLI equivalence through the
installed server, including a dispatched child whose Runtime work is substituted
by a controlled peer and a stopped-Team continuation. The second additionally
drives an installed Codex app-server with a temporary `CODEX_HOME` and an
isolated MCP server configuration: it discovers the tools, dispatches one
managed child, and then queries, steers, answers, interrupts and continues that
child through host tool calls. It needs an installed `codex` executable and no
model access; its exchange is retained under `/tmp/mcp118-host/probe.log`.

## Evidence and limits

Each Ticket retains its initial definition, accepted revisions, current state,
successive Teams, closed Round reports and append-only Session Traces. Exact
Batches and the sharded Project Worldline connect the causal history.
Readiness and ledger-shaped views are generated on request; they are not
additional persisted state. Session aliases identify historical conversations,
not processes or invocation counters.

Historical `state/<run-id>` directories are left byte-for-byte untouched.
GraphTraj does not migrate them, read them as fallback or offer compatibility
for the old project command, Run-based Batch syntax or configuration sources.

The current Adapter supports Codex. Dispatched coding Teams use Runner for
formal implementation and Review. Permitted Team Leaders may use Runtime-native
helpers only for temporary read-only investigation; those helpers have no
independent GraphTraj Trace and cannot occupy a Team seat. Engineers and
Reviewers cannot dispatch child Agents or start another Runtime. Main's
Runtime and helper settings remain under user control.

GraphTraj has no queue, daemon, automatic crash-recovery service or automatic
release promotion. One Harness Project contains one Source Repository.


The test suite exercises installed commands with controlled Runtime behavior.
With an authenticated supported Codex executable, run the narrow live Adapter
probe explicitly:

```text
CODEX_REAL_ACCEPTANCE=1 pytest -p no:cacheprovider -q tests/test_harness_root_runtime.py -k test_real_codex --tb=short
```
