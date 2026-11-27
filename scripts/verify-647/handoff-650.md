# Task 647 → Task 650: the Claude Code host on real Windows

Task 647 (W8 + W9) changed graftling at candidate `bbcea6d9` (bundle `graftling-647.bundle`, base dev
`eb5ad8e`). It was checked on a GitHub-hosted Windows runner with a stand-in Claude Code only
(`steps.zsh`, P). This note lists what Task 650 must observe with the real Claude Code on native
Windows, what each observation looks like when it passes and when it fails, the Claude Code settings an
Anthropic-compatible endpoint needs (names only), and what is still an inference.

No value of any setting, no provider, endpoint, cloud platform, account, address or machine size is
written here (AGENTS.md). Main passes the concrete endpoint and values to Task 650 through local settings.

## 1. What 647 shipped for Windows

| Area | Behaviour at `bbcea6d9` |
| --- | --- |
| Hosting route | The plugin files that `python -m graftling.claude.host configuration --project <dir> --claude <claude.exe> --write` generates. The marketplace plugin is not supported on native Windows (decision recorded by the Leader and Main, definition 20261127T192242). |
| `.mcp.json` from a venv | `command` = the venv's base interpreter (`sys._base_executable`), `env` = `{"__PYVENV_LAUNCHER__": "<venv>\\Scripts\\python.exe"}`, `args` = `-m graftling.claude.host serve --config <...>\\claude-host.json`. Outside a venv, and on POSIX, `command` is `sys.executable` and there is no `env` (unchanged). |
| Mod context call | On Windows, when `GRAFTLING_CLAUDE_HOST_PYTHON` is a venv python (a `pyvenv.cfg` one directory above it), the mod starts `<home>\python.exe -I -c <bootstrap> <venv> context --config <...>`, where `home` is read from `pyvenv.cfg`. It refuses with one line when `pyvenv.cfg` names no existing base interpreter. |
| Parent rules | Unchanged rule: the host's parent, and the parent of every per-call context process, must be the configured Claude Code executable. On Windows the parent is the recorded parent PID only when that process was created earlier (633); no launcher hop is accepted. |
| Session end | The host ends at stdin EOF, removes `channel.json`, stops and records what it owns, and exits 0. |
| Claude child | `create` (and a resume or `send` that would start one) fails with `unsupported-runtime` on native Windows, before any setting is built or process started. No switch. |
| Marketplace launcher | Under a Windows `sh` (Git Bash, MSYS, Cygwin) `bin/graftling-host` prints one line naming `configuration --write` on stderr and in `host.log`, and exits 1 without starting Python. Without a `sh`, Claude Code's own start failure is all there is. |

