# Task 648 (W10) handoff to Task 650: the Pi host on real Windows

Task 648 made the Pi host work on Windows and refuses a Pi child there. Its evidence is a stand-in Pi on the
GitHub-hosted Windows runner (`steps.zsh P`). This file lists what only a real Pi on a real Windows machine can show:
what to observe, the observable that proves each item, the settings Pi needs for its model, and the assumptions that
are still inferences. graftling candidate: `f759fd6c` on `agent/648-graftling-windows-pi` (bundle
`graftling-648.bundle`), or dev once Main has merged it.

User environment details are not written here: the machine, account, cloud project, addresses, provider choice,
model and endpoint values. Main passes them through its local, uncommitted settings.

## What changed, briefly

- **The host and MCP server start as direct children of Pi's process.** Pi's process is `node` running Pi's
  `dist/cli.js`, which npm's `pi.cmd` starts. A venv's `Scripts\python.exe` is a launcher that starts the real
  interpreter as its own child. So on Windows the extension (`pi/extension.mjs`, `directPython`) starts the venv's
  base interpreter directly with `__PYVENV_LAUNCHER__=<venv>\Scripts\python.exe`. This applies to the host
  (`-I -m graftling.pi.host`) and to the MCP server it registers (`-I -m graftling.mcp`, the variable in the
  server's `env`). graftling's checks are unchanged:
  - the host's parent must be node with Pi's entry as its argument;
  - an MCP caller's parent must be that same node.
- **A Pi child on Windows fails with `unsupported-runtime`.** The message: "Pi children are not supported on
  Windows: a Pi child runs only inside srt (@anthropic-ai/sandbox-runtime), whose Windows support is still alpha,
  ...". This holds before any selection, sandbox or launch work.
- **The host ends at its stdin's EOF** when Pi's `session_shutdown` closes it, with exit 0. No signal is involved.

## Items to observe

Run each in an interactive console session (643's finding for tool processes; Pi's bash tool runs Git Bash).
`<venv>` below is the uv tool environment of graftling (`uv tool dir`\graftling). `<site>` is `<venv>\Lib\site-packages`.

| # | Item | Observable that proves it |
| --- | --- | --- |
| H1 | The extension loads and the host starts from the installed package (`pi install <site>\graftling\pi`, then `pi` from PowerShell, which runs `pi.cmd`) | Pi starts with no extension error. `/mcp` lists the server `graftling` from the extension, connected. `<project>\.agents-control\live\pi-host` exists (or under `GRAFTLING_DATA_ROOT` when set) |
| H2 | uv's tool venv uses the same launcher as a stdlib venv (I1) | `& "<venv>\Scripts\python.exe" -c "import sys; print(sys.executable); print(sys._base_executable)"` prints two different paths. With `$p = Start-Process "<venv>\Scripts\python.exe" -ArgumentList '-c','import time; time.sleep(30)' -PassThru`, `Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)"` shows a `python.exe` child |
| H3 | Process shape: `pi.cmd` -> `cmd.exe` -> `node.exe` with Pi's entry -> host (I3, I4) | `Get-CimInstance Win32_Process` lists `ProcessId, ParentProcessId, ExecutablePath, CommandLine` for the process whose CommandLine has `graftling.pi.host` and for its parent. The host's `ExecutablePath` is the base interpreter, not `<venv>\Scripts\python.exe`. Its parent is `node.exe`, whose CommandLine names Pi's `...\pi-coding-agent\dist\cli.js`. No `python.exe` sits between them |
| H4 | The host runs as the tool venv | Before starting Pi, add the record line below to `<site>\zz_record_648.pth`. Then `<venv>\starts-648.jsonl` gets one line whose `argv` has `graftling.pi.host`, with `prefix` = `<venv>` and `ppid` = node's PID from H3. Remove the `.pth` afterwards |
| H5 | Pi passes the registered `env` to the MCP server (I2) | The same record file has a `graftling.mcp` line with `prefix` = `<venv>` and `ppid` = node's PID. If Pi dropped `env`, that server would run as the base interpreter: no record line, and `/mcp` would show the server failing (`No module named graftling`, or "The owning Agent connection is unavailable" without `GRAFTLING_CONNECTION`) |
| H6 | One MCP call passes the direct-child check | Ask the model to call `subagents` `execute` `status`. The result has `"result": {"agents": []}` and is not `authority-denied` |
| H7 | A caller that is not a direct child of Pi's node is refused | In Pi's bash tool, run `GRAFTLING_CONNECTION='<project>\.agents-control\live\pi-host\control-...' '<venv>\Scripts\subagents.exe' status`, with the real directory name from H1. It fails with `authority-denied` "The client is not owned by this native Pi host.": its parent is a launcher under Git Bash, not node |
| H8 | The Pi child refusal, with its reason | Ask the model to `create` with `runtime: "pi"`. `isError` true, code `unsupported-runtime`, and the message starts "Pi children are not supported on Windows: a Pi child runs only inside srt". `<root>\agents` gains no record |
| H9 | Session end without a signal (M18) | `/quit`, then within 10 s no process whose CommandLine has `graftling.pi.host` or `graftling.mcp` remains. Pi reports no "Independent Pi host failed" (the extension's close rejects on a non-zero host exit). Note whether `graftling.mcp` ended on its own or was terminated (I5): Pi's record of the server's exit, or none of its log lines after stdin closed |
| H10 | Pi ends without its shutdown handler (optional) | `Stop-Process` on Pi's `node.exe`. The host sees its stdin close and exits within 10 s; no host process remains |
| H11 | Non-ASCII project path (optional) | H1, H6 and H9 again with the project under a directory whose name has non-ASCII characters (the CI runs under one) |

The H4 record line (one line, the same as `tests/test_pi_windows_648.py` uses on the runner):

```text
import json, os, sys; open(os.path.join(sys.prefix, 'starts-648.jsonl'), 'a', encoding='utf-8').write(json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'prefix': sys.prefix, 'executable': sys.executable, 'argv': sys.orig_argv}) + '\n')
```

## Settings for Pi's model (names only)

Main fills in the values from its local settings. Sources: Pi 1.4.0's own documentation
(`@earendil-works/pi-coding-agent/docs/*.md`) and its model library (`@earendil-works/pi-ai/dist`). graftling's
install guide (`docs/install/pi.md`) names 1.4.0 as the Pi version of its real runs. Check the same files in the
Pi version the VM installs.

| Setting | Name | Source |
| --- | --- | --- |
| API key of a built-in provider | the provider's variable in the table "Use an API key from the environment" | `docs/providers.md`. The mapping is `pi-ai/dist/env-api-keys.js` |
| Or the key stored for Pi | `auth.json` in the agent directory: `{"<provider>": {"type": "api_key", "key": ...}}` | `docs/providers.md` ("Authenticate interactively", "Load an API key from a command"); `docs/configuration.md` (agent directory) |
| Provider and model at start | `--provider <id>` with `--model <id>`, or `defaultProvider` / `defaultModel` in `settings.json` | `docs/cli.md`, `docs/settings.md` |
| Provider id and its endpoint | a built-in provider carries its official endpoint, so no base URL setting is needed | `pi-ai/dist/models.generated.js` (provider ids); `pi-ai/dist/providers/<id>.js` (`baseUrl`) |
| A custom endpoint instead | `models.json`: `providers.<id>.baseUrl`, `api`, `apiKey` | `docs/models.md`, `docs/custom-provider.md` |
| Agent directory | `PI_CODING_AGENT_DIR`; default `~/.pi/agent` (on Windows `%USERPROFILE%\.pi\agent`, inference I8) | `docs/environment-variables.md` |
| Bash for tools | `shellPath` in `settings.json` when Git Bash is not found | `docs/windows.md` |
| graftling's Python (optional) | `GRAFTLING_PYTHON`; without it the extension finds `<venv>\Scripts\python.exe` from its own location | graftling `PUBLIC_API.md` 1.6 |
| graftling's data root (optional) | `GRAFTLING_DATA_ROOT`, or `pi --agents-config <file>` | graftling `PUBLIC_API.md` 1.6, `docs/install/pi.md` |

The key variable must be set in the console session that starts `pi`. The host inherits Pi's environment but
reads no key. No graftling setting names a key for the Pi host, because no Pi child runs on Windows.

## Assumptions that are still inferences

| # | Inference | Shown by | If it is false |
| --- | --- | --- | --- |
| I1 | uv's tool venv `python.exe` is a launcher like the stdlib venv's (the runner proves the stdlib venv only) | H2 | Nothing breaks: `directPython` sees `sys.executable == sys._base_executable` and keeps the command |
| I2 | Pi passes a registered server's `env` to the process. `docs/mcp.md` says stdio servers use `env`; whether it is merged into Pi's environment is unknown, and the fix does not depend on that | H5 | The MCP server runs as the base interpreter and cannot import graftling. Report it; the fix would need another channel for the variable |
| I3 | Real Pi starts extensions' children (the host, by graftling's `spawn`) and stdio MCP servers directly from `node`, without `cmd.exe` or a shell | H3, H5 | The direct-child check refuses the MCP server (`authority-denied`). That needs a decision; there is no workaround in 648 |
| I4 | On Windows, `process.title = 'pi'` changes only the console title, so node's command line keeps Pi's entry as its second word, which `verify_native_parent` checks | H1, H3 | The host refuses to start: "The MCP pipe is not owned by the selected native Pi process." |
| I5 | At the Session's end Pi closes the server's stdin before terminating it (`docs/mcp.md`: stdin, then SIGTERM, then SIGKILL; on Windows a kill is `TerminateProcess`), with time for `graftling.mcp` to end on its own | H9 | Harmless: `graftling.mcp` holds no state. Record which happened |
| I6 | Pi runs `session_shutdown` handlers on `/quit` on Windows | H9 | The host still ends when node exits and closes its stdin (H10) |
| I7 | The real Pi's `node` resolves `process.argv[1]` to the same file the command line names. The stand-in shows this for npm's `pi.cmd` with its doubled backslash | H1 | As I4 |
| I8 | Pi's agent directory on Windows is `%USERPROFILE%\.pi\agent` | Pi's `/login` writes `auth.json` there | Set `PI_CODING_AGENT_DIR` |

What the runner already showed (no inference left for the stdlib venv), once Main's `P` passes:
- the venv launcher's child shape;
- `__PYVENV_LAUNCHER__` honoured under `-I`;
- node as the direct parent of the host and the MCP server;
- one MCP call over the named pipe;
- the refusal message;
- the Session end at stdin EOF with exit 0.
