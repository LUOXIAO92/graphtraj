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
| `create` | `runtime*`, `instruction*`, `name`, `configuration`, `extra_fields` (object, section 5) | none; returns once the Agent is registered, never waits for its work |
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

**Result document** of `execute`:

```json
{"action": "...", "agent": "...", "session": "...", "execution": "...",
 "message": null, "result": {"...": "..."}}
```

`agent`, `session` and `execution` are stable references or `null`.
`result` is the **Agent document** plus the feature's own fields:

- `agent`, `name`, `runtime`, `state` (`active` or `standby`), `parent`,
  `creator` (`host`, `agent`, `session`), `host`, `session`;
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
| `invalid-config` | rejected driver configuration (today: any `configuration` in an independent host) |
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

Known inconsistency: envelope validation errors in `discover`/`describe`/
`execute` currently return `{"error": "<text>"}` without a code. Unassigned,
needs Main.

### 1.3 Python names

Public: `agent_swarm.__version__` and the names in `agent_swarm.__all__`:

- the tool: `TOOL_NAME`, `INPUT_SCHEMA`, `ACTION_FIELDS`, `tool_descriptor`,
  `validate_request`, `bind`, `unavailable`, `AgentsError`, `AgentsResult`,
  `Caller`, `Binding`, `Backend`, `Outcome`, `SessionArchive`;
- the backend: `AgentControl`, `RuntimeDriver`, `Run`, `ExecutionEvents`,
  `ACTIVE`, `STANDBY`;
- configuration: `CONFIG_DEFAULTS`, `default_config`, `explicit_choices`,
  `read_config`, `write_config`;
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

## 2. Creating a child: Runtime, preset, model, reasoning effort

**Today.** `create` takes `runtime`, `instruction`, optional `name` and
`configuration`. An independent host has one driver, so another Runtime
returns `unsupported-runtime`. Its children all use the host's fixed settings:
`configuration` returns `invalid-config`, and `model` or effort arguments are
rejected as unknown fields.

**Planned (380).** `create` keeps `runtime` and gains optional `preset`,
`model` and `reasoning_effort` (strings).

- A Runtime with no configured connection, a preset not in `config.yml`, a
  model not among the Runtime's candidates (from configuration or the list
  obtained at login) or an effort the model does not support is an explicit
  error with a stable code naming that field. A value is never silently
  replaced by another one.
- The precedence between a preset and explicit arguments, and whether
  `runtime` may be omitted when a preset names one, are decided by 380.
  Contradicting values are an error, never a silent choice.
- When the Runtime answers with a different model than requested (for example
  a safeguard fallback), the child's result names the requested model, the
  observed model and the Runtime's reason, as 369 does for Claude today.
  381 carries this to every host and Runtime.
- The Agent document reports the effective Runtime and model choice (field
  names decided by 380).

## 3. Standalone configuration: `<data root>/config.yml`

**Today.** Two booleans, `save_normalized_sessions` and `backfill_history`,
both default `false`. Blank lines and comments are allowed. Any other field,
a repeated field or a non-boolean value is refused, not guessed.

With `save_normalized_sessions: true`, every execution of every Runtime
(Claude, Codex, Pi, DSH) in any host writes its normalized Session to
`<data root>/sessions/<sha256 of id>/session.jsonl`; no host refuses the
setting. Switching it to `false` stops saving for later executions and keeps
the archives already written. An execution that cannot archive fails with its
own cause. Header `extra_fields` come from `create`'s `extra_fields`
argument, not from this file.

**Planned (380).** The same file declares:

- **Runtime connections:** named entries saying which Runtime they run
  (`claude`, `codex`, `pi`, `dsh`) and how to reach it (for example a native
  home, base URL, or the name of an environment variable holding a key, never
  the key itself);
- **presets:** named entries giving a connection or Runtime, a model and a
  reasoning effort, selectable by `create`'s `preset`.

The exact keys are 380's. Reading stays strict: unknown fields fail with the
file and line. agents reads only its own `config.yml` and native Runtime
login state; it never reads GraphTraj's `roles.yml` or any other product's
configuration. GraphTraj passes its roles to agents through `create`'s public
arguments and this file.

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
- `event` is `completed`, `interrupted` or `failed`; `message` is the child's
  answer, else the error message, else the outcome.

