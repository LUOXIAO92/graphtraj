# GraphTraj

GraphTraj coordinates Agent work in your own project. It tracks which tasks
need which results, runs the Agents you configure, and keeps the submitted
versions, decisions and execution history together.

Use it when work spans several tasks or Agents and you need to know what is
ready, what is still blocked, and which results have actually been accepted and
integrated. Research, documents, data and software can use the same workflow.
A task can have a single Agent; you choose the roles and methods.

## Get started

You need Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/)
for the installation below. Start with an existing Git repository that has a
commit and whose primary worktree is on `main`.

Choose a tag or commit to install, replacing `<tag-or-commit>`:

```sh
uv tool install --with "agent-swarm @ git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>#subdirectory=src/agent_swarm" \
  "git+https://github.com/LUOXIAO92/graphtraj.git@<tag-or-commit>"
cd /path/to/your-project
graphtraj setup
graphtraj doctor
graphtraj task graph
```

GraphTraj and `agent-swarm` are separate distributions built from the same
revision. GraphTraj requires the same `agent-swarm` version; install the two
matching artifacts together. From a checkout, build both with
`python -m pip wheel --no-deps -w dist ./src/agent_swarm .`, then install both
wheels in your dedicated environment. The independent distribution can also
be installed on its own from `./src/agent_swarm`.

Setup shows its plan and asks before creating the `dev` branch. It creates or
registers a separate worktree for integration and stores configuration and task
history under `.graphtraj/`. Your primary worktree stays on `main`. A new
project has no tasks or Agent roles yet, so its first graph is empty.

Running setup again preserves existing configuration and history. For a layout
with a separate source repository, or other project conventions, see the
[setup guide](manuals/setup-project/guide.md).

## Independent agents without GraphTraj

The `agent-swarm` distribution lets the Main Agent of a supported Runtime host
create and control child Agents through one `agents` tool. No GraphTraj
installation, project, Task or Git repository is needed.

### Install

`agent-swarm` is not published on PyPI. Build its wheel from a checkout, or use
a matching wheel you were given, and install it alone in a dedicated Python
3.12+ environment. Its only dependencies are PyYAML and websockets:

```sh
python -m pip wheel --no-deps -w dist ./src/agent_swarm   # in a checkout
python3 -m venv /absolute/agents-venv
/absolute/agents-venv/bin/python -m pip install dist/agent_swarm-0.1.0-py3-none-any.whl
/absolute/agents-venv/bin/agents --help
```

Run the `python -m agent_swarm...` commands below with this environment's
Python. Authenticate each Runtime separately; credentials are never copied.

### Host prerequisite

The `agents` CLI and the `agents-mcp` server only forward requests to the
Runtime host that owns the calling Agent. Started from a plain shell, or
registered by hand in another MCP client, every request, including `discover`,
returns `authority-denied`. Use one of the hosts below; each registers the
`agents` MCP entry itself.

An independent host runs children on its own Runtime with one fixed child
configuration from its settings file. `create` takes `runtime`, `instruction`
and an optional `name`; it rejects `configuration` with `invalid-config` and
does not accept a model or effort. `wait` requires `agent` and an explicit
finite `timeout_seconds` above 0.

### Independent Codex host

Authenticate Codex using its normal account setup. The installed host reuses
the same native execution implementation as GraphTraj. It runs one instruction
for a headless parent Agent:

```sh
python -m agent_swarm.codex.host --help
python -m agent_swarm.codex.host --settings native-settings.json \
  --directory /absolute/agent-state 'Use agents MCP to delegate a short question.'
```

`native-settings.json` supplies the existing native launch values. Replace the
model and absolute working path with your choices:

```json
{
  "adapter_request": {
    "arguments": ["codex"],
    "worktree_path": "/absolute/work",
    "session_parameters": {
      "cwd": "/absolute/work",
      "model": "your-selected-model",
      "developerInstructions": "",
      "config": {
        "default_permissions": "work",
        "permissions": {
          "work": {
            "extends": ":workspace",
            "filesystem": {":workspace_roots": {".": "write"}}
          }
        }
      }
    }
  }
}
```

The settings can also retain native provider/reasoning/network options in
`session_parameters.config`, and a `connection` with `runtime_home`, `base_url`
or `api_key_env` (an environment variable name, never its secret value).
Codex's native `auto_review` is the default; explicit native reviewer settings
win. Existing sandbox, account and trust controls remain effective.

