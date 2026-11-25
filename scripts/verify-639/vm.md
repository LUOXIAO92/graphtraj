# Task 639 phase 2 (draft, not run): Codex on a real Windows x64 VM

Status: a draft for review. Nothing here has run. The executable form waits until Main says how the VM is reached:
over SSH by Main, or run by the user inside the VM. Each item marked **(assumption)** must be checked or replaced first.

Phase 1 already showed the same paths with a stand-in Codex on GitHub's windows-latest runner (`steps.zsh P`).
Phase 2 replaces the stand-in with a real `@openai/codex`, using a DeepSeek model through the user's opencode-go
provider.

## 1. The VM

| Item | Value |
| --- | --- |
| Where | The user's own Google Cloud project, started for this run and **deleted afterwards** (the disk too) |
| Image | Windows Server 2022 Datacenter x64 (`windows-2022`, GCE public image) **(assumption)**. Windows 11 is not a public GCE image. Server 2022 has the Win32 job, named-pipe and ConPTY APIs Codex uses. If Codex's `mxc` sandbox needs a client SKU, this item fails, and the result is recorded as such |
| Size | `e2-standard-4` (4 vCPU, 16 GB), 64 GB balanced disk **(assumption: enough for Node, Python and Codex, with tests running serially)** |
| Network | Egress to the provider endpoint, npm and GitHub only. Ingress: RDP or SSH from the user's own IP only (firewall rule removed with the VM) |
| Locale | English (United States) by default. For 629 section 6 item 6 (non-ASCII), the cheap form is a non-ASCII working directory (`C:\work\测试ü`) and a non-ASCII prompt, as the CI run already does with TEMP. Switching the system locale to zh-CN/ja-JP needs a reboot; do it only if the user wants that item covered fully |
| Python | 3.13.7 x64 from python.org, "for all users", on PATH; `PYTHONUTF8=1` set only in the step's shell |
| Node | 22.18.0 x64 LTS (the CI version), from nodejs.org |
| Codex | `npm install -g @openai/codex@<version>`, with the version pinned at run time and written into the evidence. 629 read 0.172.0; graftling's real runs used 0.164.0 **(assumption: the version current on the run day works with graftling's app-server protocol; if not, use the newest that does and record it)** |
| Git | Git for Windows (gives Git Bash). Codex on Windows runs tools in PowerShell; Git Bash is only for the `exec`/PID item of 629 sec. 6.4 |
| Remote access | OpenSSH Server (Windows optional feature), key-only, the user's key **(assumption: Main runs the steps over SSH)**. Otherwise the user runs the same PowerShell script inside the VM over RDP and copies the evidence directory back |
| Developer Mode | On (Settings > For developers), or the steps run elevated: graftling links Codex's rollout (decision 4, `require_symbolic_links`) |
| graftling | `git clone https://github.com/LUOXIAO92/graftling.git` then check out the candidate SHA, and `pip install --no-deps -e .` plus `PyYAML==6.0.2 websockets==15.0.1 pytest==8.3.5` (the CI pins) in a venv |

## 2. The DeepSeek provider for Codex (key only inside the VM)

- The user creates the temporary key and types it **inside the VM** only, as a user environment variable, for
  example `[Environment]::SetEnvironmentVariable('OPENCODE_GO_API_KEY', '<key>', 'User')`. Alternatively it goes
  through `codex login --with-api-key` against the custom provider, if Codex supports that for a custom provider
  **(assumption)**.
