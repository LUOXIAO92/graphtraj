# Task 649 (W11) handoff to Task 650: DSH on real Windows

**DSH takes part in Task 650's real-Windows acceptance: it runs on native Windows x64.** The DSH host and DSH
children are supported there. graftling candidate: `5b7bd91d` on `agent/649-graftling-windows-dsh`, bundle
`graftling-649.bundle`, or dev once Main has merged it. The candidate contains graftling dev `5715323` (647, 648)
and fast-forwards from phase A's `21818f59`.

User environment details are not written here: the machine, account, addresses, provider choice, model and key
values. Main passes them through its local, uncommitted settings. Facts are marked **F**, inferences **I**.

## What 649 showed, and on what

- **F** Phase A, run 45984855702 (graftling `21818f59`, GitHub-hosted windows-latest x64, no credential; evidence in
  `evidence/run-45984855702-a1/`):
  - DSH 0.2.2-rc.5 installed with `npm install -g` on Node 24.22.3 (670 packages, npm's own "added 670 packages in
    18m"), and its CLI answers through the shim and through node.
  - `dsh web` printed its launch link in 3.4 s; graftling's `DshService` started, got its cookie, answered
    `session/list` and closed.
  - Nothing was left after the kill-on-close job handle closed, and all 3 DSH processes were gone 15 s after their
    owner was killed without `close()` (decision 3).
- **F** Every DSH test failure there came from graftling reading DSH's package from the directory of npm's
  `dsh.cmd` shim (`C:\npm\package.json`). Phase B reads the shim's target instead (`graftling.dsh.settings.dsh_entry`
  and `dsh_package`).
- **F** Phase B also makes the DSH plugin start a venv's base interpreter with `__PYVENV_LAUNCHER__`
  (`plugin.mjs directPython`, as 648 did for Pi). The host and its MCP server are then direct children of DSH's
  node, which the host's parent check and its MCP caller check require.