The host owns the actual parent process and Session. It exposes only `agents`
through MCP, authenticating requests by process ancestry and the bound native
Session. Inside that same host, the authenticated CLI is also available:

```sh
python -m agent_swarm.cli '{"action":"discover"}'
```

CLI arguments cannot supply an identity. Child results return through the
owning native parent connection; status does not repeat a body already sent as
a notification. Native requests for the parent itself print to stderr and take
an explicit native JSON response on stdin. Use `--resume` with the same directory
to continue the retained parent Session. A closing host interrupts its active
children, preserving their native Sessions. Normalized archiving is off and
needs GraphTraj's collector. If `<directory>/config.yml` sets
`save_normalized_sessions: true`, the host refuses to start: it prints an
`archive-unavailable` error naming that file and setting and exits with status
1. Set it to `false` or delete the line.

### Independent Claude Code host

The wheel includes the native Claude host. In the working directory where you
will run Claude Code, write its adoption material:

```sh
python -m agent_swarm.claude.host configuration --project /absolute/working-directory \
  --claude "$(command -v claude)" --write
```

This writes `.mcp.json` (an `agents` server), `.agents-control/claude-host.json`,
the `env` entries in `.claude/settings.local.json`, and the plugin under
`.claude/skills/agents-claude-host/`. Start Claude Code normally in that
directory with the same `claude` executable, and approve its ordinary folder
trust and project MCP server prompts. The existing native mod supplies the
current Session identity for every `agents` MCP call; model arguments cannot
choose it. The host exposes progressive `discover`, `describe`, and `execute`
requests. `/agents-context` shows native binding and notice delivery. GraphTraj
users continue to use the GraphTraj host, which also exposes `tasks`.

The generated `.agents-control/claude-host.json` retains the native executable,
working directory and explicit child `settings`. Child permissions default to
Claude's native `auto` review; sandboxing and native permission replies remain
in force. Optional settings include `model` (default `claude-opus-5-5`),
`reasoning_effort`, `runtime_home`, `instructions`, `read_paths`,
`worktree_access`, `permission_mode`, `base_url` and `api_key_env` (an
environment variable name, never its value). These settings apply to every
child of the host; edit them before starting Claude Code. Existing login and
trust are not copied. Session continuation uses the original child's captured
settings. Normalized archiving is off and needs GraphTraj's collector; the host
refuses to start while `.agents-control/config.yml` sets
`save_normalized_sessions: true`. Set it to `false` or delete the line.

Start or resume Claude Code from the configured directory. When a startup check
fails (another directory, the archive setting above, an `agents` host already
running for the project, or a host not launched by the configured `claude`), the
`agents` server still connects but starts no control and no child. Every
`agents` call then returns that error, for example `host-unavailable: The agents
host did not start: Claude Code was started in <actual>, but this host is
configured for <expected>.` The same line is appended to
`.agents-control/host.log` and written to the server's stderr. Fix the cause, then
start Claude Code again from the configured directory. A child stopped because Claude switched its model
(for example a safeguard fallback) ends `failed` with `RUNTIME_REQUEST_FAILED`;
its `last_result.error` names the requested model, the observed model and the
Runtime's reason, or says that none was provided.

### Pi and DSH

The wheel contains Pi and DSH Runtime code, but neither has a documented
independent host. Pi's host (`agent_swarm.pi.host`, started by its extension)
currently needs a prepared launch request with GraphTraj Task fields, and there
is no independent DSH host. Use both through GraphTraj for now.

### Independent capabilities

Verified with only the `agent-swarm` 0.1.0 wheel installed. Pi and DSH have no
independent host (see above), so their rows are not available independently.

