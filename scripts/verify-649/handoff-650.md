# Task 649 (W11) handoff to Task 650: DSH on real Windows

**DSH takes part in Task 650's real-Windows acceptance: it runs on native Windows x64.** The DSH host and DSH
children are supported there. graftling candidate: `0e5c92a6` on `agent/649-graftling-windows-dsh` (correction 1),
bundle `graftling-649.bundle`, or dev once Main has merged it. The candidate contains graftling dev `5715323`
(647, 648) and fast-forwards from `5b7bd91d`, which is on the remote.

User environment details are not written here: the machine, account, addresses, the model service and its
interface, model names and key values. Main passes them through its local, uncommitted settings. This file names
only setting and variable names, as graftling's code and documents name them. Facts are marked **F**, inferences
**I**.

## What 649 showed, and on what

- **F** Phase A, run 45984855702 (graftling `21818f59`, GitHub-hosted windows-latest x64, no credential; evidence in
  `evidence/run-45984855702-a1/`):
  - DSH 0.2.2-rc.5 installed with `npm install -g` on Node 24.22.3: 670 packages, npm's own "added 670 packages in
    18m".
  - Its CLI answers through the npm shim and through node.
  - `dsh web` printed its launch link in 3.4 s. graftling's `DshService` started, got its cookie, answered
    `session/list` and closed.
  - Nothing was left after the kill-on-close job handle closed. All 3 DSH processes were gone 15 s after their owner
    was killed without `close()` (decision 3).
- **F** Phase B round 1, run 45996884900 (graftling `5b7bd91d`):
  - Every DSH test passed but two delivered-plugin tests, and one install test regressed.
  - **Cause of the two:** DSH's plugin Loader imports a patch row's `name` as an ES module specifier, and a Windows
    path such as `D:\...\plugin.mjs` is not one (`evidence/correction-1-loader.md`). graftling's own child rows
    (`agents-mcp`, `agents-review`) had the same form.
  - Correction 1 (`0e5c92a6`) names them as `file:` URLs on Windows.
  - The install test now checks what Python the host and the MCP server run as.
- **F** The plugin starts a venv's base interpreter with `__PYVENV_LAUNCHER__` on Windows (`plugin.mjs`
  `directPython`, as 648 did for Pi). The host and its MCP server are then direct children of DSH's node, which the
  host's parent check and MCP caller check require.
- **I** The real DSH host inside a real DSH Session, a model turn, and uv's own tool venv on Windows have not run.
  These are this file's items.

## Items to observe

Run in an interactive console session (643: tool processes need an interactive logon). `<prefix>` is npm's global
prefix (`npm prefix -g`). `<venv>` is graftling's uv tool environment (`uv tool dir`\graftling) and `<site>` is
`<venv>\Lib\site-packages`.

