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

**Independent hosts.** The host commands documented in the README are public
with their documented flags:

- `python -m agent_swarm.claude.host configuration --project <dir> --claude
  <path> [--write]` and `... serve --config <file>`. The written
  `.agents-control/claude-host.json` keys (`root`, `cwd`, `claude`,
  `channel_file`, `settings`) and the documented `settings` keys are public.
  The `context` operation is the plugin's private channel.
- `python -m agent_swarm.codex.host --settings <file> --directory <dir>
  [--output <file>] [--resume] <instruction>`. On a startup error it prints
  `{"error": {"code", "message"}}` and exits `1`.
- A refused Claude host start answers every call with `host-unavailable` (or
  the refusing check's own code) and writes one JSON line to
  `.agents-control/host.log`.
- The Pi host: the agents Pi extension's `--agents-config <file>` flag and
  that file's keys (1.6). The extension starts `python -I -m
  agent_swarm.pi.host --config <file>` itself; its pipe protocol with the
  extension is private.

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
| `create` | `runtime*`, `instruction*`, `name`, `configuration`, `preset`, `model`, `reasoning_effort` (see 2) | none; returns once the Agent is registered, never waits for its work |
| `send` | `agent*`, `message*`, `reports_only` | `delivery: {at, delivery: submitted\|rejected\|unknown, error?}` when the Agent runs; in standby it continues the Session |
| `status` | `agent` | without `agent`: `{"agents": [document + "children": [...]]}`, the caller's visible hierarchy |
| `wait` | `agent*`, `timeout_seconds*` (finite, > 0) | `timed_out`; also ends early on an unanswered native request |
| `interrupt` | `agent*` | `interrupt: requested\|not-running\|already-requested\|stopped`, `scheduled`, `termination_confirmed` |
| `resume` | `agent*`, `message` (required in standby) | `resumed: false, reason: already-active` when it already runs |
| `requests` | `agent*`, `execution` | `requests: [native request document + "execution"]` |
| `reply` | `agent*`, `request*` (one document from `requests`), `response*` (explicit native response) | the reply receipt; a repeat returns the first receipt with `duplicate: true` |
| `retire` | `agent*` | `retired: true`, `duplicate` on repeat |

An unknown argument, a missing required one or an empty string is rejected.
Identity, permissions, working directory and parentage always come from the
host, never from arguments.

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
  `reasoning_effort` (the choice made at `create`, see 2), `state` (`active`
  or `standby`), `parent`, `creator` (`host`, `agent`, `session`), `host`,
  `session`;
- while running: `execution`, and when present `stopping`, `diagnostic`,
  `pending_requests` (count of unanswered native requests);
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
| `authority-denied` | no owning host, or the caller may not do this |
| `unsupported-runtime` | no driver for the requested Runtime in this host |
| `invalid-config` | rejected driver configuration (any `configuration` in an independent host), an invalid `config.yml`, or a driver that cannot run the selected connection |
| `invalid-preset` | `preset` is not declared, or uses another Runtime than `runtime` |
| `invalid-model` | `model` is not a candidate, cannot be verified, or contradicts the preset |
| `invalid-reasoning-effort` | `reasoning_effort` is not supported by the model or Runtime, or contradicts the preset |
| `ambiguous-connection` | several connections declare the Runtime and no preset selects one |
| `runtime-unavailable` | the selected connection's Runtime is not installed or not logged in on this machine |
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
| `archive-unavailable` | normalized archiving is on but unavailable in this host |
| `host-unavailable`, `host-busy`, `session-exists`, `turn-running` | host start and ownership refusals |
| `start-failed`, `delivery-unknown` | a native start or delivery failed without a native code |

An execution that fails natively keeps the Runtime's own code and message in
`last_result.error` (for example `RUNTIME_REQUEST_FAILED`). Those codes belong
to the Runtime driver; the ones the README documents are public.

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
  `ACTIVE`, `STANDBY`;
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

Every submodule (`agent_swarm.control`, `agent_swarm.claude.*`,
`agent_swarm.sessions.*` and so on) is internal, even where a public name is
defined there; import public names from `agent_swarm`.

### 1.4 Host plugins: the `agent_swarm.hosts` entry point

A package can let the `agents` CLI reach its host when the calling process has
no owner connection. It registers an entry point in the group
`agent_swarm.hosts`. The entry point is a callable taking the current working
directory (`pathlib.Path`) and returning either `None` (this host does not own
the directory) or a dispatch function. The dispatch function receives one
validated action request (`{"action": <feature>, **arguments}`) and returns an
`AgentsResult`. The first plugin that returns a dispatch function handles the
call. This is the only extension point; GraphTraj uses it like any other
package.

### 1.5 Data root and normalized Session archive

The caller chooses the data root. Public within it: `config.yml` (section 3)
and, when archiving is on, one archive per Session at
`sessions/<sha256 of the Session ID>/session.jsonl`. Everything else under the
root is internal.

The archive is JSONL: a header line, then events in native order. Today:

- `header.version` is `4`, the DeepSeek Harness Session v4 layout (see
  `examples/sessions/README.md` in the repository);
- an optional `graphtraj` object on the header and on events carries the
  extension with its own `version` `1`: header `projectId`, `agentId`,
  `taskIds`, `previousSession`, `boundary`; event `native` provenance and
  `missing` facts;
- extension event types `graphtraj/native`, `graphtraj/score`,
  `graphtraj/logprobs`, `graphtraj/derived`, `graphtraj/history`, and the
  content type `graphtraj/encrypted`.

Independent hosts refuse archiving today (`archive-unavailable`); 384 adds it.

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
| `provider_domain` | the selected model's host from Pi's catalog in `agent_dir` (`agent_swarm.models.pi_destination`); refused with `ROLE_CONFIG_UNSUPPORTED` without a plain http(s) destination |
| `allowed_domains`, `base_url`, `provider_api`, `api_key_env`, `reasoning_effort`, `native_directory`, `allow_mach_lookup`, `allow_mach_register`, `allow_local_binding`, `allow_unix_sockets` | none |

Besides these, the Pi owner always reads the worktree, its native Session
directory, the running Python and installed packages and the linked native
Home files; writes only its native directory, the connection socket and (for
`write`) the worktree and Git common directory; denies reading `agent_dir` and
the agents data root, and writing `agent_dir`, the Python prefix, the
packages and `<git_common_directory>/config` and `hooks`. The only domains are
`allowed_domains` plus the `base_url` host or `provider_domain`. A field of the
wrong type fails with `ROLE_CONFIG_INVALID` naming the field. Claude children default to
`worktree_access: read` and DSH children to `sandbox: read-only` unless
their section says otherwise. Without `codex`, a Codex `create` fails with
`invalid-config`.

**Start.** The host verifies that its parent process is the native Pi that
loaded the extension and binds that Pi Session as root caller. It then
refuses archiving (`archive-unavailable`, 1.5) and calls
`AgentControl.require_connections()` (section 2), so a `config.yml`
connection this machine cannot run stops the start rather than a later
turn; `create` checks the selected connection again. A refused start prints
one line `{"error": {"code", "message"}}` on stderr and exits `1`; Pi shows it
as the extension's error and the Session has no `agents` tool.

**Routing.** The host registers the `pi`, `claude`, `codex` and `dsh`
drivers in one `AgentControl`; `create`'s `runtime` selects one, and
`model`, `preset` and `reasoning_effort` are resolved per child (section 2).
The model reaches the Pi Session through the MCP server `agents`.

**Notices and shutdown** are section 4.

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
"reasoning_effort", "provider", "settings"})`, where `settings` is the
declared connection entry or `null`. A selected connection replaces the
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
copied or returned. The Pi host calls it at start (1.6); 381 and 383 wire
it into the other hosts.

**Agent document.** Every Agent document carries `preset`, `connection`
(the connection's name), `model` and `reasoning_effort` as chosen at
`create`; `null` means not chosen (the host's or Runtime's default).
Agents created before 0.1.1 show `null` for all four.

**Fallback.** When the Runtime answers with a different model than
requested (for example a safeguard fallback), the child's result names the
requested model, the observed model and the Runtime's reason, as 369 does
for Claude today. 381 carries this to every host and Runtime.

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
    models:                         # optional candidates; omitted: native discovery
      - claude-opus-5-5             # an id, or
      - id: claude-sonnet-5-5       # a mapping with id and optional alias,
        supported_efforts: [low, high]   # provider, supported_efforts
presets:                            # optional
  reviewer:                         # selected by create's preset
    connection: work-claude         # exactly one of connection or runtime
    model: claude-sonnet-5-5        # optional
    reasoning_effort: high          # optional
```

- The two booleans keep their meaning and defaults. A value must be exactly
  `true` or `false`.
- Blank lines and comments are allowed. Reading is strict: an unknown or
  repeated field, a wrong type, a preset naming an undeclared connection, or
  a preset with both or neither of `connection` and `runtime` fails with
  `<file>:<line>: <field>: ...`; `create` reports it as `invalid-config`.
- `read_connections(root)` returns `{"connections": {name: entry},
  "presets": {name: entry}}`; each entry is the file's fields plus `name`.
- `write_config` and `default_config` replace only the boolean lines and keep
  every other line, including connections, presets and comments.
- A file that holds only boolean lines is read exactly as before 0.1.1.

## 4. Parent-child traffic

There are exactly three kinds of traffic between a parent and a child, and
only these notify the parent:

| Kind | Direction | Today |
| --- | --- | --- |
| Message | both ways | parent → child: `create` `instruction`, `send`, `resume`. Child → parent: the child's final answer when its round ends and it has no running members of its own |
| Permission request (decision or resources) | child → parent, waits for a reply | native approval requests only: `wait` returns early, the Agent document shows `pending_requests`, the parent reads them with `requests` and answers once with `reply` |
| System exception | system → parent | an execution ending `failed` or `interrupted`, with `last_result.error` |

Delivery rules:

- Each event reaches the parent once. `last_result.notification` records it:
  `pending`, `queueing`, `queued`, `delivered`, `unconfirmed` or
  `unavailable`. Once the body was delivered (or may have been), `status` and
  `wait` show `last_message: null` instead of repeating it; a queued body
  stays readable there.
- A failed or interrupted end notifies immediately, whatever the child's
  members are doing.
- A completed round of a child that still has running members is recorded,
  not pushed. All rounds stay readable through `status`.
- While the parent is stopped, notices are held and delivered when it
  resumes. A child Agent that is itself a parent is continued with its
  child's reply. Under GraphTraj this is the 367, 372 and 375 behaviour.
- There is no separate "ask for attention" call and no parent watch switch.

What the parent sees today:

- **Claude Code host:** each notice is `{"id": "<execution>:<event>",
  "event": {"alias", "event", "message", "execution"}}`. The host plugin
  pushes it into the Main Session as `[GraphTraj notice from <alias> ·
  <event>]` followed by the message; otherwise it is attached as
  `main_notices` to the next `agents` result. An end already shown by `wait`
  or `status` is not pushed again.
- **Codex host:** one host event per notice, `{"source": "agents", "alias",
  "event", "message"}`, sent to the parent Session.
- **Pi host:** each notice is injected into the Pi Session with Pi's
  `pi.sendMessage` as a displayed custom message (`customType`
  `graphtraj:agent-communication`, content `[agents notice from <alias> ·
  <event>]` and the message, `details.fact` `notice:<execution>:<event>`),
  with `triggerTurn: true, deliverAs: "followUp"`: an idle Session starts a
  turn with it, a busy one receives it after the current turn's work. The
  notice is `delivered` once the extension acknowledges the injection,
  `unconfirmed` without an acknowledgement within 10 seconds, and
  `unavailable` (body readable through `status` and `wait`) when it could not
  be written or injected. While a notice is on its way (`notification:
  queueing`), `wait` and `status` also show `last_message: null`, so a
  `wait` that ends with the child does not repeat the body the notice
  carries. Permission requests are not pushed: `wait` ends early and the
  parent uses `requests` and `reply`.
- **Pi Session shutdown** (Pi's `session_shutdown`: quit, reload, new, resume
  or fork):
  the extension stops injecting and closes the host's pipe. The host stops
  pushing, then interrupts every running child, descendants first, and
  waits up to 10 seconds for each. The ends this causes, and any notice not
  yet acknowledged, are recorded `unavailable`, not held: they stay readable
  through `status` when the same Pi Session is resumed with the same
  configuration, and are not pushed then. Agents, Sessions and records are
  kept.
- `event` is `completed`, `interrupted` or `failed`; `message` is the child's
  answer, else the error message, else the outcome.

Gaps, by owner:

| Gap | Owner |
| --- | --- |
| Independent hosts (the Pi host included) do not push a child's native permission request; the parent polls | 381 |
| Codex children's native approvals are handled by `auto_review` and not relayed to the parent | 385 |
| Independent hosts do not hold notices while the parent is stopped: the Claude host's queue lives in its process, and the Codex host marks them `unavailable` (readable through `status`). The Pi host records them `unavailable` as above (closed in 382 by recording, not holding) | 381 (Claude, Codex), 383 (DSH) |
| A child cannot ask its parent for a decision or more resources except through native approval requests | unassigned, needs Main (closest: 381) |
| The notice title names GraphTraj | 394 |

## 5. `extra_fields` in the normalized Session

**Planned (384).** The archive gains an `extra_fields` container on the
header and on any event:

- `extra_fields` is a JSON object. Keys are non-empty strings naming a
  namespace (`extra_fields.<namespace>`); values are any JSON-serializable
  value. agents validates only this container; each namespace validates its
  own content.
- Each namespace versions itself, for example `extra_fields.graphtraj =
  {"version", "projectId", "agentId", "taskIds"}`.
- A reader that does not know a namespace ignores it safely. An extension
  field never changes the meaning of a core field.
- Header fields are attached at `create` through its arguments or
  configuration. Event fields are written only by programmatic extensions
  (hooks, plugins), never by model arguments.
- Credential redaction applies to `extra_fields` as to every other field.
- Old files: a top-level `graphtraj` key is read as
  `extra_fields.graphtraj`. New files are written only in the new form.
- The archive protocol version increases by one. Today the header carries
  `version: 4` and the extension `graphtraj.version: 1`; 384 records here
  which number carries the increase. Current readers refuse a header version
  other than 4, so raising it is an incompatible change under section 7.

All existing fidelity rules stay (native order, no reordering by notice
time).

## 6. Review plugin decision format

**Planned (385, 386, 387).** When a Runtime's native approval is missing or
unusable, the agents review plugin judges each tool call before it runs. Every
Runtime adapter accepts the same decision document from the reviewer and
nothing else:

```json
{"decision": "allow", "reason": "Reads a file inside the assigned workspace."}
{"decision": "escalate", "reason": "Pushes to a remote; needs the parent."}
{"decision": "deny", "reason": "Sends a token to an unknown host.", "category": "high-risk"}
```

| Field | Required | Values |
| --- | --- | --- |
| `decision` | yes | `allow`, `deny` or `escalate` |
| `reason` | yes | non-empty string, shown to the parent and kept in the record |
| `category` | no | `high-risk`: an operation no layer may release |

Rules:

- The document must be exactly one JSON object with these fields and types.
  Any other field, value or shape, an empty answer, a timeout, a connection
  failure or any reviewer error is a **failed review**: the call is refused
  and goes to the direct parent, with the failure as the reason.
- `allow` lets the call run. It is the only decision that does.
- `deny` and `escalate` refuse the call now and go to the direct parent, which
  may release it within its own authority. The root may refer it to a person.
- `category: high-risk` always refuses, whatever `decision` says, and the
  parent cannot release it either. The high-risk classes (at least leaking
  credentials across a trust boundary) are defined by 385.
- The format is the same for every Runtime and every reviewer model. Adapters
  translate it to their native hook; native fields never appear in it.

The review request sent to the reviewer, the review connection settings and
the startup connectivity check belong to 386.

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
- 382: the Pi host's configuration `{"root", "adapter_request"}` is refused
  and replaced by 1.6. It was never listed as public (1.1 named only the
  Claude and Codex hosts), so this is not an incompatible change. The Pi
  host section, the Pi package manifest, the Pi host's Runtime routing and
  its notices are compatible additions (patch). The version number itself is
  raised at release by whoever integrates 381–385, so parallel changes do not
  each bump it.

While the major version is `0`, an incompatible change raises the minor
version (`0.1.x` → `0.2.0`), and compatible additions and fixes raise the
patch version. From `1.0.0` the usual rule applies: major for incompatible,
minor for additions, patch for fixes. A release that changes this document
updates it in the same change.

GraphTraj declares the range it supports (today `agent-swarm>=0.1.0,<0.2`)
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
| 5 | Archive header extension `graphtraj` with `projectId`, `agentId`, `taskIds` | `sessions/protocol.py`, `sessions/archive.py`, `sessions/claude.py`, `sessions/codex.py`, `sessions/codex_history.py`, `sessions/pi.py` | 384 |
| 5+ | Core archive facts kept under the `graphtraj` name: event `graphtraj.native` provenance (required for every archived event), `graphtraj.missing`, header `previousSession`/`boundary`, types `graphtraj/native`, `graphtraj/history`, `graphtraj/text-run`, `graphtraj/encrypted`, `graphtraj/collection-pending` and the other `graphtraj/*` types. These are core meaning, so they cannot simply move into `extra_fields.graphtraj` | `sessions/protocol.py`, `sessions/archive.py`, `sessions/migration.py`, all `sessions/*` mappers | 384 for structure, 394 for names; larger than spec item 5, Main to confirm |
| 6 | Pi custom message type `graphtraj:agent-communication`, used for display entries and, since 382, for the Pi host's injected notices | `pi/extension.mjs` | 394 |
| 7 | Pi execution's GraphTraj Task fields and fixed `.graphtraj` deny-read and deny-write paths | Done in 382: `pi/host.py` takes a Task-free configuration and builds the Pi request from the native parent (1.6); `pi/execution.py` takes the generic request fields (section 2); GraphTraj supplies its former paths and domains in `graphtraj/runtimes/pi/pi_adapter.py:member_policy` | 382 (done) |
| 8 | No independent DSH host | `dsh/` | 383 |
| 9 | Notice title `GraphTraj notice from …` and default sender `graphtraj` | `claude/host_context.mjs` | 394 |
| 10 | `send`'s `reports_only` and its "Task member" description | Done in 388: generic meaning in `tool.py` and 1.2; `AgentControl` rejects `true` with `not-implemented` (fix, see 7). GraphTraj's Task member handling is unchanged | 388 (done) |
| 12 | Archiving refused without GraphTraj's collector | `config.py` (`reject_archive_without_collector`), `claude/host.py`, `codex/host.py` | 384 |
| — | Claude host plugin also handles GraphTraj's `tasks` tool (`mcp__agents__tasks`) | `claude/host_context.mjs` | unassigned, needs Main |
| — | Claude control-protocol hook IDs `graphtraj_start`, `graphtraj_collect_child`, `graphtraj_agents_display`, and the event key `graphtraj_direction` | `claude/execution.py`, `sessions/claude.py` | unassigned, needs Main (closest: 394) |
| — | GraphTraj imports internal modules and private names (`agent_swarm.control._scope`, `_alive`, `sessions.codex_values._timestamp`, and about 40 other internal modules) instead of only the names in 1.3. The version range does not protect these, because internal changes do not change the version | `src/graphtraj` (consumer side) | unassigned, needs Main |
| 11 | Plugin points and documentation examples that mention GraphTraj | `cli.py`, `config.py`, docstrings | kept by decision |
