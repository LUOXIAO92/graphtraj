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
  `channel_file`, `settings`, and since 0.1.2 the optional `runtimes`) and
  the documented `settings` keys are public. `settings` configures the
  host's Claude children. `runtimes` maps another Runtime's name to its
  driver settings: `codex` takes the document `agent_swarm.codex.host
  --settings` takes (`adapter_request`, optional `evidence`, `connection`);
  since 383 `dsh` takes the DSH driver settings (section 2, DSH children)
  and runs in `cwd`. A Runtime without an entry has no driver (`create`
  fails with `unsupported-runtime`). At start the host refuses a `pi` entry
  (`unsupported-runtime`, not supported by this host yet), a `claude` entry
  or a non-object value (`invalid-config`), invalid Codex settings
  (`invalid-config`), invalid DSH settings or a missing or unsupported DSH
  (the DSH codes in section 2), and whatever
  `AgentControl.require_connections()` refuses, each with its own code.
  The `context` operation is the plugin's private channel.
- `python -m agent_swarm.codex.host --settings <file> --directory <dir>
  [--output <file>] [--resume] <instruction>`. Since 0.1.2 the settings file
  may hold an optional top-level `runtimes` object: a Runtime name to that
  driver's settings. The host removes it before reading its own Codex
  settings. `claude` takes the documented Claude host `settings` keys and,
  since 383, `dsh` takes the DSH driver settings (section 2, DSH children);
  both run in `adapter_request.worktree_path` and are checked at start. A
  Runtime without an entry has no driver (`create` fails with
  `unsupported-runtime`). At start the host refuses a `pi` entry
  (`unsupported-runtime`, not supported by this host yet), a `codex` entry or a non-object value
  (`invalid-config`), invalid DSH settings or a missing or unsupported DSH
  (the DSH codes in section 2), and whatever
  `AgentControl.require_connections()` refuses. On a startup error it prints
  `{"error": {"code", "message"}}` and exits `1`.
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
  `reasoning_effort` (the choice made at `create`, see 2), `workspace` (the
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
  Runtime. It never runs an inference turn and never returns credentials;
- the normalized Session archive (section 1.5): `read_session(path)` returns
  `{"header", "events"}` in version 5 form for version 4 and 5 files, and
  `validate_extra_fields(value)` checks an `extra_fields` container (section 5).
  `SessionArchive` takes the keyword `event_fields` (section 5).

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

This is a floor, not a pin: no newer DSH is refused for its version. GraphTraj's
own DSH members (`graphtraj.runtimes.dsh`) still require exactly 0.2.0-rc.2.

**Agent document.** Every Agent document carries `preset`, `connection`
(the connection's name), `model` and `reasoning_effort` as chosen at
`create`; `null` means not chosen (the host's or Runtime's default).
Agents created before 0.1.1 show `null` for all four.

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
| Permission request (decision or resources) | child → parent, waits for a reply | native approval requests, and the child's own `ask_parent`: the parent is notified once per request (event `request`, see below), `wait` returns early, the Agent document shows `pending_requests`, the parent reads them with `requests` and answers once with `reply` |
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
  or `status` is not pushed again.
- **Codex host:** one host event per notice, `{"source": "agents", "alias",
  "event", "message"}`, sent to the parent Session while its turn runs. It
  enables `request_notices`, for children of every Runtime it runs (Codex,
  Claude). The `--output` document lists the notices in `deliveries`.
- **Pi host:** it enables `request_notices` and `hold_notices`, for children
  of every Runtime it runs. Each notice is injected into the Pi Session with
  Pi's `pi.sendMessage` as a displayed custom message (`customType`
  `graphtraj:agent-communication`, content `[agents notice from <alias> ·
  <event>]` and the message, `details.fact` `notice:<id>`, the id as for
  Claude above), with `triggerTurn: true, deliverAs: "followUp"`: an idle
  Session starts a turn with it, a busy one receives it after the current
  turn's work. The notice is `delivered` once the extension acknowledges the
  injection, `unconfirmed` without an acknowledgement within 10 seconds (it may
  have been shown, so it is never repeated), and `held` when it could not be
  written or injected. While a notice is on its way (`notification:
  queueing`), `wait` and `status` also show `last_message: null`, so a
  `wait` that ends with the child does not repeat the body the notice
  carries. Before injecting, the extension looks for the same `details.fact`
  among the Session's `custom_message` entries; when it is there (a crash
  after injecting and before acknowledging), it acknowledges without
  injecting again. A notice queued as a follow-up reaches the Session file
  only when Pi delivers it (`dist/core/agent-session.js:760`), and it is
  acknowledged when handed to Pi: a Pi process that dies with it still queued
  loses that notice, which is already `delivered`. Sources are
  `@earendil-works/pi-coding-agent` `1.4.0`.
- **Pi Session shutdown** (Pi's `session_shutdown`: quit, reload, new, resume
  or fork):
  the extension stops injecting and closes the host's pipe. The host stops
  pushing, then interrupts every running child, descendants first, and
  waits up to 10 seconds for each. The ends this causes, and any notice not
  yet acknowledged, are `held`, readable through `status`. Agents, Sessions
  and records are kept.
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
  | Host or DSH process stopped (Session disposed, DSH exited) | No host runs. At the stop the plugin closes the host pipe; the host stops pushing, interrupts its active children (descendants first) and holds their ends, readable through `status` | `dsh/plugin.mjs`, `dsh/host.py` |
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

  One case stays open, because of how the `headless` runner leaves: a notice the
  relay admits after the runner's last idle check
  (`dsh-headless/lib/index.js:372`) and before its exit (`:383`) wakes a turn
  that the exit ends, and the notice is already `delivered`. A flush begins with
  the turn, so it reaches this window only when that whole turn ends before the
  relay answers. Upstream DSH is not changed for any of these.