| Capability | Claude Code host | Codex host |
| --- | --- | --- |
| Attach as host | Yes, as above; `/agents-context` shows the binding | Yes; a headless parent runs one instruction per invocation |
| `create`, `status`, `wait`, `send`, `interrupt`, `resume`, `retire` | Yes; `resume` continues the same child Session | Yes; `resume` continues the same child Session |
| Choose the child Runtime | Only `claude`; `codex` returns `unsupported-runtime` | Only `codex`; `claude` returns `unsupported-runtime` |
| Choose model or effort per child | No; one setting for all children, and a `model` argument is rejected | No; one setting for all children, and `configuration` returns `invalid-config` |
| Completion notice to the Main | Yes: pushed into the Main Session, or attached as `main_notices` to the next `agents` result. Known defect: a completion already returned by `wait` can be pushed again | Yes: each completion is sent once to the parent Session as a host event |
| Relay a child's native approval request | Yes, by polling: `wait` or `status` shows `pending_requests`, then `requests` and `reply` | No: native `auto_review` handles children's requests, and the parent shares the same settings |
| Native history | Child native Sessions are retained under `.agents-control/native/` and continued by `resume` | `--resume` continues the parent Session with its children |
| Normalized archive | No: with `save_normalized_sessions` on, every `agents` call returns `archive-unavailable` naming the setting | No: with `save_normalized_sessions` on, the host exits with `archive-unavailable` naming the setting |
| Children on another Runtime | No | No |

## Use it with your Agent

Your main Agent runs in the host you already use. To delegate work, install and
authenticate the chosen Agent Runtime separately; GraphTraj does not supply
model credentials or change your host's global settings.

For a first Codex child Agent, add this preset to `.graphtraj/roles.yml`, replacing
`your-selected-model` with a model available to your Codex installation:

```yaml
roles:
  researcher:
    runtime: codex
    model: your-selected-model
    worktree_access: write
role_tree:
  researcher: {}
```

Merge it into existing configuration if the file already contains roles.
`role_tree` allows this role to receive work directly from your main Agent; an
empty child mapping gives it no further dispatch roles. Run `graphtraj doctor`
after editing. Optional `instructions` can point to your own UTF-8 role file.
Keep credentials in the Runtime's native configuration or an environment
variable named by `api_key_env`.

