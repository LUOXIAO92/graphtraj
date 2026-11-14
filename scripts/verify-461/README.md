# 461 real-host check: a killed owner's Pi child leaves no bash tool process after reconciliation

Main runs every step except 00u. Each Main command returns within 10 minutes or starts its work in the
background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/461-pi-child-tool-process-reclaim/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/461-pi-child-tool-process-reclaim/scripts/verify-461/steps.zsh`.

The base is `~/graphtraj-verify-461`, a new path. No other verify directory is touched. Nothing under `~/.claude`,
`~/.codex`, `~/.pi` or the production `.venv-runtime` is changed.

| Step | Who | Command | Expected time | Success |
|---|---|---|---|---|
| 00 | Main | `S 00` | 2-4 min | `461 fix: Pi owner samples: True \| Pi owner stops recorded: True \| PiDriver records it: True \| agents driver records it for pi: True \| GraphTraj Pi owner inherits: True`, `deps: click 8.5.0`, the Pi values (connection `pi/deepseek/deepseek-flash` resolved, `pi.sandbox_python`, `pi.sandbox_path`, `pi.agent_dir`; key variables by name only), `srt on sandbox_path:` a path, `sandbox available …: YES`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5`, `pi deepseek-flash OK: PI OK` (scratch agent dir; or `pi check SKIPPED` when `DEEPSEEK_API_KEY` is unset), `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-461/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | 1 min | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | returns at once | Starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | 2-9 min (waits for 01's Main) | Refuses (`STOP`, signals nothing) unless the child's descendants record lists a live `sleep 461`; prints the live process tree below the Runtime and the recorded chain (pid, ppid, pgid, uid, argv) before the kill; kills the child's owner and Runtime group; one reconciling read; four `CHECK` lines and `summary: ALL PASS`; writes `02-kill.json`. |
| 03 | Main | `S 03` | starts in background; 25 min max | Full suite at HEAD; read with `tail -n 25 …/realhost/03-suite.txt`; done when it shows `== totals:`. |

## What each step does

### 00: preflight

As 459's: a scratch venv from the commit under test (`git archive`, editable install), click 8.5.0, yaml and
websockets copied read-only from production `.venv-runtime`, an isolated project with `graphtraj setup`, probe Task 1
set to ready, the Claude host configuration, one `claude -p` login/model line and the plugin check. Added for Pi:

- the line proving the 461 fix is in the venv;
- the project's `roles.yml` has a second role, `pi`, the one role using Pi, so the member's agents-tool
  `create` with `runtime: pi` selects it (`AdapterDriver.prepare`). It is the user's configuration from
  production `roles.yml` (preset `pi_dsh_trial.team_leader`): `connection: pi/deepseek/deepseek-flash`
  (resolved read-only from the user's `~/.graphtraj/connections.yml`), `pi.sandbox_python`, `pi.sandbox_path`,
  `pi.agent_dir: ~/.pi/agent`, `worktree_access: read`;
- the resolved connection is printed: runtime, model, home, provider, whether a base URL is set, and the key
  variables it names with set/unset only. Never a value;
- `srt` on `sandbox_path` and `agent_sandbox.is_sandbox_available()` under `sandbox_python`;
- one Pi line: `pi --print --no-tools --no-session --provider deepseek --model deepseek-flash` with
  `PI_CODING_AGENT_DIR` = a scratch home `~/graphtraj-verify-461/scratch/pi-home` and the key from the
  environment, bounded to 120 s. Pi's startup migrations write `settings.json` and `auth.json` in its agent dir,
  so the user's `~/.pi` is never used or written here. When `DEEPSEEK_API_KEY` is unset in Main's shell, 00 prints
  `pi check SKIPPED: …` instead; the child's own login (through graftling's launch) is then proven by 01.

The steps run their commands with a cleared environment (`env -i`). `DEEPSEEK_API_KEY`, and any names in
`VERIFY461_KEEP_ENV`, are passed through when set in Main's shell, so a Pi child whose connection names a key
variable can start; 00 prints only their names. If 00 shows a key variable named by the connection as unset, or
the Pi line fails for a key, Main sets `VERIFY461_KEEP_ENV` (or exports the variable) and reruns 00.

### 01: the member and its Pi child

The `claude -p` Main dispatches the Claude member with `swarm`. The member uses only the agents tool. It creates a
**Pi** child with `Use the bash tool once to run exactly: sleep 461 . Then reply DONE-461.`, replies
`CREATE <agent> <execution>` and ends its turn. Main runs `probe.py child` until it prints `CHILD-RUNNING`: the
member's turn ended, the child record is `running` with a `runtime_pid`, and a `sleep 461` is alive. Its state line
says `runtime=pi`, `tool_marker recorded=True|False` and `tool_descendants recorded=True|False`; the marker value is
never printed.

The child's `sleep 461` ends by itself about 7.7 minutes after it starts, so run 02 as soon as 01's Main ends.

### 02: kill, one read, the checks

Pi 1.4.0 runs its bash tool as `/bin/bash -c "sleep 461"`, detached (its own session). Bash usually replaces
itself with `sleep`, so the recorded tool process can be `sleep 461` itself, its parent being Pi's node process.

`probe.py kill` refuses (prints `STOP`, signals nothing) unless the member's turn ended, the child is a `running`
Pi child, its `worker_pid` is the member's last Worker, the record has a `tool_marker` and a `tool_descendants`
path, that record lists a `sleep 461` still alive with its recorded start time, and the recorded `runtime_pid`
(if alive) is not readable without the child's marker. Before the kill it prints:

- **the live process tree below the Runtime** (read only, ignoring the boundary rule), each with pid, ppid, pgid,
  uid, `marker yes/no/unreadable` and argv. This shows whether `srt`, `sandbox-exec` and Pi's node kept the marker.
  A `marker no` there would stop the sampler at that process, and 02 would then `STOP`;
- **the recorded chain**: every record entry with pid, ppid, pgid, uid, live, argv;
- the live `sleep 461` and its recorded parent.

Then it:

1. SIGKILLs the recorded owner Worker, then the child Runtime's process group (only when the Runtime leads its own
   group; otherwise only that pid), each only if its pid still has the start time read before;
2. prints the recorded descendants still alive (the escaped tools);
3. starts three bystanders of its own, each in its own session: Python with a different random
   `GRAFTLING_MEMBER_RUN`, Python without it, and a `/bin/sleep 901`;
4. does one reconciling read (`GraphTrajAgents.reconcile_children`, as the Runner Worker's sweep does);
5. prints `CHECK` 1 (child `failed`/`owner-exited`), 2 (`escaped_processes` lists `sleep 461` and every recorded
   process alive after the kill as stopped, `remaining` empty, no `error`), 3 (none of the recorded identities and
   no `sleep 461` alive, read only) and 4 (the three bystanders alive);
6. stops only its own bystanders.

### 03: full suite

As 459's, against the Worktree HEAD, six shards, stopped at 25 minutes.

## Rehearsal without a model (sandbox)

`VERIFY461_NO_MODEL=1 VERIFY461_BASE=$TMPDIR/rh461 VERIFY461_OUT=$TMPDIR/rh461-out`, then `S 00` and `S 02`.
00 writes the `pi` role inline (same model, no connection lookup) and stops before Claude Code and Pi; in the
sandbox `srt` and `sandbox_python` are unreadable, so it prints `NONE`/`NO` for them. 02 runs `probe.py stub`
first: a fake member session and a Pi child record made through `AgentControl`; a stand-in owner Worker (Python, own
session) that runs the real descendant sampler on a stand-in Runtime (Python, own group, the child's marker), which
starts a real `/bin/bash -c 'sleep 461'` in its own session, as Pi's bash tool does. In the stub, the probe's
read-only `sleep 461` listing also shows the stand-in Worker and Runtime, whose Python code contains that text; the
CHECKs use the record, not that listing. Not rehearsed: 00's connection lookup, sandbox, model, Pi line, host
configuration and plugin check, 00u, 01, the real Pi Runtime chain (srt, sandbox-exec, node), and 03.
