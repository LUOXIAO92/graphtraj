# agents public interface

This is the stable interface of the `agent-swarm` distribution (the `agents`
tool) and the rules for its version number. Anything this document does not
list is internal: module layout, private names, the records under the data
root, driver settings documents, log text and the wording of error messages
may change in any release.

Items marked **planned** are fixed here only as public semantics. The Task
named after them implements them and records the final details in this file.

The version is `agent_swarm.__version__`, defined in
`agent_swarm/__init__.py`. This is the single source: the distribution
metadata, the MCP `serverInfo` and the Codex `clientInfo` read it. The DSH
plugin manifest `agent_swarm/dsh/package.json` must repeat it, because an npm
manifest cannot import Python; the test
`test_mcp_server_version_is_the_single_package_version` fails when the two
differ.

## 1. What is public

### 1.1 Commands

**`agents '<request JSON>'`** sends one request and prints one JSON document
on stdout.

- The request is the progressive envelope described in 1.2 (`discover`,
  `describe`, `execute`).
- Exit status: `0` for a successful result, `1` when the result has failed
  (any `error` document, or an execution result marked failed), `2` for a
  command-line usage error.
- The CLI never takes an identity from its arguments. It forwards to the host
  that owns the calling process (`AGENT_SWARM_CONNECTION`). Without one, an
  installed host plugin (1.4) may claim the call. With neither, every request,
  including `discover`, fails with `authority-denied`.

**`agents-mcp`** is a stdio MCP server (newline-delimited JSON-RPC 2.0).

- Methods: `initialize`, `tools/list`, `tools/call`, `ping`. Other methods
  return JSON-RPC error `-32601`; unparseable input `-32700`; a non-object
  message `-32600`; an unknown tool or non-object arguments `-32602`.
- `initialize` returns `serverInfo: {"name": "agents", "version":
  <__version__>}` and echoes the client's `protocolVersion` (default
  `2025-06-18`).
- `tools/list` returns exactly one tool, `agents`, whose input is the 1.2
  envelope.
- `tools/call` returns `content` (one text item with the JSON document),
  `structuredContent` (the same document) and `isError`.
- It forwards over the same owner connection as the CLI and refuses the same
  way without one.

**Independent hosts.** The host commands documented in the README and its host
notes (`install/`) are public with their documented flags:

- `python -m agent_swarm.claude.host configuration --project <dir> --claude
  <path> [--write]` and `... serve --config <file>`. The written
  `.agents-control/claude-host.json` keys (`root`, `cwd`, `claude`,
  `channel_file`, `settings`, and since 0.1.2 the optional `runtimes`) and
  the documented `settings` keys are public. `settings` configures the
  host's Claude children. `runtimes` maps another Runtime's name to its
  driver settings: `codex` takes the document `agent_swarm.codex.host
  --settings` takes (`adapter_request`, optional `evidence`, `connection`);
  since 0.2.0 `dsh` takes the DSH driver settings (section 2, DSH children)
  and runs in `cwd`; since 0.2.1 `pi` takes the Pi child settings below and
  runs in `cwd`. A Runtime without an entry has no driver (`create`
  fails with `unsupported-runtime`). At start the host refuses another
  Runtime name (`unsupported-runtime`), a `claude` entry
  or a non-object value (`invalid-config`), invalid Codex settings
  (`invalid-config`), invalid DSH settings or a missing or unsupported DSH
  (the DSH codes in section 2), a `pi` entry as below, and whatever
  `AgentControl.require_connections()` refuses, each with its own code.
  The `context` operation is the plugin's private channel. The plugin this
  `configuration` command writes associates and lists the `agents` tool only;
  a package that adds its own tool writes its plugin as in 1.4.
- `python -m agent_swarm.codex.host --settings <file> --directory <dir>
  [--output <file>] [--resume] <instruction>`. Since 0.1.2 the settings file
  may hold an optional top-level `runtimes` object: a Runtime name to that
  driver's settings. The host removes it before reading its own Codex
  settings. `claude` takes the documented Claude host `settings` keys;
  since 0.2.0, `dsh` takes the DSH driver settings (section 2, DSH children);
  since 0.2.1, `pi` takes the Pi child settings below;
  all run in `adapter_request.worktree_path` and are checked at start. A
  Runtime without an entry has no driver (`create` fails with
  `unsupported-runtime`). At start the host refuses another Runtime name
  (`unsupported-runtime`), a `codex` entry or a non-object value
  (`invalid-config`), invalid DSH settings or a missing or unsupported DSH
  (the DSH codes in section 2), a `pi` entry as below, and whatever
  `AgentControl.require_connections()` refuses. On a startup error it prints
  `{"error": {"code", "message"}}` and exits `1`.
- A `runtimes.pi` entry of the Claude Code and Codex hosts (since 0.2.1) lets
  that host start Pi children without any GraphTraj Task. Its fields are the
  table *Pi child defaults* in 1.6, except `worktree_path`, which is the
  host's `cwd` (Claude) or `adapter_request.worktree_path` (Codex). These
  hosts have no Pi parent to inherit from, so:
  - `provider` and `model` are required. `create`'s `model`, `preset` and
    connection still choose per child (section 2). Without a declared
    connection, a chosen `model` is checked against the catalog of `pi` on the
    host's `PATH` in `PI_CODING_AGENT_DIR` (else `~/.pi/agent`), not against
    `executable` and `agent_dir`. If those differ, declare the connection's
    `models` (section 3).
  - `executable` defaults to `pi` on the host's `PATH`.
  - The other fields have the defaults in 1.6, where "the host's" means this
    Claude Code or Codex host.

  At start the host refuses with `invalid-config`, naming the field: an
  unknown field, `worktree_path`, a wrong type, a missing `provider` or
  `model`, or write access without a Git common directory. It also refuses
  with `invalid-config`, naming both paths, a data root inside the worktree
  (below). It refuses with `runtime-unavailable`, naming what is missing and
  the setting that fixes it: a missing Pi executable (`executable`); a
  `sandbox_python` that does not run or cannot import `agent_sandbox`
  (`sandbox_python`); `srt` or `node` not on the `PATH` the child gets, which
  is the host Python's directory followed by `sandbox_path` (`sandbox_path`);
  and an unset `api_key_env`. No message carries a credential value. A login
  file and Pi's catalog are not checked at start: a provider can authenticate
  through Pi's own `models.json`, and a catalog query can take 30 seconds.
  Those failures appear at `create`.

  **A `pi` entry needs the data root outside the worktree.** A Pi child must
  not read the data root (1.6) and the sandbox cannot deny a path inside a
  readable one, so every child would fail. For the Codex host, choose a
  `--directory` outside `adapter_request.worktree_path`. The Claude host's
  `configuration` command writes `root` as `<project>/.agents-control`, so set
  `root` in `claude-host.json` to a directory outside the project and move
  `config.yml` and any existing `control/`, `native/` and `sessions/` there
  with it. `channel_file`, the `host.log` two levels above it and the `--config`
  file are not under `root` and may stay in the project; they hold no
  credential, and a Pi child can read them there. Running `configuration
  --write` again resets `root` and `channel_file` and keeps `runtimes`, so the
  host refuses to start until `root` is set again. Without a `pi` entry the
  default layout is unchanged.