- A grandchild's notices go to its own parent: a Claude parent Agent is
  continued with them; a Codex parent Agent is not notified, whatever the
  grandchild's Runtime, and reads them through `status`.
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

Gaps, by owner:

| Gap | Owner |
| --- | --- |
| A Pi follow-up acknowledged and then lost with its Pi process (*Pi host* above): Pi offers an extension no acknowledgement of persistence | Upstream Pi; not changed |
| A notice admitted while the `headless` DSH runner is exiting (*DSH host* above): the relay answers before the turn takes it | Upstream DSH; not changed |
| The notice title names GraphTraj | 394 |

### 4.1 Native approval per Runtime

agents uses each Runtime's own approval where it has one and never loosens
its sandbox, network or write limits. A request the Runtime asks about is held
for the direct parent as above.

| Runtime | How native approval is enabled | Configuration agents writes |
| --- | --- | --- |
| Claude Code | The supplied `permission_mode`; Claude's permission prompts arrive through `can_use_tool` | Passes the mode as `--permission-mode` and `permissions.defaultMode`; nothing else |
| Codex | `approvals_reviewer`, default `auto_review` (Codex's own reviewer decides) | Sets `approvals_reviewer = "auto_review"` when the settings name no reviewer, and `features.exec_permission_approvals = true`. `approval_policy`, sandbox, permissions and network stay as supplied |
| Pi | Pi has no approval of its own; extension dialogs (`extension_ui_request`) are the requests | None |
| DSH | The `permission` profile patch, approval `ask`, for the chosen sandbox mode | The `sandbox-policy` and `permission` patches; `dsh/approval-request` is the request |

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
unusable, the agents review plugin judges each tool call before it runs. Every
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
- `deny` and `escalate` refuse the call now and go to the direct parent, which
  may release it within its own authority. The root may refer it to a person.
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
  option.

The parent's own sandbox is not compared with the request; a parent should
decline what it could not do itself. The root may refer a request to a
person: the person answers in the root's own host (its native approval of
the root's `reply` call, or the conversation), and the root then replies.

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
- 381 (0.1.2): a Codex model mismatch at `thread/start`/`thread/resume` or a
  `model/rerouted` notification now ends the child `failed` with
  `RUNTIME_REQUEST_FAILED` under every host, GraphTraj included (section 2).
  A fix: the run used to continue on another model, contradicting the rule
  that a chosen value is never silently replaced.
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
- 403 (0.2.0): `last_result.notification` gains the value `held`, for a notice
  its parent cannot receive now, and `AgentControl` gains the optional
  `hold_notices` argument (default off, which writes nothing new) with
  `held_notices`, `settle_notice`, `settle_shown`, `notice_open` and
  `close_notices`. Compatible: a new value for a new situation, behind a new
  optional argument with a default that keeps current behaviour. All four hosts
  enable it, so `held` replaces `unavailable` for a notice they could not
  deliver; the Pi host also pushes each child request. The Pi and DSH hosts are
  themselves new in 0.2.0. The Claude Code and Codex hosts shipped in 0.1.2, so
  a consumer of theirs that reads `notification` sees the new value in 0.2.0,
  the minor version 384 already raised; 403 adds no bump of its own.
- 383: the DSH host section, the `agents-dsh` bundle, the `dsh` entries of the
  Claude Code and Codex hosts' `runtimes` and their DSH refusals are compatible
  additions. The agents DSH gate became a floor (0.2.0-rc.2 or later in semver
  order), which accepts more than before. They ship in 0.2.0; 383 adds no bump
  of its own.

While the major version is `0`, an incompatible change raises the minor
version (`0.1.x` → `0.2.0`), and compatible additions and fixes raise the
patch version. From `1.0.0` the usual rule applies: major for incompatible,
minor for additions, patch for fixes. A release that changes this document
updates it in the same change.

GraphTraj declares the range it supports (today `agent-swarm>=0.2.0,<0.3`, since the 0.2.0 archive version 5)
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
| — | Claude host plugin also handles GraphTraj's `tasks` tool (`mcp__agents__tasks`) | `claude/host_context.mjs` | unassigned, needs Main |
| — | Claude control-protocol hook IDs `graphtraj_start`, `graphtraj_collect_child`, `graphtraj_agents_display`, and the event key `graphtraj_direction` | `claude/execution.py`, `sessions/claude.py` | unassigned, needs Main (closest: 394) |
| — | GraphTraj imports internal modules and private names (`agent_swarm.control._scope`, `_alive`, `sessions.codex_values._timestamp`, and about 40 other internal modules) instead of only the names in 1.3. The version range does not protect these, because internal changes do not change the version | `src/graphtraj` (consumer side) | unassigned, needs Main |
| 11 | Plugin points and documentation examples that mention GraphTraj | `cli.py`, `config.py`, docstrings | kept by decision |
