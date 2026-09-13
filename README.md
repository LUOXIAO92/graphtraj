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
| `execution.runner_batch` | `parse_batch(document)`; `read_batch(path, cwd)` | Existing validated `Batch`. File input retains its exact bytes; a Python dictionary retains equivalent YAML. |
| `execution.runner_launch` | `launch_batch(batch, cwd)` | Existing `LaunchResponse` with `document` and `succeeded`, including per-task failures. |
| `execution.runner_status` | `status_aliases(aliases, cwd, operation_total=False, baseline=None, candidate=None)` | Existing `StatusResponse` with `document`, `succeeded` and `errors`. |
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
which defaults to true. Presets include Team Leader, Engineer tiers, both
Reviewer axes, Delivery State and Merge Resolver. Main's already selected
Runtime is outside these presets.

Set `reasoning_effort` on a role when its model needs a different reasoning
level. For example, this entry inside the existing `roles` mapping selects
`high` for the Senior Engineer:

```yaml
coding-team:
  engineer-senior:
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
graph with `graphtraj ticket graph`, and selects ready Tickets and difficulty.
Only validated `dev` integration satisfies a dependency.

Main dispatches ready Tickets to Team Leaders with a block-style YAML Batch:

```yaml
tasks:
  - ticket_id: "123"
    ticket_name: example-feature
    role: coding-team.team-leader
    instruction: Senior difficulty. Deliver the current accepted Ticket.
```

The Ticket must already be registered. The Batch selects work; its optional
instruction adds concise dispatch details to the accepted definition. Several
ready Tickets may share one Batch when capacity permits. It has no Delivery
Run identifier or Batch-level Runtime setting.

Run public commands from the Harness Project Root:

```text
agent-runner --batch-input batch.yml
agent-runner status <alias> [<alias>...]
agent-runner status --operation-total <alias> [<alias>...]
agent-runner status --baseline <commit-or-ref> --candidate <commit-or-ref> <alias> [<alias>...]
agent-runner requests <alias> [--execution-id <native-execution-id>]
agent-runner reply <alias> --request-file request.yml --response '{"decision":"decline"}'
agent-runner send <alias> --instruction <text> --caused-by-event-id <event-id>
agent-runner interrupt <alias>
agent-runner continue --ticket-id <id> --caused-by-event-id <event-id>
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
Replacing another member changes only that seat.

Resume an interrupted Team with its original Leader Batch after deciding the
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

`send_instruction(alias, text, root, (event_id,))` uses native active input when
running. For an idle Session it starts a Worker that restores the same native
conversation and its resolved Context. A continuation gets a new execution ID
and preserves the alias and Session ID. Each send must cite an existing Project
Worldline event. `interrupt_session(alias, root)` targets the mapped execution
and waits for native confirmation; other Sessions keep running. A race with
native completion returns an operation error and does not silently queue input.

The Worker closes its connection after the terminal result and final Trace
drain. A send made during that close waits for the prior owner to finish. The
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
    trace_directory: Path,
    prompt: str,
):
    async with CodexAppServer(
        cwd=worktree,
        environment=context.runtime_environment(),
    ) as adapter:
        session = await adapter.create_session(context)
        adapter.retain_native_trace(session, trace_directory)
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

Call `retain_native_trace(session, trace_directory)` once after `create_session`
or `resume_session` when the complete native Session record is required. It
writes the Runtime identity and copies complete rollout JSONL records unchanged
to `trace_directory/events.jsonl` while the Session runs. Reuse the same Trace
directory after continuation; its retained native position prevents duplicate
history, waits for delayed rollout creation and incomplete trailing records,
and performs a final drain at terminal result or connection close.

`create_session` and `resume_session` accept an optional native `approval_policy`,
including `"untrusted"` or `"never"`; approval review is routed to the client.
This is a thread parameter. Codex 0.153.0 rejects `approval_policy = "untrusted"`
in its configuration file. The callback routes native approvals, tool/input,
MCP elicitation, authentication and attestation requests without translating
their response schemas. Command approval has prior live evidence; the other
request types have controlled protocol checks, not equivalent live coverage.

An observer should drain `next_notification()` for raw native control events.
They retain native IDs and include retry/error notifications. They do not replace
the rollout at `session.rollout_path`; `retain_native_trace` preserves that
complete native record separately.
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