- **F** The phase B run (Main's `zsh scripts/verify-649/steps.zsh P` on `5b7bd91d`) gates on every
  `tests/test_*dsh*.py` against the installed DSH, with 37 must-pass tests (`dsh-new-tests.txt`).
- **I** The real DSH host inside a real DSH Session, a model turn, and uv's own tool venv on Windows have not run.
  These are this file's items.

## Items to observe

Run in an interactive console session (643: tool processes need an interactive logon). `<prefix>` is npm's global
prefix (`npm prefix -g`). `<venv>` is graftling's uv tool environment (`uv tool dir`\graftling) and `<site>` is
`<venv>\Lib\site-packages`.

| # | Item | Observable that proves it |
| --- | --- | --- |
| D1 | Install time and Node version | `node --version` is 24.9 or later. `Measure-Command { npm install -g @deepseek-ai/dsh@0.2.2-rc.5 }` and npm's "added N packages in T" give the time (CI: 18 min; record it with whether Defender real-time scanning is on). `dsh --version` prints `0.2.2-rc.5`. `where.exe dsh` lists `<prefix>\dsh.cmd` |
| D2 | graftling finds the installed DSH through the shim | `& "<venv>\Scripts\python.exe" -c "import shutil; from graftling.dsh.settings import dsh_package; print(dsh_package(shutil.which('dsh')))"` prints `<prefix>\node_modules\@deepseek-ai\dsh\package.json` |
| D3 | The DSH host with one real MCP call | After `dsh plugin --profile <profile> add <site>\graftling\dsh` (needs pnpm), or `--patch` (docs/install/dsh.md), start `dsh` in a project. The Session offers `mcp__graftling__subagents`. One call (for example the `models` or a status feature) returns a result, not `authority-denied`. `<project>\.agents-control\live\dsh-host` exists, or the same under `GRAFTLING_DATA_ROOT` |
| D4 | Process shape of the host (with D3 running) | `Get-CimInstance Win32_Process` shows two processes whose parent is DSH's `node.exe`, which runs `<prefix>\node_modules\@deepseek-ai\dsh\lib\bin.js`: the host (`-I -m graftling.dsh.host`) and the MCP server (`-I -m graftling.mcp`). Each is the venv's base interpreter, not `<venv>\Scripts\python.exe`, when the plugin found the venv's Python (I: uv's venv launcher behaves as a stdlib venv's; 648's H2 checks the same). The host's `__PYVENV_LAUNCHER__` names `<venv>\Scripts\python.exe` |
| D5 | A DSH child: create, a real turn, stop | From a host, create a child on a `runtime: dsh` connection (settings below) with a one-line prompt. It completes with the model's answer in its result and records. A `stop` during a second turn ends it with a terminal outcome. Afterwards no `node.exe` of that child's DSH service is left (its parent was the `cmd.exe` of `dsh.cmd`, in a `graftling-*` job) |
| D6 | The DSH service ends with its owner (decision 3) | While a child runs, note its DSH service processes (`node.exe` under `cmd.exe` under the owner's Python). `Stop-Process -Force` the owner. Within 15 s none of those processes remains |
| D7 | Whether a hard kill loses DSH session data (629 section 3.3) | After D6, the child's DSH Session log (`v4.jsonl` under the child's DSH home `sessions` root) parses line by line. The last completed turn is in it. A later `send` to that child either continues the same Session or fails with a stated reason; record which, and any leftover `session.lock` |
| D8 | Process shape of a child's tool | A child's shell tool (DSH's PowerShell executor on Windows) runs under DSH's `node.exe` in the same job. A `stop` ends it with the service |
| D9 | Code page and non-ASCII paths | Record `(Get-Culture).TextInfo.ANSICodePage` and `chcp`. With a project path containing non-ASCII characters (CI used `graftling-测试-ü`), D3 and D5 succeed. A prompt and an answer with non-ASCII text are intact in the child's result and in graftling's records |

## Settings DSH needs for DeepSeek's official endpoint (names and their source; never values)

| Name | Where it goes | Source |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | Environment of the process that owns the child (and of the main DSH, for its own Session); the value is entered at the K step and stays in the VM | graftling `README.md` "A DSH child's provider, home and key"; `dsh/settings.py` `_DEFAULT_KEY_ENV` (the variable DSH's Messages route reads) |
| `runtime: dsh` | The child's connection in the host's configuration | `README.md` connections (`deepseek-dsh` example) |
| `provider` (omit, or `deepseek-official`) | Same connection | `dsh/settings.py` `DEFAULT_PROVIDER`; README "Provider" |
| `api_key_env: DEEPSEEK_API_KEY` | Same connection: names the variable, never the key | README connections; `dsh/settings.py` `credential_environment` |
| `model` | The child's model at create or in the connection's `models` | `dsh/settings.py` `prepare` ("Supply the actual native DSH model") |
| `base_url` (only if not DSH's default official address) | Same connection; `http(s)` with no user, query or fragment | README "`base_url`"; `dsh/settings.py` `prepare` |
| `home` (optional) | Same connection: the child's `DSH_HOME`; without it graftling makes an empty one | README "Home" |
| `GRAFTLING_DATA_ROOT` or `GRAFTLING_DSH_CONFIG` (optional) | Environment of `dsh` for the host's data root and per-Runtime settings | docs/install/dsh.md "Data root and configuration" |
| `GRAFTLING_PYTHON` (optional) | Environment of `dsh`, when the plugin should not look for the installation's Python | docs/install/dsh.md "Which Python the plugin runs" |
| Not set: `DEEPSEEK_BASE_URL`, `DEEPSEEK_SEARCH_BASE_URL` | Leave them unset in the shell. graftling removes them from a child (`dsh/settings.py` `AMBIENT_ENDPOINTS`), but the main DSH would follow them | `dsh/settings.py` |
| Node >= 24.9.0; pnpm for `dsh plugin add` | The VM | DSH's `engines`; docs/install/dsh.md |

## Remaining inferences

- **I** A real model turn of a DSH child on Windows behaves as the stand-in service's turns on the runner. The
  stand-in covers create, turn, resume and end delivery; it has no network and no model.
- **I** uv's tool venv on Windows uses a launcher as a stdlib venv does, so `directPython` applies (D4; 648 H2).
- **I** DSH's own tool processes stay in the service's job and end with it (D8). The job is inherited by
  children unless they break away; DSH's `dsh-win32-process` package also uses Job Objects of its own.
- **I** The install time on the VM depends on Defender scanning and the network. The CI job's npm download cache
  (actions/cache) can only save the download.
- **I** The CI run starts `dsh.cmd` through `cmd.exe` with list arguments that hold no model text. The 629 note
  on cmd.exe quoting applies only if model-influenced text ever reaches that command line.