Gaps, by owner:

| Gap | Owner |
| --- | --- |
| Independent hosts do not push a child's native permission request; the parent polls | 381 |
| Codex children's native approvals are handled by `auto_review` and not relayed to the parent | 385 |
| Independent hosts do not hold notices while the parent is stopped: the Claude host's queue lives in its process, and the Codex host marks them `unavailable` (readable through `status`) | 381 (Claude, Codex), 382 (Pi), 383 (DSH) |
| A child cannot ask its parent for a decision or more resources except through native approval requests | unassigned, needs Main (closest: 381) |
| The notice title names GraphTraj | 394 |

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
| 3 | Completion checker profile `graphtraj_checker` and its permission override | `codex/app_server.py` (`CHECKER_PERMISSION_PROFILE`) | 388 |
| 3 | Pi completion checker entry `graphtraj:completion-checker` | `pi/session.py` | 388 (behaviour), 394 (name) |
| 4 | `GRAPHTRAJ_*` variables: `GRAPHTRAJ_CLI_CONNECTION`, `GRAPHTRAJ_NATIVE_RUNTIME`, `GRAPHTRAJ_NATIVE_SESSION`, `GRAPHTRAJ_NATIVE_SESSION_FILE`, `GRAPHTRAJ_CLAUDE_HOST_PYTHON`, `GRAPHTRAJ_CLAUDE_HOST_CONFIG`, `GRAPHTRAJ_DSH_PACKAGE` | `connection.py`, `claude/host.py`, `claude/host_context.mjs`, `claude/execution.py`, `codex/managed_session.py`, `pi/extension.mjs`, `pi/session.py`, `pi/host.py`, `pi/execution.py`, `dsh/plugin.mjs`, `dsh/execution.py` | 394 |
| 4 | Host exclusion check refusing both the independent and the GraphTraj connection | `connection.py` (`call_owner`), `claude/host.py` (`serve`), `pi/extension.mjs` | 388 |
| 5 | Archive header extension `graphtraj` with `projectId`, `agentId`, `taskIds` | Done in 384: agents writes no product fields; GraphTraj passes `extra_fields.graphtraj`. The `graphtraj` name remains only in the version 4 reader (`sessions/protocol.py`, `LEGACY_*`) | 384 |
| 5+ | Core archive facts kept under the `graphtraj` name (event provenance, missing facts, header continuation, `graphtraj/*` types) | Done in 384: product-neutral core fields and types (section 1.5) | 384 |
| 6 | Pi custom message type `graphtraj:agent-communication` | `pi/extension.mjs` | 394 |
| 7 | Pi execution's GraphTraj Task fields and fixed `.graphtraj` deny-read and deny-write paths | `pi/execution.py`, `pi/host.py` | 382 |
| 8 | No independent DSH host | `dsh/` | 383 |
| 9 | Notice title `GraphTraj notice from …` and default sender `graphtraj` | `claude/host_context.mjs` | 394 |
| 10 | `send`'s `reports_only` and its "Task member" description | `tool.py` (`ACTION_FIELDS`, `INPUT_SCHEMA`) | 388 |
| 12 | Archiving refused without GraphTraj's collector | Done in 384: the refusal is removed; each Runtime execution builds its own collector from the bound archive (`claude/execution.py`, `claude/collection.py`, `codex/managed_session.py`, `pi/execution.py`, `dsh/driver.py`) | 384 |
| — | Claude host plugin also handles GraphTraj's `tasks` tool (`mcp__agents__tasks`) | `claude/host_context.mjs` | unassigned, needs Main |
| — | Claude control-protocol hook IDs `graphtraj_start`, `graphtraj_collect_child`, `graphtraj_agents_display`, and the event key `graphtraj_direction` | `claude/execution.py`, `sessions/claude.py` | unassigned, needs Main (closest: 394) |
| — | GraphTraj imports internal modules and private names (`agent_swarm.control._scope`, `_alive`, `sessions.codex_values._timestamp`, and about 40 other internal modules) instead of only the names in 1.3. The version range does not protect these, because internal changes do not change the version | `src/graphtraj` (consumer side) | unassigned, needs Main |
| 11 | Plugin points and documentation examples that mention GraphTraj | `cli.py`, `config.py`, docstrings | kept by decision |