- A refused Claude host start answers every call with `host-unavailable` (or
  the refusing check's own code) and writes one JSON line to
  `.agents-control/host.log`.
- The Pi host: the agents Pi extension's `--agents-config <file>` flag and
  that file's keys (1.6). The extension starts `python -I -m
  agent_swarm.pi.host --config <file>` itself; its pipe protocol with the
  extension is private.
- The DSH host: the `AGENT_SWARM_DSH_CONFIG` variable naming that file and its
  keys (1.7). The agents DSH plugin starts `python -I -m agent_swarm.dsh.host
  --config <file>` itself; its pipe protocol with the plugin is private.

### 1.2 The `agents` tool and its features

Every entry (MCP, CLI, host-registered function) takes the same envelope:

| Field | Type | Used by |
| --- | --- | --- |
| `action` | `discover` \| `describe` \| `execute` | all, required |
| `query` | string | `discover`; words that must all match |
| `feature` | string | `describe`, `execute`; required there |
| `schema` | boolean, default false | `describe`; return only the input schema |
| `arguments` | object | `execute`; required there |

`discover` returns `{"features": [{"feature", "description"}], "describe":
{...}}`. `describe` returns `{"feature", "description", "input_schema"}`, or
`{"input_schema"}` with `schema: true`. `execute` validates `arguments`
against the feature's schema and returns the result document below.

Features and their arguments (`*` = required):

| Feature | Arguments | Result fields added to the Agent document |
| --- | --- | --- |
| `create` | `runtime*`, `instruction*`, `name`, `configuration`, `preset`, `model`, `reasoning_effort`, `workspace` (see 2), `extra_fields` (object, section 5) | none; returns once the Agent is registered, never waits for its work |
| `send` | `agent*`, `message*`, `reports_only` | `delivery: {at, delivery: submitted\|rejected\|unknown, error?}` when the Agent runs; in standby it continues the Session |
| `status` | `agent` | without `agent`: `{"agents": [document + "children": [...]]}`, the caller's visible hierarchy |
| `wait` | `agent*`, `timeout_seconds*` (finite, > 0) | `timed_out`; also ends early on an unanswered native request |
| `interrupt` | `agent*` | `interrupt: requested\|not-running\|already-requested\|stopped`, `scheduled`, `termination_confirmed` |
| `resume` | `agent*`, `message` (required in standby) | `resumed: false, reason: already-active` when it already runs |
| `requests` | `agent*`, `execution` | `requests: [native request document + "execution"]` |
| `reply` | `agent*`, `request*` (one document from `requests`), `response*` (explicit native response, or `{"answer"}` for a decision request) | the reply receipt; a repeat returns the first receipt with `duplicate: true`. Checked first under section 6 |
| `retire` | `agent*` | `retired: true`, `duplicate` on repeat |
| `ask_parent` | `kind*` (`decision` \| `resources`), `question*`, `timeout_seconds*` (finite, > 0) | `request`, `answer` (text or `null`), `timed_out`, on the caller's own Agent document; see 4 |

An unknown argument, a missing required one or an empty string is rejected.
Identity, permissions, working directory and parentage always come from the
host, never from arguments. `create`'s `workspace` only narrows the caller's
own working directory (section 2).

`ask_parent` is called by a
child about itself; a caller without an Agent reference is refused with
`authority-denied`.

`send`'s `reports_only` (boolean, default false): `true` delivers the message
only to collect results the Agent already holds; the Agent starts no new work.
A host or backend that cannot keep this limit rejects the request with
`not-implemented` instead of sending an ordinary message. agents' own backend
(`AgentControl`) cannot keep it and always rejects `true`; `false` or an
absent field is an ordinary `send`. A host that serves `reports_only` applies
its own rules for which Agents it accepts.

**Result document** of `execute`:

```json
{"action": "...", "agent": "...", "session": "...", "execution": "...",
 "message": null, "result": {"...": "..."}}
```

`agent`, `session` and `execution` are stable references or `null`.
`result` is the **Agent document** plus the feature's own fields:

- `agent`, `name`, `runtime`, `preset`, `connection`, `model`,
  `reasoning_effort`, `review` (the choice made at `create`, see 2), `workspace` (the
  assigned directory, `null` for the host's cwd), `state` (`active` or
  `standby`), `parent`, `creator` (`host`, `agent`, `session`), `host`,
  `session`;
- while running: `execution`, and when present `stopping`, `diagnostic`,
  `pending_requests` (count of unanswered native and decision requests);
- after an execution has ended: `last_result` with `id`, `outcome`
  (`completed`, `interrupted`, `failed`), `last_message`, `error` (`code`,
  `message`), `terminal_confirmed`, `ended_at`, and when present
  `termination_confirmation`, `runtime_exit`, `notification` (see 4);
- `retired_at` once retired.

The Claude Code host may add `main_notices` to the outer document (see 4).

**Errors.** A rejected request returns `{"action": ..., "error": {"code",
"message"}}` and is marked failed. The `code` is stable; the message is for
people and models and may change. Codes in use:

| Code | Meaning |
| --- | --- |
| `invalid-input` | malformed request, unknown or missing field, empty value |
| `authority-denied` | no owning host, or the caller may not do this; also a `reply` that grants more than the request asked |
| `unsupported-runtime` | no driver for the requested Runtime in this host |
| `invalid-config` | rejected driver configuration (any `configuration` in an independent host), an invalid `config.yml`, or a driver that cannot run the selected connection |
| `invalid-preset` | `preset` is not declared, or uses another Runtime than `runtime` |
| `invalid-model` | `model` is not a candidate, cannot be verified, or contradicts the preset |
| `invalid-reasoning-effort` | `reasoning_effort` is not supported by the model or Runtime, or contradicts the preset |
| `ambiguous-connection` | several connections declare the Runtime and no preset selects one |
| `workspace-denied` | `workspace` lies outside the caller's own workspace (after resolving links) |
| `runtime-unavailable` | the selected connection's Runtime is not installed or not logged in on this machine |
| `review-unavailable` | the connection's reviewer failed the connectivity check at `create` (section 6); the message holds the cause |
| `not-found` | no such Agent visible to the caller |
| `retired` | the Agent is retired |
| `active` | the Agent must be in standby first |
| `starting`, `stopping` | the execution is between states; try again |
| `not-owned` | another process owns the running execution |
| `not-running`, `stale-execution` | no current execution for this request |
| `no-session` | no native Session to continue |
| `termination-unconfirmed` | an ended execution's processes cannot be confirmed gone |
| `not-implemented` | the host lacks this capability; the message names the gap |
| `request-not-accepted` | the owner channel did not accept the request |
| `archive-unavailable` | no longer returned since 0.2.0: every host archives when saving is on (384) |
| `host-unavailable`, `host-busy`, `session-exists`, `turn-running` | host start and ownership refusals |
| `start-failed`, `delivery-unknown` | a native start or delivery failed without a native code |
| `call-cancelled` | a host serving calls concurrently stopped this call's wait, because its caller cancelled the call or its client went away |

An execution that fails natively keeps the Runtime's own code and message in
`last_result.error` (for example `RUNTIME_REQUEST_FAILED`). Those codes belong
to the Runtime driver; the ones the README documents are public.

`call-cancelled` is rarely read as a result. The Claude Code hosts run each
`tools/call` on its own thread, so a long `wait` does not block another call, and
the other hosts run calls one at a time. An explicit cancel sends no response at
all, so that caller never sees the code. When the client's input ends, the waits
stop the same way and a response carrying the code is still written, for a client
that may be gone. A host or consumer using `pause` or `run_stoppable` receives it as
`CallCancelled`. Two identical calls running at once in a Claude Code host share one
association, and the second is refused with `authority-denied`; it can be retried
once the first ends.

Envelope validation errors in `discover`, `describe` and `execute`
(malformed envelope, unknown feature, `arguments` failing the feature's
schema) use the same structure, with `action` set to the envelope's `action`
and code `invalid-input`. Before 388 they returned `{"error": "<text>"}`
without a code; the change is a fix under 7.

### 1.3 Python names

Public: `agent_swarm.__version__` and the names in `agent_swarm.__all__`:

- the tool: `TOOL_NAME`, `INPUT_SCHEMA`, `ACTION_FIELDS`, `tool_descriptor`,
  `validate_request`, `bind`, `unavailable`, `AgentsError`, `AgentsResult`,
  `Caller`, `Binding`, `Backend`, `Outcome`, `SessionArchive`;
- the backend: `AgentControl`, `RuntimeDriver`, `Run`, `ExecutionEvents`,
  `ACTIVE`, `STANDBY`. For a host holding notices (section 4, *Backend*):
  `AgentControl(hold_notices=...)` and its `held_notices`, `notice_open`,
  `settle_notice`, `settle_shown` and `close_notices`;
- configuration: `CONFIG_DEFAULTS`, `default_config`, `explicit_choices`,
  `read_config`, `write_config`, `read_connections` (section 3), and
  `discover_models(connection)`. `discover_models` takes one `config.yml`
  connection mapping (as `read_connections` returns it, or `{"runtime":
  ...}` for the native default login) and returns `{"runtime", "status":
  "available"|"unknown", "models": [{"id", "alias", "provider",
  "supported_efforts"}], "message"}`; DSH may add `provider_status`.
  `supported_efforts` is a list or `null` when the Runtime does not enumerate
  them. A connection with `models` returns those without querying the
  Runtime. It never runs an inference turn and never returns credentials.
  A DSH query drops `DEEPSEEK_BASE_URL` and `DEEPSEEK_SEARCH_BASE_URL` and takes
  `base_url` and `api_key_env` from the connection, as a child does; DSH asks an
  endpoint for its list only at the official origin, so a custom `base_url`
  lists DSH's built-in models. A Pi query reads the home (the connection's, else
  `PI_CODING_AGENT_DIR`, else Pi's default) from a private directory, so the
  home gains no file and its configured packages are not installed;
- the normalized Session archive (section 1.5): `read_session(path)` returns
  `{"header", "events"}` in version 5 form for version 4 and 5 files, and
  `validate_extra_fields(value)` checks an `extra_fields` container (section 5).
  `SessionArchive` takes the keyword `event_fields` (section 5).

Parts for building a host or a consumer on agents (since 0.2.2), also in
`agent_swarm.__all__`. Each one's docstring states its arguments and results:

- stoppable calls, for a host serving tool calls concurrently: `pause` and
  `run_stoppable` wait, `stop_requested` asks, `on_discard` registers cleanup
  and `CallCancelled` is raised when the caller cancels or goes away;
- the owner connection, the authenticated local file transport of 1.1:
  `worker_connection` serves it, `connection_operation` exchanges one document
  over it, `record_lock_owner` proves a lock's owning process,
  `client_native_context` reads the caller's native Session facts and
  `verify_native_context` compares them with what the host expects;
- the progressive envelope of 1.2: `ENVELOPE_SCHEMA`, `validate_envelope`,
  `handle_request(request, execute)`, and `validate_schema(value, schema, path)`
  for the JSON Schema vocabulary agents uses;
- MCP server parts, the framing of `agents-mcp`: `ConcurrentServer`,
  `ClientGone`, `mcp_serve`, `mcp_respond`, `mcp_result_response`,
  `mcp_error_response`, `mcp_tool_documents`;
- notices (section 4): `END_EVENTS`, `needs_parent`, `notice_id`;
- processes and locks: `process_ancestors`, `process_executable`,
  `process_arguments`, and `exclusive_lock(path)`, the lock agents takes on its
  own record files;
- `DECISION_METHOD`, the request method of `ask_parent` (section 4), and
  `within_workspace`, the check on `create`'s `workspace` (section 2);
- `native_session_files(root)`, the native Session files recorded under a data
  root (1.5);
- Runtime executions: `RuntimeAdapterError`, the protocols `RuntimeContext` and
  `RuntimeTurn`, `RuntimeExecutionResult`, `SessionStarted`,
  `credential_environment`.

Host shutdown (section 4, since 0.2.4), also in `agent_swarm.__all__`:
`stop_owned(control)` interrupts what this process runs on one 10-second deadline
and returns the Agents it still owns; `exit_if_owned_unconfirmed(agents)` writes
their `stop-unconfirmed` line and ends the process, and returns when the list is
empty.

Parts for one Runtime or for the Session archive live in these packages, each
with its own `__all__`:

| Package | Names |
| --- | --- |
| `agent_swarm.claude` | `ClaudeDriver`, `ClaudeExecution`, `collect_hook_event`, `hook_source`, `NativeCalls`, `REFUSAL_FILE`, `claim_channel`, `context_endpoint`, `ended_by_claude`, `log_replaced_channel`, `require_free_channel`, `serve_refusal`, `claude_host_plugin` |
| `agent_swarm.codex` | `CodexDriver`, `CodexManagedExecution`, `CodexAppServer`, `CodexExecution`, `CodexSession`, `CodexServerRequest`, `CodexRPCError`, `CodexAdapterError`, `CodexRuntimeContext`, `restore_codex_context`, `validate_codex_launch_request`, `reject_legacy_sandbox_config`, `codex_api_key_env`, `codex_connection_environment`, `find_native_session`, `project_access`, `validate_connection` |
| `agent_swarm.pi` | `PiDriver`, `PiExecution`, `current_connection`, `session_record`, `session_source`, `verify_main`, `pi_destination` |
| `agent_swarm.dsh` | `DshDriver`, `DshService`, `DshError`, `DshExecution`, `bind_run`, `session_context`, `dsh_version_refusal` |
| `agent_swarm.sessions` | `SessionArchive` (the JSONL archive; `agent_swarm.SessionArchive` is the interface a backend expects), `ConfiguredSessionArchive`, `JsonlSessionStore`, `archive_path`, `SESSION_FORMAT_VERSION`, `INITIAL_COLLECTION_TYPE`, `append_stream_record`, `native_record`, `retain_native`, `snapshot_event`, `upgrade_event`, `upgrade_header`, `validate_header`, `validate_session`, `CodexJsonlArchive`, `CodexHistoryArchive`, `NativeInputError`, `rollout_record`, `codex_attachments`, `DshArchive`, `DshLiveFrames`, `attachment_refs`, `attempt_usage`, `collect_jsonl`, `PiArchive`, `import_native`, `import_sqlite`, `verify_sqlite` |

`import agent_swarm` loads none of these Runtime packages; each name loads
its code on first use. Every other submodule (`agent_swarm.control`,
`agent_swarm.claude.host`, `agent_swarm.sessions.archive` and so on) is
internal, even where a public name is defined there: import a public name from
`agent_swarm` or from the package listed above. The test
`test_every_public_name_is_listed_in_the_contract` keeps this list complete.

**Extending an execution class.** A consumer may subclass a public execution
class and replace these methods, keeping their arguments and results. Other
underscore methods and attributes stay internal.

| Class | Method | What it supplies |
| --- | --- | --- |
| `ClaudeExecution` | `native_settings(address)` | the native settings and MCP documents of the launch |
| `ClaudeExecution` | `bind_connection(resources)` | the address of the owner connection, opened in the `ExitStack` |
| `ClaudeExecution` | `record_process(pid, outcome=None)` | receives process facts |
| `CodexManagedExecution` | `bind_connection(connections, request, cwd)` | `(address, environment variable, MCP module)`, or three `None` |
| `CodexManagedExecution` | `session_archive(session)` | the collector for a started Session, or `None` |
| `CodexManagedExecution` | `uses_review()`, `review_approval(request)` | whether the host judges approvals, and the native response for one |
| `CodexAppServer` | `call(method, params, *, wait_for_session=False)` | sends one native JSON-RPC request (call it, not replace it) |
| `PiExecution` | `prepare_launch(address)` | `(argv, environment)` of the launch |
| `PiExecution` | `provider_domain(source, provider)` | the model's network destination from the catalog in `source` |
| `PiExecution` | `bind_connection()`, `connection_environment(address)` | a context manager giving the address, and the variables that name it |
| `PiExecution` | `archive_collector(header, native)` | the collector for a started Session, or `None` |
| `PiExecution` | `record_process(pid, outcome=None)` | receives process facts |
| `DshExecution` | `prepare_launch()` | the launch environment, with the profile written |

A consumer may read and, before `run()`, set the attributes these classes
declare without an underscore (for example `request`, `directory`, `archive`,
`extra_fields`, `parent_notice`, `host_connection`, `independent`). A
`parent_notice(message, details)` set this way receives native requests, and a
driver binding an execution replaces it with its own.

**`AgentControl` methods.** Besides `operate` (`bind`'s entry) a host may call
`create`, `send`, `resume`, `interrupt`, `wait`, `requests`, `reply`,
`ask_parent`, `retire`, `select`, `require_connections`, `hierarchy`,
`reference_hint`, `interrupt_owned`, `owns_running`, `unconfirmed_ends`,
`registration(agent)` (`{"host", "parent", "settings"}` of an Agent the host
recorded, or `None` for a missing or unreadable record; it checks no caller),
`confirm_ended(agent, caller, *, by=None)` (`by` is the identity recorded as
confirming: `{"host", "agent", "session"}`), `import_agent(record)` and
`configure_stopped(agent, settings, caller)`.

**JavaScript files.** A package that places its own files beside the installed
`agent_swarm` may import these exports. Everything else in these files, and
every other `.mjs` file, is internal.

| File | Exports |
| --- | --- |
| `agent_swarm/pi/extension.mjs` | `loadHostSdk`, `registerAgents`, `registerAgentDisplay`, `sessionEnvironment`, `startAgentHost` |
| `agent_swarm/dsh/plugin.mjs` | `sessionEnvironment` |

### 1.4 Host plugins: the `agent_swarm.hosts` entry point

A package can let the `agents` CLI reach its host when the calling process has
no owner connection. It registers an entry point in the group
`agent_swarm.hosts`. The entry point is a callable taking the current working
directory (`pathlib.Path`) and returning either `None` (this host does not own
the directory) or a dispatch function. The dispatch function receives one
validated action request (`{"action": <feature>, **arguments}`) and returns an
`AgentsResult`. The first plugin that returns a dispatch function handles the
call. GraphTraj uses it like any other package.

**A tool beside `agents` in a Claude Code host (since 0.2.2).** A package whose
own Claude Code host serves another tool on its MCP server named `agents` (so
Claude Code calls it as `mcp__agents__<tool>`) declares that tool in two places.
There are no other extension points; GraphTraj declares its `tasks` tool this
way.

- `claude_host_plugin(directory, name, description, tools=())` returns the host
  plugin's files, keyed by absolute path, and writes nothing: `.claude-plugin/
  plugin.json` and `hooks/hooks.json` as JSON values and `hooks/host_context.mjs`
  as text. `directory` is the plugin's directory (`.claude/skills/<name>`), and
  `tools` the added tool names. A name that is not letters, digits, `_` or `-`,
  the name `agents`, or a repeated name raises `ValueError`.
- `NativeCalls(make_call, cwd, runner=None, tools=())` associates each native
  call with its Claude Session for the host. `make_call(session, cwd)` returns
  `call(tool, request)`, which returns an `AgentsResult`. The host passes
  `NativeCalls.context` as the receiver of its context channel and calls
  `NativeCalls.call(request, tool)` when the MCP server receives `tools/call`.
  Preparing a tool that was not declared fails with `invalid-input`.

A declared tool gets the behaviour of `agents`, except the display: each native
call has its own association, overlapping calls each end only their own, one
notice push loop is shared and rechecked after the last running call, queued
notices arrive with its results, and `/agents-context` lists it. No exchange
between Agents is rendered for it. A host that declares nothing, such as the
independent Claude Code host, associates and lists `agents` only.

### 1.5 Data root and normalized Session archive

The caller chooses the data root. Public within it: `config.yml` (section 3)
and, when archiving is on, one archive per Session at
`sessions/<sha256 of the Session ID>/session.jsonl`. Everything else under the
root is internal; `native_session_files(root)` returns the native Session files
its Agents recorded, for a host that grants exact read access to them. It
returns resolved paths of existing `.jsonl` files named by absolute path, and
skips a record it cannot read.

The archive is JSONL: a metadata line holding the header, then events in
native order.

- `header.version` is `5`: the DeepSeek Harness Session v4 layout (see
  `examples/sessions/README.md` in the repository) plus the product-neutral
  archive fields below and `extra_fields` (section 5). Version 5 replaced
  version 4 in agents 0.2.0.
- Header fields: `native` (`runtime`, `sessionId`, `locator`, plus native
  evidence), `missing` (`[{path, reason}]`), `previousSession` with its
  `boundary` (`{kind, offset}`, kind `rollout`, `compaction` or `rollback`),
  `source`.
- Event fields: `native` provenance (required on every archived event) and
  `missing`; Runtime evidence such as `attachments`, `usage`, `usageSource`,
  `contextReplay`, `receivedAtMs`, `lastReceivedAtMs`, `collectionBoundary`.
- Archive event types `native`, `history`, `score`, `logprobs`, `derived`;
  `collection-pending` (drafts only, never canonical history); content type
  `encrypted`; stream record type `text-run`.

Version 4 files stay readable. Every reader (`read_session`, the store,
Session lookup) maps them on read; agents writes only version 5. An archive
reopened from a version 4 file is rewritten whole, atomically, as version 5 on
its next change, so one file never mixes versions. Version 4 to 5:

| Version 4 | Version 5 |
| --- | --- |
| `header.version: 4` | `header.version: 5` |
| header `graphtraj.version`, `projectId`, `agentId`, `taskIds` | `extra_fields.graphtraj.version`, `.projectId`, `.agentId`, `.taskIds` |
| header `graphtraj.native`, `.missing`, `.previousSession`, `.boundary`, `.source` | header `native`, `missing`, `previousSession`, `boundary`, `source` |
| event `graphtraj.native`, `.missing` | event `native`, `missing` |
| event `graphtraj.attachments`, `.usage`, `.usageSource`, `.contextReplay`, `.receivedAtMs`, `.lastReceivedAtMs`, `.collectionBoundary` | the same names at the event's top level |
| event `graphtraj.version` (always `1`) | dropped |
| types `graphtraj/native`, `graphtraj/history`, `graphtraj/score`, `graphtraj/logprobs`, `graphtraj/derived`, `graphtraj/collection-pending` | `native`, `history`, `score`, `logprobs`, `derived`, `collection-pending` |
| content `graphtraj/encrypted`, stream `graphtraj/text-run` | `encrypted`, `text-run` |

Native records (`native.record`, `data.record`) are copied unchanged. A
version 4 value whose `graphtraj` key would overwrite an existing top-level
field is refused, not merged.

Independent hosts write archives when `save_normalized_sessions` is on.

### 1.6 Pi host: the agents Pi extension

A Pi Session becomes an agents host (the parent of its children) by loading
the extension `agent_swarm/pi/extension.mjs` and starting with
`--agents-config <file>`.

**Distribution.** The installed directory `agent_swarm/pi/` is a Pi package:
its `package.json` declares `"pi": {"extensions": ["./extension.mjs"]}` and
repeats `__version__` (tested like the DSH manifest). Install it with Pi's
own package command, from the agents installation Pi should use:

```sh
PI_PACKAGE="$(<python> -c 'import agent_swarm.pi, pathlib; print(pathlib.Path(agent_swarm.pi.__file__).parent)')"
pi install "$PI_PACKAGE"          # personal; add -l for this project only
AGENT_SWARM_PYTHON=<python> pi --agents-config /abs/pi-host.json
```

`pi -e "$PI_PACKAGE/extension.mjs" --agents-config ...` loads it for one
invocation without installing. `AGENT_SWARM_PYTHON` names the Python that has
`agent-swarm` installed; without it the Session start fails. Pi child
executions load the same file themselves, so a Pi child of any host needs no
installation.

**Configuration file** (JSON). Exactly these keys; any other key fails the
start, including the pre-382 `adapter_request` form (that form was internal,
see 7):

| Key | Required | Content |
| --- | --- | --- |
| `root` | yes | absolute agents data root (its `config.yml` is section 3) |
| `pi` | no | overrides of the Pi child request, below |
| `claude` | no | Claude driver settings, the keys of the Claude host's `settings` |
| `codex` | no | Codex `Run.settings`, the document `agent_swarm.codex.host --settings` takes |
| `dsh` | no | DSH driver settings (`model` is required by DSH) |

**Pi child defaults.** The host builds the Pi child request from its
verified native parent; `pi` may set any of these fields except
`worktree_path`:

| Field | Default |
| --- | --- |
| `executable` | the verified Pi entry of the parent |
| `provider`, `model` | the parent's current provider and model, as a default only; `create`'s `model`/`preset` choose another (section 2) |
| `worktree_path` | the host's cwd (fixed) |
| `agent_dir` | `PI_CODING_AGENT_DIR`, else `~/.pi/agent` |
| `instructions` | empty |
| `sandbox_python` | the host's Python (it must have `agent_sandbox`; set this to another Python otherwise) |
| `sandbox_path` | the host's `PATH` (it must reach `srt` and `node`) |
| `worktree_access` | `read`; `write` also resolves `git_common_directory` with Git unless given |
| `read_paths`, `write_paths`, `deny_read`, `deny_write` | none (absolute path lists) |
| `provider_domain` | the selected model's host from Pi's catalog in `agent_dir` (`agent_swarm.pi.pi_destination`); refused with `ROLE_CONFIG_UNSUPPORTED` without a plain http(s) destination |
| `allowed_domains`, `base_url`, `provider_api`, `api_key_env`, `reasoning_effort`, `native_directory`, `allow_mach_lookup`, `allow_mach_register`, `allow_local_binding`, `allow_unix_sockets` | none |

Besides these, the Pi owner always reads the worktree, its native Session
directory, the running Python and installed packages and the linked native
Home files; writes only its native directory, the connection socket and (for
`write`) the worktree and Git common directory; denies reading `agent_dir` and
the agents data root, and writing `agent_dir`, the Python prefix, the
packages and `<git_common_directory>/config` and `hooks`. The only domains are
`allowed_domains` plus the `base_url` host or `provider_domain`. A field of the
wrong type fails with `ROLE_CONFIG_INVALID` naming the field. An `api_key_env`
variable stays in the child's environment, where same-account processes and the
child's own tools can read it; Pi finds it through a private `auth.json` holding
only its name, so the value is on no command line and in no file. Pi's command
reaches `srt` as one shell-quoted word, because `srt` parses it with an inner
shell. Claude children default to
`worktree_access: read` and DSH children to `sandbox: read-only` unless
their section says otherwise. Without `codex`, a Codex `create` fails with
`invalid-config`.

**Start.** The host verifies that its parent process is the native Pi that
loaded the extension and binds that Pi Session as root caller. It then
calls `AgentControl.require_connections()` (section 2), so a `config.yml`
connection this machine cannot run stops the start rather than a later
turn; `create` checks the selected connection again. A refused start prints
one line `{"error": {"code", "message"}}` on stderr and exits `1`; Pi shows it
as the extension's error and the Session has no `agents` tool.

**Routing.** The host registers the `pi`, `claude`, `codex` and `dsh`
drivers in one `AgentControl` with `request_notices=True` and
`hold_notices=True`; `create`'s `runtime` selects one, and
`model`, `preset` and `reasoning_effort` are resolved per child (section 2).
The model reaches the Pi Session through the MCP server `agents`.

**Notices and shutdown** are section 4.

### 1.7 DSH host: the agents DSH plugin

A DSH main Session becomes an agents host (the parent of its children) when
its DSH loads the agents DSH plugin and the DSH process has
`AGENT_SWARM_DSH_CONFIG` naming a host configuration file.

**Distribution.** The installed directory `agent_swarm/dsh/` is a DSH plugin
bundle named `agents-dsh`: its `package.json` declares `"dsh": {"bundle":
{"patch": "./dsh.patch.yml"}}`, and that patch inserts the row `agents-host`
(module `agents-dsh`, that is `plugin.mjs`) with no settings. Install it with
DSH's own plugin command (it runs pnpm in the profile directory), from the
agents installation DSH should use:

```sh
DSH_PACKAGE="$(<python> -c 'import agent_swarm.dsh, pathlib; print(pathlib.Path(agent_swarm.dsh.__file__).parent)')"
dsh plugin --profile headless add "$DSH_PACKAGE"     # once per profile
AGENT_SWARM_PYTHON=<python> AGENT_SWARM_DSH_CONFIG=/abs/dsh-host.json \
  env -u DEEPSEEK_BASE_URL dsh --profile headless "<task>"
```

The `env -u` concerns only this main Session's own endpoint, which DSH takes
from that variable when its profile names none. Its DSH children ignore the
variable (section 2).

Any profile works the same way (`web`, `tui`, `acp`, `sdk`). Without
installing, a patch file with the row `{id: agents-host, name:
<DSH_PACKAGE>/plugin.mjs}` under `insert`, passed with `dsh --profile <name>
--patch <file>`, loads it for one invocation. `AGENT_SWARM_PYTHON` names the
Python that has `agent-swarm` installed. The row does nothing without
`AGENT_SWARM_DSH_CONFIG`, and nothing inside a DSH that is itself an agents
child (`AGENT_SWARM_CONNECTION` or `DSH_AGENT_PACKAGE` set). DSH child
executions keep loading the same `plugin.mjs` with their own `mcpCommand`
row; that path is unchanged. The plugin finds DSH's packages from the real
path of the running `dsh` entry, so no `GRAPHTRAJ_*` variable is needed;
`GRAPHTRAJ_DSH_PACKAGE` and `GRAPHTRAJ_CLI_CONNECTION` are still read when
set (renamed in 394). Verified against the source of DSH `0.2.2-alpha.2`.

**Configuration file** (JSON). Exactly these keys; any other key fails the
start:

| Key | Required | Content |
| --- | --- | --- |
| `root` | yes | absolute agents data root (its `config.yml` is section 3) |
| `dsh` | no | DSH driver settings; `sandbox` defaults to `read-only` and `model` to the parent Session's current model |
| `claude` | no | Claude driver settings, the keys of the Claude host's `settings`; `worktree_access` defaults to `read` |
| `codex` | no | Codex `Run.settings`, the document `agent_swarm.codex.host --settings` takes; without it a Codex `create` fails with `invalid-config` |
| `pi` | no | the whole Pi child request (`worktree_path` is the host's cwd); without it the host has no Pi driver and a Pi `create` fails with `unsupported-runtime` |

**Start.** The plugin starts one host, `python -I -m agent_swarm.dsh.host
--config <file>`, for each DSH main Session when DSH announces it
(`agent/created`, for new and resumed Sessions), in the Session's cwd. A
native DSH subagent (header `origin: subagent` or `delegationDepth` above 0)
gets no host and no `agents` tool. The host verifies that its parent process
is the DSH Node process that loaded the plugin (kernel executable and entry
file, inside the `@deepseek-ai/dsh` package) and binds the Session the plugin
supplied as root caller. Only that Session's MCP server `agents` may call it:
a client presenting another Session, source or cwd gets `authority-denied`.
The host then calls
`AgentControl.require_connections()` (section 2). A refused start prints one
line `{"error": {"code", "message"}}` on stderr and exits `1`; the plugin's
`agent/created` handler fails with that text and the Session has no
`agents` tool.

**Routing.** The host registers the `dsh`, `claude` and `codex` drivers (and
`pi` when configured) in one `AgentControl` with `request_notices=True` and
`hold_notices=True`;
`create`'s `runtime` selects one, and `model`, `preset`, `connection` and
`reasoning_effort` are resolved per child (section 2).

**Notices, delivery conditions and shutdown** are section 4.

## 2. Creating a child: Runtime, preset, model, reasoning effort

`create` takes `runtime` (required), `instruction` (required), optional
`name`, `configuration`, and since 0.1.1 optional `preset`, `model` and
`reasoning_effort` (non-empty strings).

**Resolution.** agents resolves the choice against its own `config.yml`
(section 3) before the driver prepares anything. A value is never silently
replaced by another one.

1. `runtime` must have a driver in this host, else `unsupported-runtime`.
   `runtime` is always given, also with a preset.
2. `preset` must be declared, else `invalid-preset`. Its Runtime (its own
   `runtime`, or its connection's) must equal `runtime`, else
   `invalid-preset`.
3. Precedence: the preset fills `model` and `reasoning_effort` only when the
   request omits them. An explicit value equal to the preset's is accepted;
   a different one is a contradiction and fails with `invalid-model` or
   `invalid-reasoning-effort`. Explicit arguments never override a preset.
4. Connection: the preset's connection; else the only connection declared
   for `runtime`; else none (the host's own settings and the Runtime's native
   default login, exactly as before 0.1.1). Several connections for the
   Runtime without a preset that selects one fail with
   `ambiguous-connection`. A selected connection whose Runtime is not
   installed or not logged in fails with `runtime-unavailable`, naming the
   Runtime and connection.
5. `model` (explicit or from the preset) must be the `id` of exactly one
   candidate from `discover_models`: the connection's declared `models`,
   else the native catalog (Pi and DSH catalogs filtered by the connection's
   `provider`; Claude and Codex list their own configured provider's
   models). Not a candidate, discovery `status: unknown`, or several
   providers offering the id fail with `invalid-model`. Without `model`, the
   host's or Runtime's default model applies and nothing is checked.
   Discovery runs synchronously inside `create`: a native catalog query may
   take up to about 30 seconds before `create` returns; declared `models`
   avoid it.
6. `reasoning_effort` must be in the chosen model's `supported_efforts` when
   that is a list, else `invalid-reasoning-effort`. When it is unknown
   (`null`, or no `model`), the driver checks it against the Runtime's own
   values and fails with the same code (Claude `low`, `medium`, `high`,
   `xhigh`, `max`; Codex `none`, `minimal`, `low`, `medium`, `high`,
   `xhigh`; Pi `off`, `minimal`, `low`, `medium`, `high`, `xhigh`; DSH `off`,
   `low`, `high`, `max`). A Runtime that rejects the value natively keeps its
   own code (section 1.2).

A request that selects nothing (no preset, model or effort, and no
connection declared for the Runtime) reaches the driver exactly as before.
`configuration` keeps its meaning and may be combined with the new arguments;
independent hosts still refuse it with `invalid-config`.

**Drivers.** The selection reaches the driver as
`prepare(runtime, caller, selection={"preset", "connection", "model",
"reasoning_effort", "provider", "settings", "review"})`, where `settings` is the
declared connection entry or `null`, and `review` is the entry of the reviewer
that connection names (section 3) or `null`. A selected connection replaces the
host's native home, endpoint and key variable together, so a host key never
reaches another endpoint. A driver whose `prepare` does not accept
`selection` makes such a create fail with `invalid-config`. The agents
drivers apply `model` and `reasoning_effort` for all four Runtimes; current
limits, each failing with `invalid-config`: the DSH driver runs the
`deepseek-official` provider only; the Pi driver takes no `base_url`;
declare such an endpoint as a provider in Pi's own `models.json` in the
connection's home. When a Pi selection changes the provider, model, home or
key, the driver reads the model's network destination from Pi's catalog in
the selected home and fails with `invalid-config` if Pi exposes no plain
http(s) destination; another provider or a selected connection drops the
host's `api_key_env`, `base_url` and `provider_api`. Claude has no native
provider setting, so a Claude connection's `provider` only names its models.

**Several Runtimes in one host.** A host registers one driver per Runtime in
`AgentControl(root, {runtime: driver, ...})`; `create` routes by `runtime`.
At start a host may call `AgentControl.require_connections()`, which raises
`unsupported-runtime` for a declared connection whose Runtime has no driver
and `runtime-unavailable` for one that is not installed or not logged in.
Login is checked by existence only: the connection's `api_key_env` variable
is set, or the native login file exists in its home (Claude
`.credentials.json` or the `.claude.json` account record, Codex and Pi
`auth.json`). DSH's own login files are not inspected; without
`api_key_env` its start reports a missing login. No credential is read,
copied or returned. The independent Claude Code host registers its Claude
driver and one driver per `runtimes` entry (1.1) and calls
`require_connections()` at start; a refusal answers every call with its
code (1.1). The independent Codex host does the same with its own
`runtimes` (1.1) and reports a refusal as its startup error. The Pi host
and the DSH host call it at start (1.6, 1.7).

**DSH children (383).** Any host that registers `agent_swarm.dsh.DshDriver(cwd,
settings)` starts DSH children without GraphTraj installed and without any
`GRAPHTRAJ_*` variable. `settings` holds `model` (the default model, required),
`sandbox` (`read-only` or `workspace-write`, required) and optionally
`executable` (else `dsh` on `PATH`), `reasoning_effort`, `api_key_env`,
`base_url`, `runtime_home` and `instructions`. A create's connection, `model`
and `reasoning_effort` replace them for that child only. The child's MCP
server is `<host python> -I -m agent_swarm.mcp`, loaded into DSH by the
packaged `agent_swarm/dsh/plugin.mjs`. DSH receives `DSH_AGENT_PACKAGE` (the
installed DSH `package.json`) and `AGENT_SWARM_CONNECTION`. `prepare` (which
the Claude Code and Codex hosts call at start) refuses:
- DSH not found: `RUNTIME_UNAVAILABLE`.
- An installed DSH older than 0.2.0-rc.2 in semver order, or a version that
  cannot be read: `RUNTIME_UNSUPPORTED`, message `DSH 0.2.0-rc.2 or later is
  required (installed <version or unknown>).`.
- A missing `model` or `sandbox`: `ROLE_CONFIG_INVALID`.
- An unset `api_key_env`: `RUNTIME_CREDENTIAL_MISSING`.

The child's endpoint comes only from `base_url` in the connection or settings,
else DSH's official root. `DEEPSEEK_BASE_URL` and `DEEPSEEK_SEARCH_BASE_URL` in
the parent's environment are removed from every DSH child's environment, GraphTraj's
DSH members included, so they no longer route a child and a key goes only where
the connection says. Anyone routing through them must declare `base_url` on the
connection or the DSH settings.

DSH's web search has its own key reference, `DEEPSEEK_API_KEY`, which has no agents
setting. When a connection declares a `base_url` at another origin than
`https://api.deepseek.com` and its key is that same variable, named or by default,
search follows the connection: its Messages requests go to `base_url` (with `/v1`
unless the path ends in it), and DSH's Search and Fetch API provider is disabled,
because its fixed official address is not in the connection. An endpoint that does
not serve native search then gives a search error naming the endpoint, rather than
official search. A connection with any other key variable, or with no `base_url` or
an official one, leaves search at DSH's official root with `DEEPSEEK_API_KEY`: to
keep official search beside a gateway, name the gateway's key in another variable.

A turn that ends other than `completed` fails the execution with
`RUNTIME_EXECUTION_FAILED`. When the native reason carries an error, the message
is `DSH turn ended with <kind>: <code>: <text>.` (for example `DSH turn ended
with error: HTTP_404: DeepSeek Messages request failed (404).`), else `DSH turn
ended with <kind>.`. The native part has launch credentials and URLs redacted
and is cut to 500 characters. Parents read it as `error.message` in `status`
and `wait`.

Continuing a DSH child (`send` to a standby child, `resume`) reopens the
same native Session. On DSH 0.2.0-rc.2 (and when the installed version cannot
be read) the driver calls `session/create` with the stored `sessionId`. Later
DSH mints a new Session there once the stored one has a turn
(0.2.2-alpha.2 `dsh-api-session-controller/lib/index.js:345-365`, contract
`typert.host.js:1993`), so the driver instead subscribes to the stored Session
(`session/follow`), which DSH resolves by resuming it (`index.js:160-213`). It
no longer passes `cwd` or an agent preset on that path; the resumed Session
keeps its own. Another Session in the snapshot, or `session/not-found`, fails
the execution with `RUNTIME_SESSION_NOT_RESUMABLE`.

This is a floor, not a pin: no newer DSH is refused for its version.
`dsh_version_refusal(package)` (since 0.2.2) applies the rule to a DSH
`package.json` path: it returns the refusal message above, or `None` when that
DSH can run. GraphTraj's own DSH members use it, so they follow the same rule.

**Review plugin (approval layer 3).** A connection with `review` (section 3)
runs under the review plugin. `create` refuses it with `invalid-config` when
the Runtime's driver has no adapter (`supports_review = True`; the Claude, Codex,
Pi and DSH drivers have one), so a child never silently runs unreviewed, then
runs the connectivity check (section 6). Both happen before any Agent record
exists; `send` and `resume` do not repeat them.

