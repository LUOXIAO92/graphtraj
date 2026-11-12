# 451 real-host check: a child's lost owner reaches the member once, through the 15 s sweep

Main runs every step except 00u. Each Main command returns within 10 minutes or starts
its work in the background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/451-owner-exited-child-parent-notice/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/451-owner-exited-child-parent-notice/scripts/verify-451/steps.zsh`.

The base is `~/graphtraj-verify-451`, a new path. `~/graphtraj-verify-449` is not touched.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `451 sweep: True 15.0`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5`, and `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-451/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once. It starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for 01's Main, then prints `CHILD-RUNNING`, the killed pids and `KILLED child <agent> execution <id>`, and writes `02-kill.json`. Prints the 03 command. |
| 03 | Main | `S 03` | Returns at once. It starts a `claude -p` Main that resumes the member, and prints the 04 command. |
| 04 | Main | `S 04 2>&1 \| tee …/realhost/04.txt` | Waits up to 9 minutes for 03's Main, then prints four `CHECK` lines and `summary: ALL PASS`. |
| 05 | Main | `S 05` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/05-suite.txt`. It is done when the file shows `== totals:`. |

## What each step does

### 00: preflight

It is 449's preflight:

- a scratch venv built from the commit under test (`git archive`, then an editable install);
- click 8.5.0, yaml and websockets copied read-only from production `.venv-runtime`. The step stops unless click is 8.5.0;
- an isolated project with `graphtraj setup`;
- one `team_leader` role as in 450: `claude`, `claude-opus-5-5`, `permission_mode: auto`;
- probe Task 1, set to ready;
- the Claude host configuration;
- one `claude -p` line that checks login and model, and the plugin check.

### 01: start the member and its child

The `claude -p` Main dispatches the member with `swarm`. The member uses only the agents tool:

1. It creates a Claude child with the instruction `Use the Bash tool once to run exactly: sleep 400 . Then reply DONE-451.`
2. It prints `CREATE <agent> <execution>`.
3. It calls `wait` on the child with `timeout_seconds: 600`. This keeps the member's turn, and its Worker, alive.
4. On any input with `source: graphtraj`, it replies with those inputs verbatim and then `REPORT-451-END`.

Main runs `probe.py child` (each call at most 100 s, at most 5 calls) until the child's record is running with a live `runtime_pid`. It then prints `CHILD-RUNNING` and stops. It retires nothing.

### 02: kill the child's owner

1. It reads the member mapping's `worker_pid` and checks that it equals the child execution's `process.worker_pid`. The Worker that serves the member's agents channel owns the child (engineer.md).
2. It sends SIGKILL to that Worker.
3. It kills the child's `runtime_pid` and its process group, if it is still alive.
4. It also kills the member's own `runtime_pid` group, so the Runner can resume the member. A real Worker crash leaves that Runtime alone as well.
5. It writes `02-kill.json`.

### 03: resume the member

The `claude -p` Main calls `agents` `resume` on the member alias with this message:

> Call no tool. Reply WAITING-451 and end your turn. When an input whose JSON has source graphtraj arrives, reply with every such input verbatim, then REPORT-451-END.

It then polls with `probe.py wait` until the member's `execution.yml` holds `REPORT-451-END`.

Nothing reads the child's record before the new Worker does. The member's new Worker sweeps after 15 s, ends the child as `owner-exited`, and sends the notice through `notify_member_of_child_end`.

### 04: observe (read only)

It prints four checks:

1. The child execution is `failed`, with error `owner-exited` and `notification` `delivered` (or `queued`).
2. The project's records hold exactly one distinct notice for that execution. The member's report holds exactly one `failed` input with that execution.
3. The child's end was recorded, which is the sweep's reconcile, at most 60 s after the member's resumed core execution started. If something else read the child first, the line says so.
4. No killed pid and no `sleep 400` process is alive.

### 05: full suite

This is 449's step 03, writing to `05-suite.txt` and `05-shards/`.

## Fallbacks and rehearsal flags

01 writes its Main's pid to `…/realhost/01-main.pid` and 02 waits on that file; 03 and 04 use `03-main.pid`
the same way. A missing pid file prints `STOP: no pid file <path>; run the previous step first`.

00 and 01 first stop, changing nothing, if a pid in `01-main.pid`, `01-main-stream.pid`, `03-main.pid` or
`03-main-stream.pid` is alive, or if a `sleep 400` process runs. They print what is alive. Wait for it to end,
then rerun; the script never signals it.

Fallbacks are printed beside each step. If the resume is refused, for example because the previous execution is still closing, rerun 03 once.

`VERIFY451_BASE`, `VERIFY451_OUT`, `VERIFY451_NO_MODEL` and `VERIFY451_CLAUDE` (a stub host) exist for rehearsal only.

## Rehearsed in the sandbox without a model

Base and output were under `$TMPDIR`.

- 00 with `VERIFY451_NO_MODEL`: `deps: click 8.5.0`, `451 sweep: True 15.0`, `roles OK`, `task 1 ready`.
- `probe.py child`, `kill`, `wait` and `observe` on synthetic records, with real `sh -c 'sleep 400'` processes as the Worker and the two Runtimes:
  - CHILD-RUNNING was found;
  - the three processes were killed, each Runtime by its own group;
  - observe before delivery shows FAIL on checks 1–3;
  - observe after synthetic delivery shows `summary: ALL PASS`, with `12.0 s` for check 3;
  - no process was left.

Not rehearsed:

- the `claude -p` steps 01 and 03;
- the real Runner resume after a killed Worker;
- the real sweep;
- 05.