- `%USERPROFILE%\.codex\config.toml` (written in the VM by the step, with no secret in it) **(assumption: the
  provider names and URL are the user's opencode-go values, which the user confirms)**:

  ```toml
  model = "<deepseek model id the user names, e.g. deepseek-chat>"
  model_provider = "opencode-go"

  [model_providers.opencode-go]
  name = "opencode-go (DeepSeek)"
  base_url = "<the user's opencode-go OpenAI-compatible base URL>"
  env_key = "OPENCODE_GO_API_KEY"
  wire_api = "chat"
  ```

  graftling's settings name the key with `connection.api_key_env: OPENCODE_GO_API_KEY` and `connection.base_url`.
  Codex reads the value from its own environment.
- Never in the repository, the evidence, CI or a command line. The steps' evidence is scanned for the key's value
  before it leaves the VM: the step greps for the value and fails if it is found, without printing the value. Any
  step started from macOS (SSH) sends no key: the SSH session's environment carries none (`SendEnv` unset), and the
  key exists only in the VM user's environment.
- After the run: the user revokes the key, then the VM and its disk are deleted.

## 3. Real-run steps, in order, each with the observable that proves it

Every step writes `C:\work\evidence\<step>\` (console, JSON results, `stderr.log`, `escaped_processes`, and the
process listings) and prints its verdict last.

| # | Step | Observable that proves it |
| --- | --- | --- |
| R0 | Preflight: versions (Windows build, Python, Node, Codex, git); `codex exec` with a one-line prompt | Codex answers, and its reported model/provider equal the configured DeepSeek ones (from `codex exec --json` or app-server `thread/start` `model`/`modelProvider`). The key's value is absent from all output |
| R1 | **Codex child: create, then a tool call, then the turn ends.** `AgentControl` + `CodexDriver` in a Python owner; `create` with an instruction that makes the model run one PowerShell command, for example writing a marker file under the worktree | The result is `completed`; the marker file exists; the record's `process` has `runtime_job` (`graftling-<marker>`); `codex-termination-<turn>.yml` lists what the reclaim stopped (it may be empty if Codex ended its own tools) |
| R2 | **Stop.** `resume` with an instruction that runs a long command (`Start-Sleep 600`), then `interrupt` | `interrupted`, standby; no process from the job is left (`find_marked_processes(tool_marker)` reports no job, or an empty list); the PIDs seen during the turn are gone |
| R3 | **Takeover.** As R2, but the owner process is ended (`Stop-Process -Force`) during the command; then a new owner process calls `status`, `interrupt` (confirm) and `resume` | Ended `owner-exited`; `escaped_processes.stopped` lists the leftover tool tree, **or** `error` says "No job ... is open". The second case means that a real Codex's tools do not inherit the job handle (the phase-1 inference), and it is reported, not hidden. Then the confirm lists the execution, and the resumed turn completes in the same Session id |
| R4 | **Codex parent host (MCP), one real call.** `python -m graftling.codex.host --settings <file> --output result.json "Use the subagents tool to create one codex child that answers OK, then report its answer."` | `result.json`: `outcome` completed, at least one `operations` entry with `parent_session`, `authenticated_callers` non-empty, and `stop_unconfirmed` `[]`. The child's record exists |
| R5 | 629 sec. 6 Codex items (below) | As listed |

### 629 section 6, Codex items

1. **Pipe identity.**
   - The `authenticated_callers[].caller_pid` of R4 is the MCP server. Record its parent chain (`Get-CimInstance Win32_Process`) and check that it is in the service's job (`IsProcessInJob`, via `graftling._win32`).
   - Caller inside Codex's sandbox: in a child turn, the model runs `python -m graftling.cli`, or the `subagents` CLI, with `GRAFTLING_CONNECTION` from its shell. Expected **(assumption)**: refused under `elevated` (a separate sandbox account; the pipe's DACL admits only the user's SID). Unknown under `mxc`. Record the error text.
   - Negative same-user test: a process outside the job (started from a second console) opens the pipe with a forged request. It must get `authority-denied`. Then one started with `PROC_THREAD_ATTRIBUTE_PARENT_PROCESS` naming the service: record the result (629 sec. 3.2 says this is the known weaker case).
2. **Job behaviour.** In a child turn:
   - `cmd /c start /b powershell -c Start-Sleep 600`, and `Start-Process powershell -ArgumentList '-c Start-Sleep 600'`. Both must be listed in the job and ended by the stop of R2.
   - Whether Codex's own sandbox uses a job, and if so, that it nests: assignment succeeded and the tools are in graftling's job.
   - The job is opened by name from a later process (R3).
3. **Process shape.**
   - The parent of the MCP server and of any hook: `codex.exe` directly, or `cmd.exe`/`node.exe`.
   - The command line of the Codex process: the npm shim (`codex.cmd`) resolved to `node.exe ...codex.js`, or a native `codex.exe`.
   - Recorded from `Win32_Process` (ParentProcessId, CommandLine) during R4.
4. **Session end (M18).** At the end of R4, the MCP server's exit and the time it exited relative to the service's. Expected: it ends at stdin EOF (exit 0) before the job is terminated. If it is killed instead (exit 1, the job's exit code), M18's EOF path is not what Codex uses, and that is recorded.
5. **app-server stdio and profile under `mxc` and `elevated`.** Run R1 and R4 twice, with `windows.sandbox = "mxc"` and `"elevated"` in `config.toml` **(assumption: those are the key and values on the run day)**. Record:
   - that `app-server --listen stdio://` starts;
   - that the permission profile graftling writes (no `unix_sockets`, M17; the control directory granted `write`) is accepted, with no error in `stderr.log`;
   - whether the MCP server runs outside the tool sandbox, so that it can open the pipe (the phase-1 inference behind M17).

## 4. Assumptions phase 2 must confirm (from phase 1)

- The MCP server Codex starts runs outside its tool sandbox and as the user, so it can open graftling's pipe. No permission entry grants the pipe on Windows.
- The control directory's `filesystem: write` grant is kept on Windows. It is harmless, but it is not what reaches the pipe.
- Real Codex's tools inherit the service's handles, as Rust's `std::process` does, so the job's name outlives the owner while a tool lives (R3). The stand-in does this through `PEER_TOOL_INHERIT`.
- Codex ends at its stdin's EOF, and it ends its MCP servers by closing their stdin (M18).