**Agent document.** Every Agent document carries `preset`, `connection`
(the connection's name), `model`, `reasoning_effort` and `review` (the
reviewer's name) as chosen at `create`; `null` means not chosen (the host's or
Runtime's default). Agents created before 0.1.1 show `null` for the first four,
and before 0.2.1 for `review`.

**Workspace (approval layer 1).** `create`'s optional `workspace` is an
existing absolute directory the parent assigns to the child. Rules:

- It must lie inside the caller's own workspace: the calling Agent's assigned
  `workspace`, else the host's cwd. Links are resolved first. Outside:
  `workspace-denied`; relative or missing: `invalid-input`.
- A child created by an Agent that has a workspace inherits it when
  `workspace` is omitted, so a grandchild is never wider than its parent.
- The driver receives it as `prepare(..., workspace=Path)`. A driver whose
  `prepare` does not take `workspace` makes such a create (including an
  inherited workspace) fail with `not-implemented`, never run wider.
- It replaces only the child's working directory. It adds no writable root,
  read grant, network, approval or permission-mode change.

What each Runtime then enforces:

| Runtime | Effect of `workspace` |
| --- | --- |
| Claude | cwd, and so the native sandbox's working directory and `blockReadsOutsideWorkingDirectories`; declared `read_paths` stay |
| Codex | cwd (`worktree_path`, Session `cwd`); the captured permission profile keeps its own filesystem and network grants, which may be wider than the workspace |
| Pi | cwd and the worktree read/write grants of the native sandbox; other grants stay |
| DSH | cwd and the sandbox policy's `workspaceRoot` |

It is not an OS sandbox by itself: a Runtime confines the child only as far
as its own sandbox follows the working directory, as listed above.

**Fallback.** When the Runtime answers with a different model than
requested (for example a safeguard fallback), the child's result names the
requested model, the observed model and the Runtime's reason, as 369 does
for Claude. The report belongs to the driver, so a Claude child reports it
the same way under any host that registers the Claude driver.

Codex (since 0.1.2): a `thread/start` or `thread/resume` response whose
`model` differs from the requested `model`, or a `model/rerouted`
notification for the child's turn, ends the execution `failed` with
`RUNTIME_REQUEST_FAILED`; a reroute interrupts the turn first. The message
is `<summary>: requested model <requested>, observed model <observed>;
Runtime reason: <reason, or "not provided in the native stream">.` For a
reroute the reason is the notification's `reason`, and the requested model
is its `fromModel` when none was requested. This holds under every host,
GraphTraj included.

## 3. Standalone configuration: `<data root>/config.yml`

agents reads only its own `config.yml` and native Runtime login state; it
never reads GraphTraj's `roles.yml` or any other product's configuration.
GraphTraj passes its roles to agents through `create`'s public arguments and
this file.

```yaml
save_normalized_sessions: false     # boolean, default false
backfill_history: false             # boolean, default false
connections:                        # optional
  work-claude:                      # name: any non-empty string
    runtime: claude                 # required: claude, codex, pi or dsh
    home: /abs/native/home          # optional native home (absolute; ~ expanded)
    provider: anthropic             # optional native provider
    base_url: https://host/v1       # optional, http(s) without credentials, query or fragment
    api_key_env: WORK_KEY           # optional: the NAME of an environment variable, never a key
    review: local-review            # optional: this connection's reviewer (section 6)
    models:                         # optional candidates; omitted: native discovery
      - claude-opus-5-5             # an id, or
      - id: claude-sonnet-5-5       # a mapping with id and optional alias,
        supported_efforts: [low, high]   # provider, supported_efforts
presets:                            # optional
  reviewer:                         # selected by create's preset
    connection: work-claude         # exactly one of connection or runtime
    model: claude-sonnet-5-5        # optional
    reasoning_effort: high          # optional
reviewers:                          # optional
  local-review:                     # a chat completions endpoint
    base_url: http://127.0.0.1:1234/v1   # required, http(s) without credentials, query or fragment
    model: tuned-reviewer           # required
    api_key_env: REVIEW_KEY         # optional: the NAME of an environment variable, never a key
    json_mode: false                # optional, default false: send response_format json_object
    timeout_seconds: 20             # optional, default 20: finite, above 0
  own-script:                       # or a local process
    command: [/abs/reviewer, --strict]   # required, exact argv
    timeout_seconds: 30             # optional, as above
```

`review` on a connection is how the user declares that its native approval is
missing or unusable. A connection without it keeps native approval exactly as
4.1 and no reviewer ever runs; agents does not guess or probe native
availability. A reviewer is never defaulted to the child's own provider, and
there is no preset field or inheritance for it.

With `save_normalized_sessions: true`, every execution of every Runtime
(Claude, Codex, Pi, DSH) in any host writes its normalized Session to
`<data root>/sessions/<sha256 of id>/session.jsonl`; no host refuses the
setting. Switching it to `false` stops saving for later executions and keeps
the archives already written. An execution that cannot archive fails with its
own cause. Header `extra_fields` come from `create`'s `extra_fields`
argument, not from this file.

- The two booleans keep their meaning and defaults. A value must be exactly
  `true` or `false`.
- Blank lines and comments are allowed. Reading is strict: an unknown or
  repeated field, a wrong type, a preset naming an undeclared connection, a
  preset with both or neither of `connection` and `runtime`, a connection
  naming an undeclared reviewer, a reviewer with both or neither form, or
  `api_key_env` over plain http to anything but this machine fails with
  `<file>:<line>: <field>: ...`; `create` reports it as `invalid-config`.
- `read_connections(root)` returns `{"connections": {name: entry},
  "presets": {name: entry}}`, plus `"reviewers": {name: entry}` when the file
  declares any; each entry is the file's fields plus `name`.
- `write_config` and `default_config` replace only the boolean lines and keep
  every other line, including connections, presets and comments.
- A file that holds only boolean lines is read exactly as before 0.1.1.

## 4. Parent-child traffic

There are exactly three kinds of traffic between a parent and a child, and
only these notify the parent:

| Kind | Direction | Today |
| --- | --- | --- |
| Message | both ways | parent → child: `create` `instruction`, `send`, `resume`. Child → parent: the child's final answer when its round ends and it has no running members of its own |
| Permission request (decision or resources) | child → parent, waits for a reply | native approval requests, and the child's own `ask_parent`: the parent is notified once per request (event `request`, see below), `wait` returns early, the Agent document shows `pending_requests`, the parent reads them with `requests` and answers once with `reply` |
| System exception | system → parent | an execution ending `failed` or `interrupted`, with `last_result.error` |

Delivery rules:

- Each event reaches the parent once. `last_result.notification` records it:
  `pending`, `queueing`, `queued`, `held`, `delivered`, `unconfirmed` or
  `unavailable`. Once the body was delivered (or may have been), `status` and
  `wait` show `last_message: null` instead of repeating it; a queued or held
  body stays readable there.
- A failed or interrupted end notifies immediately, whatever the child's
  members are doing.
- A completed round of a child that still has running members is recorded,
  not pushed. All rounds stay readable through `status`.
- A notice its parent cannot receive now is recorded `held`, stays readable
  through `status` and `wait`, and is delivered once when that parent next
  runs, including across host processes. A body the parent has read through
  `wait` or `status` is settled `delivered` and is not pushed again. Records
  written before holding (`queued`, `unavailable`) are never replayed. A crash
  between delivery and settling delivers that notice once more, never loses it.
  A child Agent that is itself a parent is continued with its child's reply, on a
  driver that binds a receiver (see *Gaps* for Pi).
  Under GraphTraj this is the 367, 372 and 375 behaviour.
- There is no separate "ask for attention" call and no parent watch switch.
  `ask_parent` is the permission-request kind above, not an attention call:
  it must name `kind` and a `question`, and it waits for an answer.
- A permission request (native or `ask_parent`) notifies the parent once per
  request when the host enables it (since 0.1.2; see *Backend* below). A
  repeated report of the same request notifies nobody again. The notice names
  the request's method and tool only, never its input, and asks for `requests`
  and `reply`; it never answers the request.

**Decision and resource requests.** A child asks its direct parent to decide
or to grant resources (more time, wider scope) with `ask_parent`. agents
retains it on the child's running execution as a request document `{"session",
"execution_id", "request_id": null, "request_token", "method":
"agents/decision", "params": {"kind", "question"}}`. It is distinct from a
native safety approval: no Runtime sees it, and its reply is `{"answer":
"<text>"}` (anything else is `invalid-input`), recorded with `reply_status:
answered`. The child's call waits at most `timeout_seconds`:

- answered: `answer` is the parent's text, `timed_out: false`;
- no answer in time: `answer: null`, `timed_out: true`. This is an explicit
  "no answer", never an approval; the request stays pending, and asking the
  same `kind` and `question` again in the same execution waits for the same
  request (or returns its answer);
- the execution ends first: `stale-execution`; the request is withdrawn.

The answer is information for the child. agents itself grants no time or
scope; the parent does that with its own means (for example `send`, or a new
`create` with a narrower `workspace` inside its own).

What the parent sees today:

- **Claude Code host:** each notice is `{"id": "<execution>:<event>",
  "event": {"alias", "event", "message", "execution"}}`; a `request` notice's
  id is `<execution>:request:<request>`. It enables `request_notices`, for
  children of every Runtime it runs. The host plugin
  pushes it into the Main Session as `[GraphTraj notice from <alias> ·
  <event>]` followed by the message; otherwise it is attached as
  `main_notices` to the next `agents` result. An end already shown by `wait`
  or `status` is not pushed again. It enables `hold_notices`: a notice stays
  held until the plugin acknowledges its submission (`{"operation":
  "acknowledge", "session", "position": 0, "ids"}`) or a result carries it. A
  result the caller cancelled, or sent to a client already gone, gives it back.
  A child that ends before its own `create`, `send` or `resume` returns can have
  its notice on that very result; the `wait` that follows then shows
  `last_message: null`. The host interrupts its children when
  Claude Code ends the Session, and those ends are held. The first time a
  Session binds in a host process, whether by a call or the plugin's claim,
  what was held for it is queued, so `claude --resume` of the same Session
  receives it; another Session does not. Adopting this version means running
  `agent_swarm.claude.host configuration --write` again: an earlier copy of the
  plugin never acknowledges, so its pushed notices repeat once per host process.
- **Codex host:** one host event per notice, `{"source": "agents", "alias",
  "event", "message"}`, sent to the parent Session while its turn runs. It
  enables `request_notices`, for children of every Runtime it runs (Codex,
  Claude, DSH, Pi). The `--output` document lists the notices in `deliveries` (`id`,
  `agent`, `event`, `parent_session`, `body`, `accepted`). It enables
  `hold_notices`: a notice that arrives before the parent's turn starts or after
  it ended, or whose event could not be written, is held. A written event
  whose acknowledgement was lost stays `unconfirmed`. A closing host interrupts
  the children it runs and waits up to 10 seconds for their ends, which are
  held (*Claude Code and Codex host shutdown* below). `--resume` sends what was held for that Session once, into the resumed
  turn; a notice not yet sent when that turn ends waits for the next `--resume`.
- **Pi host:** it enables `request_notices` and `hold_notices`, for children
  of every Runtime it runs. Each notice is injected into the Pi Session with
  Pi's `pi.sendMessage` as a displayed custom message (`customType`
  `graphtraj:agent-communication`, content `[agents notice from <alias> ·
  <event>]` and the message, `details.fact` `notice:<id>`, the id as for
  Claude above), with `triggerTurn: true, deliverAs: "followUp"`: an idle
  Session starts a turn with it, a busy one receives it after the current
  turn's work. Pi writes the message to the Session only when a turn takes it
  (`dist/core/agent-session.js:760`), so the notice is `delivered` once the
  extension finds its entry there after Pi's `message_end`; until then it stays
  `held`. It is `unconfirmed` when no acknowledgement of any kind comes within
  10 seconds (it may have been shown, so it is never repeated), and `held` when
  it could not be written or injected. While a notice is on its way
  (`notification: queueing`), `wait` and `status` also show `last_message:
  null`, so a `wait` that ends with the child, or a `status` during the turn,
  does not repeat the body the notice carries. A permission request does not
  wait for that turn: its child and `ask_parent` go on at once. Before
  injecting, the extension looks for the same `details.fact` among the Session's
  `custom_message` entries; when it is there (a crash after Pi wrote it and
  before the acknowledgement), it acknowledges without injecting again. A notice
  Pi took but never wrote, because the Session stopped or its turn failed to
  start, is delivered by the next host process for this Session; until then the
  host hides its body. A notice to a Pi parent that is mid-turn is taken at the
  end of that turn, so a permission-request notice can arrive after the parent
  has already answered the request through `wait`, `requests` and `reply`; it
  then costs one more model turn and is still delivered once (observed once on
  the real host, 403). Sources are `@earendil-works/pi-coding-agent` `1.4.0`.
- **Pi Session shutdown** (Pi's `session_shutdown`: quit, reload, new, resume
  or fork):
  the extension stops injecting and closes the host's pipe. The host stops
  pushing, then interrupts every running child, descendants first, and
  waits up to 10 seconds in total for all of them, whether or not they have
  an unanswered request. The ends this causes, and any notice not
  yet acknowledged, are `held`, readable through `status`. Agents, Sessions
  and records are kept. An Agent still active at that deadline, or every
  Agent when no `status` could be read, is not reported as stopped: the host
  writes one `{"error": {"code": "stop-unconfirmed", "message"}}` line naming
  it to stderr and exits non-zero, and the extension's `session_shutdown`
  handler rejects with that text. In the next host's `status` that Agent is `active` with `stopping`
  and the diagnostic `owner-exited; the Runtime process is still running` while
  its Runtime lives; once that is gone, it is in standby with `last_result`
  `outcome: failed`, `terminal_confirmed: false` and error `owner-exited`, and
  that end is held.
- **Claude Code and Codex host shutdown** (Claude Code ends the Session, or the
  Codex parent's run ends or fails): the host interrupts every execution this
  process runs, whoever created it, and tries again until they end, up to 10
  seconds in total. A call blocked in a driver or on a record lock can add up to
  1 second. Executions other processes own are not touched. An interrupt that
  fails or blocks does not stop the others (`interrupt_owned` keeps that Agent
  in its list and records no stop for it). The ends this causes are held under
  `hold_notices`. Each Agent still owned at that deadline is named in one
  `{"error": {"code": "stop-unconfirmed", "message"}}` line, and the process
  exits non-zero even if a stuck thread would keep it alive. The next host's
  `status` for that Session shows such an Agent as in *Pi Session shutdown*
  above: `active` while its Runtime lives, then standby with `outcome: failed`,
  `terminal_confirmed: false` and error `owner-exited`. A confirmed shutdown
  writes no line and exits as before. Where the line lands:
  - **Claude Code hosts** (`agent_swarm.claude.host` and GraphTraj's): in
    `host.log`, because the host's stderr is that file once it serves MCP.
    `agents host recorded its children stopped.` is written only when every stop
    was confirmed. The Claude Session does not see the line: the host stops its
    children after Claude Code has closed MCP or is ending the Session, so no
    tool result or notification can reach it, and a Claude Code host has no other
    path into the Session. Read the state through `status` on the next host.
  - **Codex host:** on the stderr of `agent_swarm.codex.host`, and in
    `stop_unconfirmed`, a list of Agents that is empty for a confirmed shutdown,
    in the `--output` document and the result of `CodexHost.run`. The parent
    Session does not see it: its run has ended, so no host event can reach it. A
    run that raises writes no `--output` document, as before, so only the line
    names them. `CodexHost.run` called as a library returns its result and never
    ends the caller's process; only `main` does.
- **Pi Session resumed** with the same configuration: a new host process binds
  the same Session and delivers each held notice once, in the order the
  children ended. It starts when the Session's first turn starts
  (`agent_start`), or two seconds after the start in a Session with a UI where
  no turn has started, because a held notice starts a turn in an idle Session
  and Pi refuses a prompt while one runs (`dist/core/agent-session.js:1667`;
  print mode passes no queueing option, `dist/modes/print-mode.js:105`). A
  notice refused then stays held for the next host process. A Session with no
  UI and no turn delivers nothing and keeps them held. Held notices belong to
  their Session: a new or forked Pi Session does not receive them.
- **DSH host** (1.7): it enables `request_notices` and `hold_notices`, for
  children of every Runtime it runs. Each notice `{"id", "agent", "session", "event",
  "message", "execution"}` (the id as for Claude above) goes to the plugin,
  which hands it to the existing `agentMessages.receive` relay
  (`dsh/communication.mjs`): one native `agent-message` relay message from
  the child's Agent and Session, text `[agents notice from <agent> ·
  <event>]` followed by the message, communication id `agents-notice:<id>`,
  placed in the Session's next-step inbox with a wake. The relay admits one
  id once per Session, including across processes, by looking for it in the
  Session's persisted events and inbox (`communication.mjs` `deliver`); that is
  the guard against showing a replayed notice twice. Admitted is
  `delivered`; refused (for example the Session is no longer active in that
  DSH) is `held`; no acknowledgement within 10 seconds is `unconfirmed` (it may
  have been admitted, so it is never repeated). A DSH parent Agent's request
  notice has the relay id `<execution>:request:<request>`, and its end keeps
  `<execution>`, so one execution's notices do not collide.

  When a DSH parent receives a notice depends on its state. Sources are the
  installed DSH `0.2.2-alpha.2` packages under
  `node_modules/@deepseek-ai/`:

  | Parent state | What happens | DSH source |
  | --- | --- | --- |
  | Turn running | The message enters the next-step inbox; the running turn takes it at its next step and does not end while the next-step inbox has input | `dsh-agent-loop/lib/index.js:564-569` (`send`), `:103-105` (`claim`), `:790-798` |
  | Idle, host alive (a long-lived profile such as `web`, `tui`, `acp` or `sdk`, or `headless` before its runner leaves its loop) | The wake starts a new turn with the notice at once | `dsh-agent-loop/lib/index.js:564-569`, `:618-623` |
  | Idle during maintenance (for example compaction) or right after a cancel | The wake is latched and the turn starts when that activity ends | `dsh-agent-loop/lib/index.js:565-566`, `:619-621` |
  | `headless`, after the parent is idle with no native DSH subagents | The runner flushes and exits. agents children are not native subagents, so it does not wait for them; the host then stops with DSH (next row) | `dsh-headless/lib/index.js:369-373`, `:377-383` |
  | Host or DSH process stopped (Session disposed, DSH exited) | No host runs. At the stop the plugin closes the host pipe; the host stops pushing, interrupts its active children (descendants first), waits up to 10 seconds in total for all of them and holds their ends, readable through `status`. An Agent it cannot confirm stopped is reported as for the Pi host above (`stop-unconfirmed` on stderr, non-zero exit, the same `status` in the next host); the plugin writes that text to the DSH logger | `dsh/plugin.mjs`, `agent_swarm/shutdown.py` |
  | On resume (`dsh --profile headless --session-id <id> "<task>"`, or reopening the Session in a long-lived profile) | DSH registers and announces the Session again and a new host binds the same Session. The plugin tells the host to begin when the Session's first turn begins, or two seconds after its `agents` tool attaches in a Session that starts no turn by itself: a relay message wakes an idle Session, and the `headless` runner applies its permission settings and hands over its task only after the announcement. The host then delivers each held notice once through the relay. A refused notice is tried again, at most six passes five seconds apart in that host's lifetime, and then stays held for a later host. Earlier children are listed by `status` and continue with `resume` | `dsh-agent/lib/index.js:655`, `:710`; `dsh-headless/lib/index.js:263`, `:344`, `:361` |

  Cases without immediate delivery: (1) a running parent receives a notice
  only at its next step, after the current model response or tool call;
  (2) during maintenance or right after a cancel, only when that activity
  ends; (3) a `headless` parent whose task has ended receives a later notice
  only when resumed: its children are interrupted when DSH exits and their ends
  are held, so a later `dsh --profile headless --session-id <id> "<task>"`
  delivers them in that task's turn, and a parent that needs a child's answer
  within its task calls `wait` for it before ending that task;
  (4) while DSH or the Session is stopped, nothing is delivered, and notices
  are held; (5) on resume, each held notice is delivered once, unless the parent
  read it through `status` or `wait` first.

  A notice the relay admitted and no turn has taken yet survives a stop: DSH
  appends each inbox insertion to the Session as an event
  (`dsh-agent-loop/lib/index.js:198`) and restores the inbox from those events on
  resume (`:26-60`), so the next turn takes it. One case stays open, because of
  how the `headless` runner leaves: a notice admitted after the runner's last
  Session flush (`dsh-headless/lib/index.js:377`) and before its exit (`:383`)
  may not reach the Session file, and it is already `delivered`. Upstream DSH is
  not changed for any of these.
- A grandchild's notices go to its own parent, whatever the grandchild's
  Runtime. A running Claude, Codex or Pi parent Agent takes them into its turn as
  `[agents · <child> → <parent>]` followed by the message; a standby one is
  continued with a child's reply, in its retained Session. A standby parent is
  not started for a `request`, or for an end without a body: under
  `hold_notices` those are held and taken into its next run (`resume`, `send`,
  or being continued by another child's reply). So is any notice while its
  host process has no receiver for that parent, after a restart for example;
  the host's root receiver never sees it. An end that reaches a parent whose
  turn has just stopped accepting input continues it once when that turn ends,
  unless the parent ended `failed` or `interrupted`, or was retired. A parent
  reading its child's end through its own `wait` or `status` settles it; an
  ancestor reading a grandchild does not, since `delivered` would hide the body
  from that child's parent.
- A Pi parent Agent gets a notice through RPC `prompt` with
  `streamingBehavior: "steer"`. Pi acknowledges when it queues the text, and
  takes it before its next model call (`message_start` of the user message); the
  record is `delivered` from the acknowledgement. Its own timing:
  - Held notices are flushed when `driver.start` returns, which is before Pi has
    accepted the turn's first prompt. The receiver waits for that, up to 30
    seconds (the RPC limit), so a `resume` with held notices can take that long
    and they reach the turn it starts. When the wait expires the notice stays
    `held` for that turn's end or the next run.
  - A stop or a dying process drops what Pi has queued. A notice Pi acknowledged
    and never took returns to `held` when the parent ends `interrupted` or
    `failed`, its body readable again, and the next run takes it. The same holds
    for a continued turn's prompt. A notice Pi took stays `delivered`. A
    `completed` turn settled with Pi's queue empty, so nothing returns.
  - A refused `prompt`, a stopping or ended execution wrote nothing: the notice
    stays `held`, or continues a standby parent as above. An acknowledgement not
    received in 30 seconds may have been taken: `unconfirmed`, never repeated.
  - Remaining windows. A killed host process cannot return what Pi dropped: it
    stays `delivered`, its body hidden. A Pi extension whose `input` handler
    rewrites or handles the notice hides it from this check, so a stop returns it
    and it can arrive twice. A stop that ends the parent between its receiver
    returning and the core recording `delivered` keeps `delivered`.
- `event` is `completed`, `interrupted`, `failed` or `request`; `message` is
  the child's answer, else the error message, else the outcome. For
  `request` it is a short credential-free text naming the method and tool
  (`ask_parent`'s method is `agents/decision`; its question is not included),
  for example `Permission request claude/can_use_tool for Bash waits
  for your reply. Read it with requests and answer once with reply.`

**Backend.** `AgentControl(root, drivers, event_receiver=..., request_notices=
False)`. With `request_notices=True` (since 0.1.2), when a driver reports a
new native request through `ExecutionEvents.request`, or a child's
`ask_parent` adds a new request, the core calls the parent's receiver once: a parent Agent's native receiver, else the host's
`event_receiver` for a root. The notice is `{"parent", "agent", "session",
"execution", "body", "outcome": "request", "request"}` (`request` is the
request's token, else its native ID as JSON); a root's notice adds
`"creator"` and `"error": null`, as an end notice does. A receiver error is
ignored: the request stays readable through `status` and `requests`. The
default `False` keeps a host's notices to ends only, as before 0.1.2.
`request_notices="decisions"` (since 0.2.2) applies this to `ask_parent` only,
for a host that keeps its children's native requests to `wait` and `requests`.
GraphTraj's own host does this.

With `hold_notices=True` (since 0.2.1; the default `False` writes no new field or
value) a notice its parent cannot receive now is kept in the record:

- A receiver may return `"held"`. For a root's end, so do a receiver that
  returns `False` or raises, and a control without a receiver. An end a process
  died before reporting (`owner-exited`) is held too. A receiver that returns
  `"unconfirmed"`, or a parent Agent's receiver that raises, leaves it
  `unconfirmed`: not repeated.
- A request is `held` before its receiver is called, in the execution's
  `request_notices: {<request>: "held"|"delivered"|"unconfirmed"}`. The request
  document does not change.
- `held_notices(caller)` returns every undelivered notice addressed to `caller`,
  oldest first, in the shape a receiver gets: for a root caller those of the root
  Agents it created (the scope of `status`), for an Agent caller those of its
  direct children. It lists ends `held`, or left `queueing` or `pending` by a
  process that died, and `held` requests while their execution runs unanswered:
  a request whose execution ended is withdrawn, and its end covers it. Retired
  Agents are left out.
- `notice_open(notice)` says whether one notice still waits.
- `settle_notice(notice, delivery, reopen=False)` marks one notice `delivered`,
  `unconfirmed` or `held` and returns whether that changed anything. `delivered`
  and `unconfirmed` are final unless `reopen`, which is for a tool result that
  carried the notice and was discarded.
- `ExecutionEvents.return_notice(notice)` (since 0.2.2) is that `reopen` for a
  driver: a child's notice its Runtime acknowledged and then dropped is `held`
  again. It does nothing without `hold_notices`.
- `settle_shown(request, document)` settles `delivered` what one successful
  `wait` or `status` showed, in either request form and including the hierarchy
  form's `children`, and returns those notices. It settles only ends addressed
  to the root caller; the core does the same for a parent Agent's own calls. It
  runs only where a host calls it, so a host's own internal `wait` settles
  nothing. Hide a body before calling it: a `queueing` end whose `last_message`
  is hidden is not settled.
- `close_notices()` stops delivery for a host about to stop its children: later
  ends and requests are held in the same record write, no receiver runs and no
  parent is continued. `interrupt_owned()` calls it; a host stopping children
  another way calls it first.

A parent Agent's held notices are handed to its bound receiver after `driver.start`
returns, so a driver's receiver must take input by then, or wait for it as the
Pi driver's does.

Gaps, by owner:

| Gap | Owner |
| --- | --- |
| A notice admitted between the `headless` DSH runner's last Session flush and its exit (*DSH host* above; `dsh-headless/lib/index.js:377`, `:383`): the relay answers before that write | Upstream DSH; not changed |
| A child Runtime that outlives a killed Claude host: Claude Code can kill the host before it stops its children (`mcp.py` `INTERRUPT_SECONDS`), so the execution stays `running` with no notice yet. The notice arrives on a later host process, or read it through `status`. In the one real run (403), Claude Code 2.1.314's SIGINT left the host time to finish (`agents host recorded its children stopped.`, in all 3 Claude runs of that step), and the end arrived as `interrupted`. A kill was not observed, so the case stays possible by code | Unassigned, needs Main |
| The notice title names GraphTraj | 394 |

### 4.1 Native approval per Runtime

agents uses each Runtime's own approval where it has one and never loosens
its sandbox, network or write limits. A request the Runtime asks about is held
for the direct parent as above.

| Runtime | How native approval is enabled | Configuration agents writes |
| --- | --- | --- |
| Claude Code | The supplied `permission_mode`; Claude's permission prompts arrive through `can_use_tool` | Passes the mode as `--permission-mode` and `permissions.defaultMode`; nothing else |
| Codex | `approvals_reviewer`, default `auto_review` (Codex's own reviewer decides) | Sets `approvals_reviewer = "auto_review"` when the settings name no reviewer, and `features.exec_permission_approvals = true`. `approval_policy`, sandbox, permissions and network stay as supplied. With a connection's `review` (section 6): `approvals_reviewer = "user"`, so Codex hands each approval to the review plugin; `approval_policy = "never"` is refused with `invalid-config`, and a Session Codex reports as `never` ends `failed`, because no request would reach the reviewer |
| Pi | Pi has no approval of its own; extension dialogs (`extension_ui_request`) are the requests | None. With a connection's `review` (section 6): the agents extension's `tool_call` hook, enabled by the owner for that execution; a reviewed Pi with no agents connection is refused with `ROLE_CONFIG_UNSUPPORTED` |
| DSH | The `permission` profile patch, approval `ask`, for the chosen sandbox mode | The `sandbox-policy` and `permission` patches; `dsh/approval-request` is the request. With a connection's `review` (section 6): also the `agents-review` plugin row |

**Codex auto review relay.** Under `auto_review`, Codex decides approvals
itself and reports the outcome only as an `item/autoApprovalReview/completed`
notification (Codex 0.164 app-server). agents turns an outcome of `denied`
(a refusal) or `timedOut`/`aborted` (the reviewer failed) into a request for
the direct parent, with `method: "item/autoApprovalReview/completed"`,
`request_id: "auto-review:<reviewId>"` and the notification as `params`.
Approvals are not relayed. Codex 0.164 has no "escalate" outcome; an action
Codex hands to the client as a server request is held like any native
request.

- The child's execution stays active until the parent answers, even if the
  reviewed turn has ended. `reply` takes exactly `{"decision": "accept"}` or
  `{"decision": "decline"}`.
- `accept` after `denied` records Codex's one-retry approval
  (`thread/approveGuardianDeniedAction`). After a reviewer failure no native
  record is written. Either way the child is told it may retry once, and the
  retry **goes through auto review again**: the parent cannot approve the
  action itself, widen it, or skip the reviewer. If Codex refuses the
  approval, `reply` fails and the request stays pending.
- `decline` keeps the refusal; the child is told not to retry.
- The answer reaches the child as input to its running turn; an accepted
  answer after the turn ended starts one follow-up turn. A declined answer
  after the turn ended starts nothing.
- Interrupting the child drops its unanswered relays.

**Claude review plugin (386).** A Claude child whose connection names a reviewer
(section 3) has every tool call judged in a `PreToolUse` hook on its own control
pipe, except the bound `mcp__agents__agents` tool: it is the child's channel to
its parent, limited by agents' authority checks, and must work when the reviewer
is down. Read-only tools are reviewed too. The hook's timeout outlasts the
reviewer (its timeout plus 60 seconds, at least 600), and the host always answers
before it, so nothing depends on what Claude does past it. On Claude Code 2.1.314
a hook past its timeout was cancelled and the call did not run (one observation,
one tool); a hook that errors is untested. Without a reviewer the hooks and
settings are unchanged.

- `allow`: the hook answers `{}` with no permission decision, so Claude's own
  rules, mode and sandbox still apply. A later `can_use_tool` for that call (same
  `tool_use_id` and input; without an ID, the exact tool and input) is answered
  with its original input and does not reach the parent, unless it names
  `blocked_path` or the input sets `dangerouslyDisableSandbox`: the reviewer was
  not asked to widen a native limit, so those are held as native requests. A
  prompt for any other call is held as before.
- `deny`, `escalate` or a failed review, including any error in this path: the
  hook answers Claude's own `deny`, telling the child its parent has been asked
  and not to retry, and a request is held with `method: "agents/review"`,
  `request_id: "agents-review:<uuid>"` and `params` `{"tool", "input", "decision",
  "reason"}`. An identical call while that request waits is refused without
  asking the reviewer or the parent again.
- `reply` takes exactly `{"decision": "accept"}` or `{"decision": "decline"}`.
  `accept` releases one retry of exactly that call: it skips the reviewer, not
  Claude's own limits, and a repeat or a changed input is reviewed again.
- The answer reaches the child as input to its running turn; an accepted answer
  after the turn ended starts one follow-up turn. A declined answer after the turn
  ended starts nothing. The execution stays active until the parent answers.
- Interrupting the child drops its unanswered requests and releases; a release
  also ends with its execution.
- Each decision and released retry is recorded in `review.jsonl` in the child's
  execution directory, without the tool input. The reviewer's key variable is not
  passed to the child.

## 5. `extra_fields` in the normalized Session

The header and any event may carry an `extra_fields` container:

- `extra_fields` is a JSON object. Keys are non-empty strings naming a
  namespace (`extra_fields.<namespace>`); values are any JSON value without
  non-finite numbers. agents validates only this container
  (`validate_extra_fields`); each namespace validates its own content.
- Each namespace versions itself, for example `extra_fields.graphtraj =
  {"version", "projectId", "agentId", "taskIds"}`.
- A reader that does not know a namespace ignores it safely; agents itself
  never reads a namespace. An extension field never changes the meaning of a
  core field, and never affects messages, order or identity.
- Header fields are attached when the archive is created, through the
  collectors' `extra_fields` argument, which hosts fill from `create`'s
  `extra_fields` argument (or `AgentControl.create(..., extra_fields=)` in
  programmatic construction); configuration is not a source today. The first
  writer's header is kept: reopening with a different header is refused.
- Event fields are written only by programmatic extensions:
  `SessionArchive(..., event_fields=callable)`. The callable receives a copy
  of each event about to be written (newly published events and drafts) and
  returns an `extra_fields` object, merged by namespace, or `None`. A
  published event keeps the fields it was first written with. Model arguments
  never reach it.
- Credential redaction applies to `extra_fields` in the header and in events
  before they are written: credential-named keys and recognizable secrets
  (bearer tokens, `sk-` keys, URL passwords, credential environment values)
  become `[redacted]`. Native content is archived losslessly and is not
  redacted.
- Old files: a top-level `graphtraj` key is read as described in section 1.5:
  its product keys become `extra_fields.graphtraj`, its core keys become core
  fields. New files are written only in the new form.
- The protocol version increase is carried by `header.version` (4 → 5).
  Readers older than agents 0.2.0 refuse version 5, so this is an
  incompatible change under section 7.

All existing fidelity rules stay (native order, no reordering by notice
time).

## 6. Review plugin decision format

**Format and rules: 385 (`agent_swarm.approval`); the review plugin: 386,
387.** When a Runtime's native approval is missing or
unusable, the agents review plugin judges each tool call the adapter can see
before it runs. Every
Runtime adapter accepts the same decision document from the reviewer and
nothing else:

```json
{"decision": "allow", "reason": "Reads a file inside the assigned workspace."}
{"decision": "escalate", "reason": "Pushes to a remote; needs the parent."}
{"decision": "deny", "reason": "Deletes files outside the task."}
```

| Field | Required | Values |
| --- | --- | --- |
| `decision` | yes | `allow`, `deny` or `escalate` |
| `reason` | yes | non-empty string, shown to the parent and kept in the record |

Rules:

- The document must be exactly one JSON object with these two fields and
  types. Any other field (`category` included), value or shape, an empty
  answer, a timeout, a connection failure or any reviewer error is a **failed review**: the call is refused
  and goes to the direct parent, with the failure as the reason.
- `allow` lets the call run. It is the only decision that does.
- With `deny` and `escalate` the call does not run and goes to the direct
  parent, which may release it within its own authority: Claude refuses it at
  once and releases one exact retry; Codex holds the native request, and Pi and
  DSH hold the call, until the parent answers. The root may refer it to a person.
- The format is the same for every Runtime and every reviewer model. Adapters
  translate it to their native hook; native fields never appear in it.

agents applies no high-risk rule of its own to requests, reviews or replies:
safety rests on workspace isolation (section 2), the Runtime's native
sandbox and approval or auto review (4.1), the review plugin where native
approval is missing (386, 387), and parent fallback below.

**Parent fallback (layer 4).** A refused or failed review, and every native
request the Runtime itself hands over, reaches the direct parent as a pending
request (section 4). Before `reply` reaches any driver, agents checks it
against the request as the Runtime reported it (a parent's edited copy is not
used):

- a declining reply (Claude `behavior: deny`, Codex `decline`/`cancel` or
  empty `permissions`, Pi `confirmed: false`/`cancelled`, DSH `reject`)
  always passes;
- an approving reply may grant at most what was asked, else
  `authority-denied`: Claude may not replace the tool input; Codex may answer
  only `accept` (not `acceptForSession` or a policy amendment) and only the
  requested permissions for the turn; a Pi `select` must pick an offered
  option;
- a request held by the Claude, Pi or DSH review plugin (`agents/review`, 4.1 and
  below) takes exactly `{"decision": "accept"}` or `{"decision": "decline"}`, else
  `invalid-input`.

The parent's own sandbox is not compared with the request; a parent should
decline what it could not do itself. The root may refer a request to a
person: the person answers in the root's own host (its native approval of
the root's `reply` call, or the conversation), and the root then replies.

**Review request.** The reviewer receives `{"version": 1, "runtime", "tool",
"input", "cwd", "instruction", "native"}`: the exact planned call, its working
directory, the task the direct parent gave (bounded to about 20000 characters,
with a `<truncated .../>` marker) and the Runtime's own facts (`native`, or
`null`). `tool` is the Runtime's name for the call; for Codex, the approval
method.

**Connection (section 3).** The shared policy, `agent_swarm/review_policy/`, is
the reviewer's prompt only. A `base_url` reviewer gets one POST to
`{base_url}/chat/completions`, with the policy as system message, the request as
JSON user message and `stream: false`. There are no retries and no redirects. It
must finish with `finish_reason: stop`; the message content is parsed as above,
with no repair and no stripping of code fences. A key variable that is missing
or empty is a failed review naming only the variable. A `command` reviewer gets
`{"policy", "request"}` on stdin and answers the decision document on stdout; it
is killed at its timeout, and a non-zero exit is a failed review. Every failure
reason is free of credentials and of echoes of the request; an HTTP failure
keeps the status and the provider's `code`, `type` and `message`. The reviewer's
`api_key_env` variable is read only by the host and is removed from the child's
environment, unless the child's own connection gives it that variable.

**Connectivity check.** `create` sends one review call through the same path
with a fixed harmless request (`tool: agents/connectivity-check`), bounded by the
reviewer's timeout. A well-formed decision of any value passes. A transport
failure or an invalid document fails `create` with `review-unavailable` and the
reason, so an endpoint that would reject every review is reported at once.

**Codex adapter.** Every command, file change, permissions and MCP tool call
approval is reviewed before it runs. Calls Codex runs without asking, because
its sandbox and `approval_policy` allow them, are not reviewed and stay inside
that sandbox; a granular `approval_policy` object is not inspected. A request
Codex hands over may ask to go beyond its sandbox, and `allow` grants that one
request, as Codex's own reviewer would; this differs from Claude, where the
reviewer's allow never answers a sandbox or directory prompt. `allow` accepts exactly that request, with
the exact requested permissions for the turn and no persistent trust. `deny`,
`escalate` or a failed review holds the same native request for the direct
parent, with `params.review: {"decision", "reason"}` added: `requests`, the
single notice, `wait` and the reply checks above work unchanged, and interrupting
the child drops the hold. There is no retry and no second review. Each decision
is appended to `review.jsonl` in the Agent's driver directory, without the tool
input (internal, like the rest of that directory). A decision that cannot be
written does not run.

**Pi and DSH adapters (387).** Both hold the tool call until it is answered, like
Codex and unlike Claude, so the reviewed call is the call that runs and there is
no retry. The native side waits with no timeout of its own: Pi's dialog
(`rpc-mode.js`) and DSH's approval wait in `serviceAsk`. In both:

- `allow` lets the call run with nothing reaching the parent. It answers only this
  review: Pi's sandbox and DSH's sandbox, permission mode and guards still apply.
- `deny`, `escalate` or a failed review, including any error in this path, holds
  the call. A request reaches the direct parent with `method: "agents/review"`,
  `request_id: "agents-review:<uuid>"` and `params` `{"tool", "input", "decision",
  "reason"}`. `reply` takes exactly `{"decision": "accept"}`, which runs that one
  call once with no second review, or `{"decision": "decline"}`, which refuses it.
- Interrupting the child, or its end, drops every hold and every review in
  progress, and those calls do not run.
- Each decision is appended to `review.jsonl` in the Agent's driver directory,
  without the tool input, before it takes effect. A decision that cannot be written
  does not run.
- The reviewer runs in the host, outside the child's sandbox and off the threads
  reading the Runtime's protocol; no sandbox, network or write grant is added for
  it. Its `api_key_env` variable is removed from the child's environment, unless
  the child's own connection names that variable.
- The bound agents tool, `mcp__agents__agents`, is not reviewed and is the only tool
  that is not: it is the child's channel to its parent, limited by agents' authority
  checks, and must work when the reviewer is down.
- Before the first prompt the owner establishes that the hook is installed, else
  the execution ends `failed` with `RUNTIME_REQUEST_FAILED` and no model work. Every
  execution checks this, `resume` included. Without a reviewer the hooks, settings
  and approval modes are unchanged.

*Pi.* A `tool_call` handler in `pi/extension.mjs` holds each call on a native
`confirm` dialog whose reserved title the owner chooses for that execution and
passes in `AGENT_SWARM_PI_REVIEW`. The extension removes the variable from its
environment at once, so no tool's process inherits the title. A dialog with that
title never reaches the parent as `pi/confirm`; any other dialog is an ordinary
native request. Pi documents a `tool_call` handler failure as blocking the tool
(`docs/extensions.md`). Calls a tool makes through `ctx.executeTool`, such as
codemode's, go through the same pipeline and hooks (`agent-session.js`
`_executeNestedToolCall`), so the outer and each nested call are reviewed. The hook
is established by RPC `get_commands` reporting the `agents-review-hook` command from
this `extension.mjs`.

Limits on Pi 1.4.0. Pi loads `--extension` paths before the connection home's
extensions (`resource-loader.js`, `mergePaths`) and runs `tool_call` handlers in that
order, in place on one `input` (`docs/extensions.md`), so an extension in the
connection's home can change a call's input after it was reviewed; that home is the
user's own trust decision. A `mcp.json` server named `agents` in that home overrides
the bound one (`docs/mcp.md`), and its `agents` tool would have the exempt name.

*DSH.* The `agents-review` row (`dsh/review.mjs`) is a `tools/pre-execute` listener
that calls DSH's own decision first. A native deny stays denied and a native ask
stays a native `dsh/approval-request` for the parent, unreviewed. Only a call DSH
itself would allow becomes a review, as an approval ask marked by a key of
`displayReason` that holds the tool and exact arguments. Native asks set only fixed
locale keys there (`dsh-sandbox`, `dsh-experimental-auto-review`), and model-written
text reaches their values and `reason`, never a key, so the classification does not
rest on text a model can influence. A frame whose mark is absent, malformed or names
another tool or call is an ordinary native request: no reviewer call and no
`allowed-once`. A sandbox escalation is a separate native ask inside the tool body
(`approveEscalation`), so it reaches the parent even after the reviewer allowed the
call: the reviewer's `allow` never widens the sandbox. The outer `run_code` and each
inner call are reviewed. The hook is established by a file the row writes when it
registers, named for that execution.

*DSH's own auto-review and this plugin.* In an agents child DSH's experimental
auto-review (`@deepseek-ai/dsh-experimental-auto-review`) never applies. The plugin
applies when the connection names a reviewer; otherwise a request DSH asks about
goes to the direct parent as in 4.1. Auto-review acts only under the `auto` permission
preset, which it registers and which runs with Full access (no file sandbox). agents
never selects that preset: it accepts only `read-only` and `workspace-write`
(`dsh/settings.py`) and writes approval `ask` for the chosen mode. agents' profile,
`dsh-base` and `dsh-web-app`, does not install that layer. If a connection's own home
has it installed, its listener calls `next()` because the preset is not `auto`. It
also reviews with the child's own provider and model, unlike this plugin's separately
configured connection.

## 7. Version rules

agents follows semantic versioning on the interface above.

**Incompatible** changes:

- removing or renaming a command, flag, exit status, MCP method or tool,
  feature, argument, result field, error code, config field, entry point
  group or public Python name;
- changing the meaning or type of any of them, or a default that changes
  observable behaviour;
- accepting less than before: a new required argument, a narrower type or
  value range, a new rejection of a request that used to succeed;
- an archive change that current readers cannot read, including raising
  `header.version`;
- changing the decision format in a way current adapters or reviewers would
  reject or read differently.

**Compatible** changes: new features, new optional arguments, new result
fields, new error codes for new situations, new config fields with defaults
that keep current behaviour, new archive fields, events or `extra_fields`
namespaces that current readers ignore, and fixes that make behaviour match
this document.

Consumers must ignore result fields and archive fields they do not know.

Recorded classifications:

- 388: `send` with `reports_only: true` is rejected with `not-implemented` by
  agents' own backend, which used to ignore the field and start new work. This
  is a fix (compatible): the silent ignore contradicted the field's only
  documented meaning, "starts no new work". No version-range change.
- 388: envelope validation errors gained `action` and a coded `error` object
  (see 1.2). A fix that makes them match the documented error structure.
- 381 (0.1.2): a Codex model mismatch at `thread/start`/`thread/resume` or a
  `model/rerouted` notification now ends the child `failed` with
  `RUNTIME_REQUEST_FAILED` under every host, GraphTraj included (section 2).
  A fix: the run used to continue on another model, contradicting the rule
  that a chosen value is never silently replaced.
- 386 (0.2.1): `reviewers`, a connection's `review`, the Agent document's
  `review`, selection's `review`, the error `review-unavailable`. Compatible: new
  optional config fields and result fields, with a default that keeps current
  behaviour.
- 387 (0.2.3): a Pi or DSH connection naming a `review`, refused with
  `invalid-config` before, is accepted, and its calls are reviewed. Requests with
  `method: "agents/review"` from those Runtimes are new. Compatible: a configuration
  that could not start before starts now, and a connection without `review` is
  unchanged. The new refusals (a reviewed Pi with no agents connection, a hook that
  is not loaded) are new error situations of that same configuration.
- 381 (0.1.2): the notice event `request` and `AgentControl`'s optional
  `request_notices` argument (default off). Compatible: a new event for a new
  situation, behind a new optional argument with a default that keeps
  current behaviour.
- 382: the Pi host's configuration `{"root", "adapter_request"}` is refused
  and replaced by 1.6. It was never listed as public (1.1 named only the
  Claude and Codex hosts), so this is not an incompatible change. The Pi
  host section, the Pi package manifest, the Pi host's Runtime routing and
  its notices are compatible additions. They ship in 0.2.0, the version 384
  set; 382 adds no bump of its own.
- 403 (0.2.1): `last_result.notification` gains the value `held`, for a notice
  its parent cannot receive now, and `AgentControl` gains the optional
  `hold_notices` argument (default off, which writes nothing new) with
  `held_notices`, `settle_notice`, `settle_shown`, `notice_open` and
  `close_notices`. Compatible: a new value for a new situation, behind a new
  optional argument with a default that keeps current behaviour. All four hosts
  enable it, so `held` replaces `unavailable` for a notice they could not
  deliver; the Pi host also pushes each child request. The Pi and DSH hosts are
  themselves new in 0.2.0. The Claude Code and Codex hosts date from 0.1.0, so
  a consumer of theirs that reads `notification` sees the new value in 0.2.1,
  the version 386 already raised; 403 adds no bump of its own.
- 383: the DSH host section, the `agents-dsh` bundle, the `dsh` entries of the
  Claude Code and Codex hosts' `runtimes` and their DSH refusals are compatible
  additions. The agents DSH gate became a floor (0.2.0-rc.2 or later in semver
  order), which accepts more than before. They ship in 0.2.0; 383 adds no bump
  of its own.
- 400 (0.2.2): the public names and extension methods added to 1.3, and the
  JavaScript exports listed there. Compatible: they only add names. Every
  name they replace was internal, so renaming those is not an incompatible
  change. `import agent_swarm` also stopped loading the `agent_swarm.codex`
  package, which nothing public depended on.
- 408 (0.2.1): the `pi` entry of the Claude Code and Codex hosts' `runtimes`, refused
  at start with `unsupported-runtime` before, is accepted. Its refusals are
  compatible additions: new error situations for a configuration that could
  not start before. A `pi` connection declared without an entry still fails
  with `unsupported-runtime`. 408 adds no bump of its own.
- 411 (0.2.2): a DSH child no longer inherits `DEEPSEEK_BASE_URL` or
  `DEEPSEEK_SEARCH_BASE_URL`, and a failed turn's message gains the native
  error (section 2). A fix (compatible): section 2 already said a key never
  reaches another endpoint, and no document offered the variables as a way to
  route a child. A setup that did rely on them now reaches DSH's official root,
  and must declare `base_url`. 411 adds no bump of its own.
- 413 (0.2.2): `discover_models` for DSH follows the connection's `base_url` and
  `api_key_env` and ignores the two variables, and for Pi no longer runs on the
  home. Pi's keyless `pi_destination` likewise, so a home whose configured package
  cannot be installed no longer has every selection refused. Fixes (compatible):
  a listing used an endpoint and key the connection did not name, and a query
  wrote into the home. 413 adds no bump of its own.
- 413 (0.2.2): a connection with a `base_url` at another origin whose key is
  `DEEPSEEK_API_KEY` sends search to that endpoint and loses DSH's Search and
  Fetch API provider (section 2). A
  fix (compatible): section 2 already said a key never reaches another endpoint.
  A setup that relied on official search through such a gateway must name the
  gateway's key in another variable. No bump of its own.
- 415 (0.2.4): `stop_owned` and `exit_if_owned_unconfirmed` are new public names, and
  the `--output` document gains `stop_unconfirmed`. `interrupt_owned` no longer
  raises when one Agent's interrupt fails, and returns while one is blocked. The
  Codex host now exits non-zero when a stop is unconfirmed, where it exited 0 and
  recorded nothing; the Claude Code hosts name every such Agent where they raised
  naming none. Fixes and additions (compatible). 415 merged while `dev` said
  0.2.3, so 0.2.3 does not identify these names; 0.2.4 does.
- 391 (0.2.4): the version rises for 415's names, and the README, `CHANGELOG.md`
  and host notes join the wheel. Compatible: nothing is removed or narrowed. No
  version has been published; these numbers mark `dev` history, and before 0.2.4
  several fixes merged without a bump, so commits with the same number can differ.
  `CHANGELOG.md` lists each version's content.

While the major version is `0`, an incompatible change raises the minor
version (`0.1.x` → `0.2.0`), and compatible additions and fixes raise the
patch version. From `1.0.0` the usual rule applies: major for incompatible,
minor for additions, patch for fixes. A release that changes this document
updates it in the same change.

GraphTraj declares the range it supports (today `agent-swarm>=0.2.4,<0.3`, since it imports the 0.2.4 names in 1.3)
and widens it in the same change that adopts an incompatible release.

## Appendix: Known GraphTraj-specific surfaces

Places in the package that exist only for GraphTraj and must become generic
or be renamed. Numbers refer to the subtraction list in
`docs/specs/agents-standalone-release.md`. Paths are relative to
`src/agent_swarm/`.

| # | Surface | Where | Owner |
| --- | --- | --- | --- |
| 1 | Codex managed Session MCP server named `graphtraj`; legacy `graphtraj`/`graphtraj_*` tool names refused | `codex/managed_session.py` (`mcp_servers['graphtraj']`, legacy tool check); `pi/extension.mjs` (accepts server `graphtraj`) | 394 |
| 2 | Codex `clientInfo.name` and `toolOutput.name` `graphtraj`; logger `graphtraj.codex.local` | `codex/app_server.py` | 394 |
| 3 | Completion checker profile `graphtraj_checker` and its permission override | Done in 388: `CodexAppServer.fork_session` takes `network_profile` and `unix_socket` from the caller; agents keeps no profile name. GraphTraj owns `CHECKER_PERMISSION_PROFILE` (`graphtraj/runtimes/codex/app_server.py`) and passes it from `finalize.py` | 388 (done) |
| 3 | Pi completion checker entry `graphtraj:completion-checker` | Done in 388: `pi/session.py` `session_source`/`verify_main` take caller-supplied `child_entry_types`; GraphTraj's `runtimes/pi/session_entry.py` passes its own entry type (name unchanged) | 388 (done), 394 (name) |
| 4 | `GRAPHTRAJ_*` variables: `GRAPHTRAJ_CLI_CONNECTION`, `GRAPHTRAJ_NATIVE_RUNTIME`, `GRAPHTRAJ_NATIVE_SESSION`, `GRAPHTRAJ_NATIVE_SESSION_FILE`, `GRAPHTRAJ_CLAUDE_HOST_PYTHON`, `GRAPHTRAJ_CLAUDE_HOST_CONFIG`, `GRAPHTRAJ_DSH_PACKAGE` | `connection.py`, `claude/host.py`, `claude/host_context.mjs`, `claude/execution.py`, `codex/managed_session.py`, `pi/extension.mjs`, `pi/session.py`, `pi/host.py`, `pi/execution.py`, `dsh/plugin.mjs`, `dsh/execution.py` | 394 |
| 4 | Host exclusion check refusing both the independent and the GraphTraj connection | Done in 388: removed from `connection.py` (`call_owner`), `claude/host.py` (`serve`), `pi/extension.mjs` (both branches) and `pi/host.py`; agents keeps only its own `AGENT_SWARM_CONNECTION` checks. GraphTraj refuses the combination in `interfaces/hosted_cli.py` (`forward_request`), `runtimes/claude/host.py` (`serve`) and `runtimes/pi/extension.mjs` (before starting agents) | 388 (done) |
| 5 | Archive header extension `graphtraj` with `projectId`, `agentId`, `taskIds` | Done in 384: agents writes no product fields; GraphTraj passes `extra_fields.graphtraj`. The `graphtraj` name remains only in the version 4 reader (`sessions/protocol.py`, `LEGACY_*`) | 384 |
| 5+ | Core archive facts kept under the `graphtraj` name (event provenance, missing facts, header continuation, `graphtraj/*` types) | Done in 384: product-neutral core fields and types (section 1.5) | 384 |
| 6 | Pi custom message type `graphtraj:agent-communication`, used for display entries and, since 382, for the Pi host's injected notices | `pi/extension.mjs` | 394 |
| 7 | Pi execution's GraphTraj Task fields and fixed `.graphtraj` deny-read and deny-write paths | Done in 382: `pi/host.py` takes a Task-free configuration and builds the Pi request from the native parent (1.6); `pi/execution.py` takes the generic request fields (section 2); GraphTraj supplies its former paths and domains in `graphtraj/runtimes/pi/pi_adapter.py:member_policy` | 382 (done) |
| 8 | No independent DSH host | Done in 383: `dsh/host.py`, the `agents-dsh` bundle (`dsh/package.json`, `dsh/dsh.patch.yml`) and the host row of `dsh/plugin.mjs`; see 1.7 | 383 (done) |
| 9 | Notice title `GraphTraj notice from …` and default sender `graphtraj` | `claude/host_context.mjs` | 394 |
| 10 | `send`'s `reports_only` and its "Task member" description | Done in 388: generic meaning in `tool.py` and 1.2; `AgentControl` rejects `true` with `not-implemented` (fix, see 7). GraphTraj's Task member handling is unchanged | 388 (done) |
| 12 | Archiving refused without GraphTraj's collector | Done in 384: the refusal is removed; each Runtime execution builds its own collector from the bound archive (`claude/execution.py`, `claude/collection.py`, `codex/managed_session.py`, `pi/execution.py`, `dsh/driver.py`) | 384 |
| — | Claude host plugin also handles GraphTraj's `tasks` tool (`mcp__agents__tasks`) | Done in 400: `claude_host_plugin` and `NativeCalls`' `tools` (1.4); GraphTraj declares `tasks` in `runtimes/claude/host.py` | 400 (done) |
| — | Claude control-protocol hook IDs `graphtraj_start`, `graphtraj_collect_child`, `graphtraj_agents_display`, and the event key `graphtraj_direction` | `claude/execution.py`, `sessions/claude.py` | unassigned, needs Main (closest: 394) |
| — | GraphTraj imports internal modules and private names | Done in 400: GraphTraj imports only the names in 1.3, and `tests/test_graphtraj_public_agents_api.py` fails on anything else | 400 (done) |
| 11 | Plugin points and documentation examples that mention GraphTraj | `cli.py`, `config.py`, docstrings | kept by decision |