To share models and providers across projects, use `graphtraj connections`.
Project roles can reference this user-level catalog while login stays in the
original Runtime. See [shared connections](manuals/setup-project/guide.md#share-runtime-connections-across-projects).

Your host must expose the `graphtraj` tool. If it supports MCP, register
`graphtraj-mcp` as a stdio server with the project root as its working directory.
For hosts using TOML MCP configuration:

```toml
[mcp_servers.graphtraj]
command = "graphtraj-mcp"
args = []
cwd = "/absolute/path/to/your-project"
```

Use your host's normal configuration and trust controls, and open or reload the
session as that host requires. The optional [GraphTraj Skill](skills/graphtraj/SKILL.md)
introduces the workflow; installing a Skill alone does not register the tool.

With the tool available, start from a task you have agreed to do, for example:

> Use GraphTraj to register and deliver this research task: [agreed scope].
> Use the researcher role, retain the sources with the document, and show me
> the result and any remaining work.

The [task delivery guide](manuals/task-delivery/guide.md) covers registration,
dispatch, result decisions and integration. The tool can describe each operation
and its inputs when needed. Tasks belong to your local project and have stable
local IDs. Provide the accepted scope and completion criteria; a GitHub Issue
URL can be a source reference, but is not required or used as the task's identity.

## How work progresses

1. **Define the work.** Register tasks with completion criteria
   and dependencies on the results they need.
2. **Run ready tasks.** Configured Agents work in Task worktrees. Independent
   tasks can run in parallel within the project's concurrency and budget limits.
3. **Assess the result.** An Agent submits a committed version and evidence;
   its authorized parent accepts it or requests a correction. An Agent finishing
   its turn does not by itself complete the task.
4. **Integrate.** Accepted results are merged and validated in `dev`. Successful
   integration satisfies dependencies and makes subsequent work ready.

GraphTraj retains the original inputs, reports, native Session records and
project event history so work can be inspected or continued. Your project
chooses who validates and accepts results; a coding team or review process is
not required for every kind of work.

These commands give you an overview from the project root:

```sh
graphtraj task graph      # Open work with folded history
agent-runner status      # Agent tree and current activity
graphtraj worldline read # Recorded project events
```

Use `--view full` to list every Task, `--task-id <id>` to select a scope,
or `--details <id>` to include definitions and execution facts.

For direct CLI use, start with `graphtraj --help` and `agent-runner --help`.
Individual command help includes its input schema; the
[command input reference](manuals/task-delivery/references/command-inputs.md)
explains the files used for registration, result decisions and integration.

## Runtimes and host integration

Child Agents can use different Runtimes without changing your main Agent's host.

| Runtime | Preparation and limits |
| --- | --- |
| Codex (`codex`) | An installed, authenticated Codex CLI. Native permissions and approvals remain in effect. |
| Claude Code (`claude`) | Official CLI 2.1.299 or later, authenticated separately. Uses structured CLI input/output, native permission prompts and mandatory native sandboxing. Finds `claude` on PATH or `~/.local/bin/claude`. |
| Pi (`pi`) | An installed Pi backend, existing Pi configuration, and an `asb` sandbox with `srt`. The role's optional `pi.sandbox_python`, `pi.sandbox_path` and `pi.agent_dir` select those locations. |
| DeepSeek Harness (`dsh`) | DSH `0.2.0-rc.2` for child members and a host that supports its native subprocess sandbox. Start DSH with `DEEPSEEK_BASE_URL` unset (`env -u DEEPSEEK_BASE_URL dsh ...`), as in the verified runs. Native replacement and recovery approval routes are unavailable; its native file tools can read outside the task worktree. |

For Claude Code, select the exact model `claude-opus-5-5` and
`reasoning_effort: high` in a role, or save an explicit model entry through
`graphtraj connections` and reference it from `graphtraj roles organize`.
Discovery returns native catalog metadata; it does not test account access.
Claude's `opus` alias is not a version pin. Other model IDs require an explicit
connection; GraphTraj does not substitute a model or effort.

Claude child execution uses restricted mode, the native sandbox with
`failIfUnavailable` and no unsandboxed retry, and native permission
responses through Runner `requests` / `reply`. A reply uses Claude's
`behavior: allow` or `behavior: deny` shape. The native permission and filesystem
checks still apply. `claude.read_paths` may list explicit external read-only
resources. Assigned reports use the hosted `submit_report` tool, without granting
write access to private state. User settings and other MCP servers are excluded
from these restricted child launches; managed settings remain effective. The
captured Context records these sources, model, effort, CLI version and paths.

Set `claude: {permission_mode: default}` for manual tool approval or
`claude: {permission_mode: auto}` for Claude's native tool classifier. Explicit
choices are retained on resume. When omitted, Runner supplies no permission-mode
flag or `defaultMode`: Claude selects from managed settings and its native
restricted-session defaults, including its native resume behavior. This does
**not** inherit user, project or local settings, which `--restricted` excludes;
represent a desired choice explicitly in the role instead of changing global
settings. Sandbox and file restrictions remain the same in either mode.
Runner `reports` distinguishes requested mode, its source and the mode reported
by native initialization; missing observations are `unknown`, and a fallback is
not evidence that auto became active. Native auto availability depends on Claude
policy and service support. Tool auto approval does not approve GraphTraj budget
recovery; recovery still requires the calling parent's selected reviewer.

Runner retains the native Session on continuation, checks registration before
releasing the first prompt, and distinguishes an interrupt request from verified
termination. Native helpers and background tasks are disabled for these children.
Managed output and supported native Main hook records are collected into
[project-local Session archives](examples/sessions/README.md#claude-collection).
Collection does not install hooks or migrate existing history. Claude's native
replacement approval route is explicitly unavailable. Unknown approval
capability fails closed.

### Continuing Main from any Runtime

A project has one Main working state: the Main-owned root Agents and their
hierarchy, pending notices and results, and the current summary scope. Each
verified external Main Session, whether Codex, Claude Code, Pi or DSH, continues
that state, so default `agents` status and `tasks` views show the existing members
rather than an empty list. Continuation is a new associated record in
`.graphtraj/runner/main-sessions/continuity.jsonl`; original Sessions, member
identities and parents stay unchanged. Native subagents, GraphTraj members and
completion checkers never become Main.

Main is the one central dispatcher. A Main takes control at its native entry:
a Codex `SessionStart` (startup, resume or clear), a Pi `session_start`
(startup, new or resume) or a DSH `agent/created`; compaction, Pi `reload` and
`fork` are not entries. Claude Code takes control at the first control call of
each host process. Reads never take control. When another Main has continued
the project, the earlier Session can still read status, but its control calls
fail with `main-continued` naming the current Main. To continue Main there,
start or resume it through its native entry; a Claude Code Session needs a new
Claude Code process. Member events and results go to the current Main. A Codex
Main receives them as host events; a Claude Code, Pi or DSH Main finds them in the
project's durable notice queue, which its host integration delivers into the Main
Session (the Pi extension as a custom message, the DSH plugin through the native
inbox, within about five seconds) and acknowledges only after delivery.

### Claude Code as Main

The Claude Code host serves both `agents` and `tasks` from one project MCP
server, with the same Agent view and control as a Codex Main (every Runtime,
Task member Sessions) and Main authority for Task operations. A Claude Code
plugin supplies each call's native Session. Print, or with `--write` write, the
adoption material from the GraphTraj installation:

```bash
python -m graphtraj.runtimes.claude.host configuration --write \
  --project /path/to/project --claude "$(command -v claude)"
```

It produces:

- `.graphtraj/claude-host/config.json`: the host configuration naming the
  Claude CLI that must launch the host directly;
- `.mcp.json`: one `agents` server serving both tools (replace earlier
  hand-made `graphtraj`/`agents` entries for this host);
- `.claude/settings.local.json` `env`: `GRAPHTRAJ_CLAUDE_HOST_PYTHON` and
  `GRAPHTRAJ_CLAUDE_HOST_CONFIG`;
- the plugin `.claude/skills/graphtraj-claude-host/`, which Claude Code loads
  at session start: `.claude-plugin/plugin.json`, `hooks/hooks.json`
  (`{"modules": ["./host_context.mjs"]}`) and `hooks/host_context.mjs`.

Check it with `claude plugin validate .claude/skills/graphtraj-claude-host`;
`claude --plugin-dir <dir>` loads it for a temporary session. Claude Code's own
project MCP approval and trust prompts decide adoption; GraphTraj trusts nothing
itself. In a session, `/agents-context` shows the current Session, whether the
`agents` and `tasks` entries are registered, and whether notice push is available.

Member notices for this Main are appended to a durable per-Session queue in
`.graphtraj/runner/main-sessions/inbox/`. The plugin submits them into the
Main's turn or idle Session through Claude Code's prompt submission and
acknowledges them only afterwards; until then they are also returned with the
next `agents`/`tasks` result. Without prompt submission they arrive only with
that next result.

The execution host needs access to the chosen Runtime executable, credentials,
project files and subprocess sandbox. Role permissions do not replace the
Runtime's filesystem restrictions.

On macOS, `pi.allow_mach_lookup` and `pi.allow_mach_register` separately allow
service lookup and registration when supported by the sandbox runtime. Entries
can be exact names or narrowly scoped trailing-`*` prefixes. The optional
`pi.allow_local_binding` can allow binding and inbound connections on all local
interfaces and ports. These grants apply to the Pi Runtime and its subprocesses;
they are off by default and do not change filesystem rules.
`pi.allow_unix_sockets` allows socket binding and connections beneath the listed
paths on macOS; it grants no file access and adds no permissions when omitted.

Use the CLI or local stdio MCP entries `agents` and `tasks`. MCP discovers
features first and returns a selected feature's schema only when requested.
When several roles in the project use the same Runtime, `agents` `create` must
name the role in `configuration`. `wait` takes `agent` and an explicit finite
`timeout_seconds`.
The `graphtraj-tool` JSON-lines process is an internal host bridge for the
desktop and event delivery, not another model tool. CLI or MCP access alone
does not connect background events or
completion hooks to an existing conversation; those require integration with
the host that owns the session. See
[completion checking](manuals/task-delivery/guide.md#main-completion-checking)
and [recovery](manuals/task-delivery/references/recovery.md).

GraphTraj currently manages one source repository per project. It does not
provide a job queue, automatic crash recovery, or automatic promotion from
`dev` to `main`.

## Optional desktop

The app in [desktop/](desktop/) offers a project graph, recorded
Agent activity, a usage dashboard, shared model connections and project team
configuration.
Select a task and expand chat to read its Agents in parallel columns. Each column
scrolls independently; the bottom scrollbar reaches offscreen Agents. Hide the
sidebar for more room, expand tool results, copy text or pause following new
activity. Returning from another page preserves your reading position.
The project list is stored in `~/.graphtraj/projects.json`; removing an entry
leaves its project files intact. Unavailable records remain explicitly unknown.
The CLI works without
Node or Electron; the desktop is an optional monitoring and configuration window.
It does not provide task execution controls.

For Apple Silicon macOS, extract the ZIP and open `GraphTraj.app` from the
extracted folder to try it; copying it to `/Applications` is optional. Electron
is included, but Python is separate. Install the accompanying GraphTraj and
agent-swarm wheels in a Python environment, and make `graphtraj-tool` available on the app's
launch `PATH` or set `GRAPHTRAJ_TOOL` to that executable. Use the matching CLI
package rather than an older global installation. The macOS build is unsigned.

For the Windows x64 ZIP, install Git, extract the archive, and run
`.\Install-GraphTraj.ps1` from its folder in PowerShell. Then open GraphTraj from
the Start menu and add an existing project. The installer copies the app to
`%LOCALAPPDATA%\Programs\GraphTraj`; Python and Electron are included, so the
extracted archive is no longer needed after installation. Desktop support does
not add Windows execution support to Agent Runtimes that lack it.

On Ubuntu 24.04 amd64, install the package with
`sudo apt install ./graphtraj-desktop_0.1.0_amd64.deb`, then run
`graphtraj-desktop`. The app and its matching Python environment are installed
under `/opt/graphtraj-desktop`.

Open **Global usage** to compare projects, or **Project usage** to filter the
selected project's records by task, Agent or model. Choose a start and end date;
the default covers today and the preceding six local calendar days. Normalized
history is saved under `~/.graphtraj/usage-history` and survives reopening the
app. It contains usage facts, not copies of conversations.

Cache-hit rates are weighted by input tokens. Missing usage—including unrecorded
Main calls—and quantities without a known price stay visible. Date totals exclude
records whose time is unknown; totals cover only the available records.

Cost estimates use bundled prices from the original model vendor, in USD per
million tokens. They are not provider bills, especially for third-party routes.
When historical prices cannot be established, the app labels the estimate as a
current-rate approximation. Unsupported models or unresolved pricing conditions
remain unpriced. The snapshot's official sources are [OpenAI pricing](https://developers.openai.com/api/docs/pricing),
[Astra context rates](https://developers.openai.com/api/docs/models/gpt-6-astra),
[OpenAI cache accounting](https://developers.openai.com/api/docs/guides/prompt-caching)
and [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/).

Open **Settings → Agents & models** to manage Runtime Homes, providers and
models. Refresh models through the Runtime's public interface or add a manual
connection; API keys are referenced by environment variable name only. Login
stays in the original Runtime, and discovering a model does not establish
account access. If discovery is unavailable, follow the displayed client setup
guidance rather than entering credentials into GraphTraj.

Open **Teams & roles** for the selected project to add or rename teams, connect
Agent nodes, select shared models and edit instructions. When deleting a node,
choose whether to remove its branch or reconnect its children; an empty team
can be rebuilt with a new root. Both settings pages provide **Save** to persist
changes once and **Cancel** to discard unsaved edits. Invalid input, write
failures and external changes leave the saved configuration intact and show
the reason; reload to resolve an external change. Agent-initiated configuration
changes still require their existing native authorization. Effort choices use
saved model capabilities when available; otherwise they show the native Runtime
configuration values, with model support explicitly unreported. Reselecting a
model retains its effort. These settings apply to future dispatch; editing them does not stop running Agents.

To run it from a source checkout, install the matching Python GraphTraj version
and make `graphtraj-tool` available on `PATH` (or set `GRAPHTRAJ_TOOL` to its
executable). With Node 22.18+ and a graphical desktop session:

```sh
cd desktop
npm ci
npm exec -- install-electron
npm start
```

Choose **Add project** and select an existing GraphTraj project root. Removing
an entry removes it from the app's list; it does not delete the project.
You can also launch with `npm start -- --project=/absolute/project/path` to
validate and select a project directly. Without it, the saved selection is used.

## More documentation

- [Project setup](manuals/setup-project/guide.md): paths, tracking and resources.
- [Task breakdown](manuals/task-breakdown/guide.md): scope, dependencies and work sizing.
- [Task delivery](manuals/task-delivery/guide.md): execution through integration.
- [Recovery](manuals/task-delivery/references/recovery.md): interruptions, failures and continuation.
- [Research](manuals/research/guide.md) and [concept clarification](manuals/concept-clarification/guide.md): optional methods for your project.
- [Coding Skill examples](examples/coding-skills/README.md): optional development methods, separate from the Runtime installation.