| # | Item | Observable that proves it |
| --- | --- | --- |
| D1 | Install time and Node version | `node --version` is 24.9 or later. `Measure-Command { npm install -g @deepseek-ai/dsh@0.2.2-rc.5 }` and npm's "added N packages in T" give the time (CI: 18 min; record whether real-time malware scanning is on). `dsh --version` prints `0.2.2-rc.5`. `where.exe dsh` lists `<prefix>\dsh.cmd` |
| D2 | graftling finds the installed DSH through the shim | `& "<venv>\Scripts\python.exe" -c "import shutil; from graftling.dsh.settings import dsh_package; print(dsh_package(shutil.which('dsh')))"` prints `<prefix>\node_modules\@deepseek-ai\dsh\package.json` |
| D3 | The DSH host with one real MCP call | After `dsh plugin --profile <profile> add <site>\graftling\dsh` (needs pnpm), start `dsh` in a project. The Session offers `mcp__graftling__subagents`. One call (for example `models`, or a status) returns a result, not `authority-denied`. `<project>\.agents-control\live\dsh-host` exists, or the same under `GRAFTLING_DATA_ROOT`. Note: the documented `--patch` form (docs/install/dsh.md) names the plugin by a path; on Windows that name must be a `file:` URL (`file:///C:/.../plugin.mjs`), the form correction 1 uses (I: W12 owns that document) |
| D4 | Process shape of the host (with D3 running) | `Get-CimInstance Win32_Process` shows two processes whose parent is DSH's `node.exe` (its command line runs `<prefix>\node_modules\@deepseek-ai\dsh\lib\bin.js`): the host (`-I -m graftling.dsh.host`) and the MCP server (`-I -m graftling.mcp`). Each is the venv's base interpreter, not `<venv>\Scripts\python.exe`, when the plugin found the venv's Python (I: uv's venv launcher behaves as a stdlib venv's; 648's H2 checks the same). The host's environment names `<venv>\Scripts\python.exe` in `__PYVENV_LAUNCHER__` |
| D5 | A DSH child: create, a real turn, stop | From a host, create a child on a `runtime: dsh` connection (settings below) with a one-line prompt. The child has graftling's tool, which shows its `agents-mcp` row loaded from a `file:` URL. It completes with the model's answer in its result and records. A `stop` during a second turn ends it with a terminal outcome. Afterwards no `node.exe` of that child's DSH service is left (its parent was the `cmd.exe` of `dsh.cmd`, in a `graftling-*` job) |
| D6 | The DSH service ends with its owner (decision 3) | While a child runs, note its DSH service processes (`node.exe` under `cmd.exe` under the owner's Python). `Stop-Process -Force` the owner. Within 15 s none of those processes remains |
| D7 | Whether a hard kill loses DSH session data (629 section 3.3) | After D6, the child's DSH Session log (`v4.jsonl` under the child's DSH home's sessions root) parses line by line. The last completed turn is in it. A later `send` to that child either continues the same Session or fails with a stated reason; record which, and any leftover `session.lock` |
| D8 | Process shape of a child's tool | A child's shell tool (DSH's PowerShell executor on Windows) runs under DSH's `node.exe` in the same job. A `stop` ends it with the service |
| D9 | Code page and non-ASCII paths | Record `(Get-Culture).TextInfo.ANSICodePage` and `chcp`. With a project path containing non-ASCII characters (CI used `graftling-测试-ü`), D3 and D5 succeed. A prompt and an answer with non-ASCII text are intact in the child's result and in graftling's records |

## Interface settings DSH needs (names only; values from Main's local settings)

| Name | Where it goes | Source in graftling |
| --- | --- | --- |
| `runtime: dsh` | The child's connection in the host's configuration | `README.md` "Connections" |
| `api_key_env` | Same connection: the **name** of the environment variable that holds the model service's key, never the key | `README.md`; `dsh/settings.py` `credential_environment` |
| the variable `api_key_env` names | Environment of the process that owns the child; its value is entered at the K step and stays in the VM | `README.md` "A DSH child's provider, home and key". Without `api_key_env`, a child keeps DSH's own default key variable, `dsh/settings.py` `_DEFAULT_KEY_ENV` |
| `provider` (optional) | Same connection: omitted means DSH's built-in route (`dsh/settings.py` `DEFAULT_PROVIDER`); otherwise a provider id the installed DSH serves, which then requires `api_key_env` | `README.md` "Provider"; `dsh/settings.py` `pi_ai_route` |
| `base_url` (optional) | Same connection: the interface address when it is not the route's default; `http(s)` with no user, query or fragment | `README.md` "`base_url`"; `dsh/settings.py` `prepare` |
| `model` | The child's model at create, or in the connection's `models` | `dsh/settings.py` `prepare` |
| `home` (optional) | Same connection: the child's `DSH_HOME`; without it graftling makes an empty one | `README.md` "Home" |
| The main DSH Session's own login | The environment or DSH's own credential store of the `dsh` the user starts (for the host's Session) | `README.md` (DSH may read a `.env` and its home's `.credentials.yaml`) |
| `GRAFTLING_DATA_ROOT` or `GRAFTLING_DSH_CONFIG` (optional) | Environment of `dsh`, for the host's data root and per-Runtime settings | docs/install/dsh.md "Data root and configuration" |
| `GRAFTLING_PYTHON` (optional) | Environment of `dsh`, when the plugin should not look for the installation's Python | docs/install/dsh.md "Which Python the plugin runs" |
| Leave unset: the variables in `dsh/settings.py` `AMBIENT_ENDPOINTS` | The shell. graftling removes them from a child; DSH would otherwise route to them when its profile names no endpoint (that file's comment) | `dsh/settings.py` |
| Node >= 24.9.0; pnpm for `dsh plugin add` | The VM | DSH's `engines`; docs/install/dsh.md |

## Remaining inferences

- **I** A real model turn of a DSH child on Windows behaves as the stand-in service's turns on the runner. The
  stand-in covers create, turn, resume and end delivery; it has no network and no model.
- **I** uv's tool venv on Windows uses a launcher as a stdlib venv does, so `directPython` applies (D4; 648 H2).
- **I** DSH accepts `file:` URL row names from a real profile patch as it does in the delivered-plugin fixture (D3,
  D5). The fixture uses DSH's own Loader and inventory, so this is likely.
- **I** DSH's own tool processes stay in the service's job and end with it (D8). DSH's `dsh-win32-process` package
  also uses Job Objects of its own.
- **I** The install time on the VM depends on malware scanning and the network. The CI job's npm download cache can
  only save the download.