M5 (Claude Code's permission-rule syntax for Windows paths) and M14 (Claude child process starts) are not
reached while Claude children are refused; they are not applicable in this round.

## 2. Setup the observations assume

1. graftling installed as the README says (`uv tool install --managed-python ...`). The venv python is
   `<uv tool dir>\graftling\Scripts\python.exe` (call it `VENVPY`).
2. Claude Code from the native installer, so the process is `claude.exe` (graftling's default is
   `%USERPROFILE%\.local\bin\claude.exe`, M11). Pass that exact path as `--claude`.
3. In the project directory: `& $VENVPY -m graftling.claude.host configuration --project <dir> --claude <claude.exe> --write`,
   then start Claude Code from `<dir>`. Keep the printed file list and the written `.mcp.json`.
4. Claude Code reaches the endpoint Main names through the settings in section 4.

## 3. Observations

Each row: what to do, the observable that proves it, and what a failure looks like. "host.log" is
`<dir>\.agents-control\host.log`; "channel" is `<dir>\.agents-control\live\channel.json`.

| # | Observation | Pass looks like | Fail looks like |
| --- | --- | --- | --- |
| O1 | Process shape of the MCP server's parent: does Claude Code start the `.mcp.json` stdio server directly? | `/mcp` lists `graftling` connected; host.log has no `did not start` line; `channel.json` `parent` equals the PID of `claude.exe`; `Get-CimInstance Win32_Process -Filter "ProcessId=<host pid>"` shows `ParentProcessId` = that PID and `ExecutablePath` = the base `python.exe` (not `Scripts\python.exe`). | host.log / `/mcp` stderr: `The subagents host did not start: This host must be launched directly by the selected Claude CLI. {"expected_executable": ..., "observed_executable": ..., "parent_pid": ..., "stage": "serve"}`. `observed_executable` names the wrapper (for example `cmd.exe`, `bash.exe`, `node.exe` or `Scripts\python.exe`): record it; the rule fails closed. |
| O2 | Does Claude Code pass the `.mcp.json` `env` to the server? | Same as O1 pass (the base interpreter imports graftling only through `__PYVENV_LAUNCHER__`). | `/mcp` shows the server failed with `No module named graftling` (or `graftling.claude`) in its stderr. |
| O3 | Direct-child rule from Claude Code's own mod: the per-call context process. | The first `subagents` call (for example `discover`) is allowed and answered; host.log has its `subagents-call ...` lines and no `authority-denied`. Optional: a process-creation trace shows the context process `<home>\python.exe -I -c ...` with `ParentProcessId` = `claude.exe`. | The call is denied with `Native agents association failed: ...` and, in that text, `launched directly by the selected Claude CLI` with `"stage": "context"`, or `The sender is not owned by this native Claude host.`; or `graftling: ...pyvenv.cfg names no base interpreter ...`. |
| O4 | Direct-child rule from a Bash-tool (or PowerShell-tool) caller. | In Claude Code's Bash or PowerShell tool run `& <base python.exe> -I -c "<the mod's bootstrap>" <venv> context --config <...>` with a `prepare` document on stdin, or simply `& $VENVPY -m graftling.claude.host context --config <...>`: exit 1 with `launched directly by the selected Claude CLI` and `observed_executable` = the shell (`bash.exe`, `sh.exe`, `pwsh.exe` or `powershell.exe`) or `Scripts\python.exe`. The `subagents` CLI typed there fails with `authority-denied` (no owner), as on POSIX. | Exit 0 with `{"prepared": true}`: a tool command passed as Claude Code's direct child. Stop and report. |
| O5 | Session end (`/exit`, closing the terminal window). Claude Code's documented Windows stop: it closes the server's stdin, then ends the server's process tree if it is still running 300 ms later (mcp.md, "How Claude Code stops a stdio server"; Claude Code 2.1.296 or later). | host.log ends with `subagents host recorded its children stopped.`; `channel.json` is gone; no host `python.exe` remains. Record the Claude Code version. | `channel.json` remains (the host was ended before it finished): the next start logs `subagents host replaced a stale channel of a dead host`. Record which happened; with no children the host normally finishes well within 300 ms (inference). |
| O6 | Claude child refusal on the Windows host. | `subagents` `create` with `runtime: "claude"` returns `error.code` `unsupported-runtime` and the message `A Claude child cannot run on native Windows: Claude Code has no OS sandbox there ("On native Windows, Claude Code runs commands unsandboxed"), and graftling runs Claude children only inside that mandatory sandbox, without a bypass. ...`; no Agent is listed by `status`. | Any Claude process started for a child, or another code. |
| O7 | `failIfUnavailable` and rule syntax. | Not exercised: no Claude child starts (O6). Claude Code documents that with `sandbox.failIfUnavailable` it exits at startup on native Windows (sandboxing.md), which is why the child stays refused. | — |
| O8 | Probe (decides nothing in 650): does `${VAR:-default}` expand in a plugin `mcpServers` `command` on real Windows? Make a throwaway local plugin directory with `.claude-plugin/plugin.json` holding one server `probe647` with `"command": "${PROBE_647_PYTHON:-C:/probe-647-default.exe}"` and `"args": ["-m", "graftling.mcp"]`; set `PROBE_647_PYTHON` to `VENVPY` in the shell; start `claude --plugin-dir <that directory>`. | `/mcp` shows `probe647` connected (the variable expanded and was visible). | `/mcp` shows `probe647` failed and names `C:/probe-647-default.exe` (expansion works, the variable was not seen) or the literal `${PROBE_647_PYTHON:-...}` (no expansion in a plugin `command`). Record the text exactly. |
| O9 | How the marketplace plugin fails on native Windows. With the marketplace added and the plugin enabled for a second project (not the one of O1-O6). | With a `sh` on Claude Code's `PATH`: `/mcp` stderr and that project's host.log hold `graftling plugin: the subagents host did not start: the graftling marketplace plugin is not supported on native Windows. ... configuration --write ...`. Without one: Claude Code's own start failure for `sh`. Record which. | A host that starts from the marketplace plugin. |

## 4. Claude Code settings for the user's Anthropic-compatible endpoint (names only)

Set under `env` in `%USERPROFILE%\.claude\settings.json`, or as environment variables of the shell that
starts Claude Code (llm-gateway-connect.md, "Set the base URL and credential"). Values come from Main's
local settings and stay on the VM.

| Variable | Use | Source |
| --- | --- | --- |
| `ANTHROPIC_BASE_URL` | The endpoint's base URL | env-vars.md; llm-gateway-connect.md |
| `ANTHROPIC_AUTH_TOKEN` | The credential when the endpoint takes `Authorization: Bearer` (the default the guide suggests) | env-vars.md; llm-gateway-connect.md, "Set the credential variable" |
| `ANTHROPIC_API_KEY` | Instead of the above, when the endpoint takes `x-api-key` | same |
| `ANTHROPIC_MODEL` | The model the session uses | env-vars.md; model-config.md |
| `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` | What the `sonnet`, `opus` and `haiku` aliases resolve to (Haiku also for background work) | env-vars.md |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Default model of Claude Code's own subagents | env-vars.md |
| `API_TIMEOUT_MS` | Optional: longer response-header wait for a slow endpoint | env-vars.md |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | Optional: no auto-update, telemetry or error reporting | env-vars.md |
| `CLAUDE_CODE_GIT_BASH_PATH` | Optional, Windows only: where Git Bash is when Claude Code does not find it | env-vars.md; setup.md |

The documents are Claude Code's own, at `https://code.claude.com/docs/en/<page>` (fetched 2026-11-27).
llm-gateway-connect.md says that with `ANTHROPIC_AUTH_TOKEN` the variable takes precedence over a saved
login at once; with `ANTHROPIC_API_KEY` Claude Code asks first. The host inherits Claude Code's
environment, so these variables reach the graftling host process too; graftling neither logs nor uses them
for the host, and starts no Claude child on Windows.

## 5. Still inferences (to confirm or refute in 650)

1. uv's tool venv uses CPython's venv launcher for `Scripts\python.exe` (that a stdlib venv does is a fact:
   CPython `venv`; the runner test shows the launcher starting a child). The 650 VM uses the uv install.
2. Claude Code starts a `.mcp.json` stdio server directly, as hooks' exec form does (hooks.md: exec form on
   Windows needs a real `.exe` and uses no shell), and passes that server's `env`. Not stated for MCP servers.
3. The mods API `$.process.run` (no shell, plugins/mods/api.md) starts its program as a direct child of
   `claude.exe`, with no helper process between.
4. The native installer's process image is `claude.exe` at the path given as `--claude`. A Claude Code
   started through npm runs as `node.exe`; its hosts would be refused at O1 (fail closed).
5. A base `python.exe` started with `__PYVENV_LAUNCHER__` takes the venv as its prefix, as CPython's
   multiprocessing relies on (bpo-35797); shown on the runner's CPython 3.13.7 (python.org build), not yet on
   uv's managed Python build.
6. uv writes `home = <directory of the base python.exe>` in the venv's `pyvenv.cfg`, and that directory
   holds `python.exe`; the venv's site-packages is `<venv>\Lib\site-packages`.
7. With no children, the host finishes its stop within Claude Code's 300 ms (O5).
8. Whether `${VAR:-default}` expands in a plugin `mcpServers` `command` (O8): documented for `.mcp.json`;
   for plugins the docs show placeholder substitution in `command` and user variables in `env`.
9. A same-user process can forge its recorded parent on Windows (629 section 3.2); the parent rules are
   weaker there than on POSIX against a deliberately hostile process of the same user. Not testable as a
   pass in 650; recorded so it is not read as equivalence.
