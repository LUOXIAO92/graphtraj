# 460 real-host check: a Task member whose Worker and Runtime were killed leaves no /bin/zsh or /bin/sleep tool process after the Runner's reconcile

Main runs every step except 00u. Each Main command returns within 10 minutes or starts its work in the
background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/460-runner-member-killed-worker-tool-reclaim/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/460-runner-member-killed-worker-tool-reclaim/scripts/verify-460/steps.zsh`.

The base is `~/graphtraj-verify-460`, a new path. No other verify directory is touched.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `460 fix: worker records: True \| confirmation reclaims: True`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5`, and `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-460/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once. It starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for 01's Main. Refuses (`STOP`, signals nothing) unless the Runner's record of the member's running execution lists a live `sleep 460`. Kills the member's Worker and Runtime group, does one Runner status read, prints four `CHECK` lines and `summary: ALL PASS`, and writes `02-kill.json`. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/03-suite.txt`. It is done when the file shows `== totals:`. |

No step shows a dialog except 00u (folder trust).

## What each step does

### 00: preflight

As 459's: a scratch venv from the commit under test (`git archive`, editable install), click 8.5.0, yaml and
websockets copied read-only from production `.venv-runtime`, an isolated project with `graphtraj setup`, one
`team_leader` role (`claude`, `claude-opus-5-5`, `permission_mode: auto`), probe Task 1 set to ready, the Claude
host configuration, one `claude -p` login/model line and the plugin check. One extra line proves the fix is in the
venv: the Worker records the tool facts, and `_confirm_termination` reclaims.

### 01: the member runs `sleep 460`

The `claude -p` Main dispatches the member with `swarm`. The member's instruction: use the Bash tool exactly once,
with timeout 600000, to run exactly `sleep 460`, then reply DONE-460. The member's turn keeps running while the tool
runs. Main runs `probe.py member` until it prints `MEMBER-SLEEPING`. That means the member's execution has no
`execution.yml`, the Runner record `tool-processes-<execution>.yml` exists, and the descendants sidecar it names
lists a `sleep 460` still alive with its recorded start time. Its state line says
`tool_marker recorded=True|False`; the marker value is never printed. Main then stops without waiting for the member.

The member's `sleep 460` ends by itself about 7.7 minutes after it starts, so run 02 as soon as 01's Main ends.

### 02: kill, one Runner read, the checks

`probe.py kill` refuses (prints `STOP`, signals nothing) unless all of these hold:

- the member's execution is still running (no `execution.yml`);
- the Runner record exists for the mapped execution and has a marker;
- the mapped Worker holds the Session's ownership lock;
- the sidecar lists a live `sleep 460`;
- the recorded `runtime_pid` is alive and carries the member's marker.

**The "before the kill" lines print the record's entries (pid, argv)**, the live `sleep 460` and its recorded
parent (the Bash tool shell, expected `/bin/zsh -c …`). Then the probe:

1. SIGKILLs the member's Worker. It waits until the ownership lock is released, then SIGKILLs the Runtime's process
   group (only when the Runtime leads its own group; otherwise only that pid). Each signal is sent only if the pid
   still has the start time read before.
2. Prints the recorded tool processes still alive (the escaped tools).
3. Starts three bystanders of its own, each in its own session: Python with a different random
   `GRAFTLING_MEMBER_RUN`, Python without it, and a `/bin/sleep 901`.
4. Does one Runner status read as the project's root caller (`status_aliases([alias], project)`, as a direct parent
   reads). The Runner judges the member abnormal and answers: owner-exit record, then the Claude Adapter's Runtime
   termination confirmation, then (460) the tool reclaim, then one parent notice.
5. Prints `CHECK` 1 to 4:
   - 1: `execution.yml` is `owner-exited` and `terminal-confirmation-<execution>.yml` says `terminal_confirmed: true`.
   - 2: the receipt's `tool_processes` lists the tool shell and `sleep 460` as stopped, `remaining` is empty, and
     there is no `error`. The same result is the last entry of the Runner record's `reclaims`.
   - 3: none of the recorded identities and no `sleep 460` is alive (read only).
   - 4: the three bystanders are alive.
6. Stops only its own bystanders.

### 03: full suite

As 459's step 03, against the Worktree HEAD, six shards, stopped at 25 minutes.

## Rehearsal without a model (sandbox)

Set `VERIFY460_NO_MODEL=1 VERIFY460_BASE=$TMPDIR/rh460 VERIFY460_OUT=$TMPDIR/rh460-out`, then run `S 00` and `S 02`.
00 stops before Claude Code. 02 finds no member and must print `STOP … Nothing was done`. The full Runner path
(Worker and Runtime killed, status read, reclaim, bystanders) is covered by the dev test
`tests/test_runner_tool_reclaim_460.py` with real `/bin/sh` and `/bin/sleep`. It uses the fake Codex Runtime, and the
test writes the Runner record itself. Not rehearsed: 00's model, host configuration and plugin check, 00u, 01, Claude
Code's own Bash tool shell, the Claude Adapter's termination confirmation, and 03.
