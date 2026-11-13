# 459 real-host check: a killed owner's Claude child leaves no /bin/zsh or /bin/sleep tool process after reconciliation

Main runs every step except 00u. Each Main command returns within 10 minutes or starts its work in the
background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/459-reclaim-platform-binary-tool-descendants/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/459-reclaim-platform-binary-tool-descendants/scripts/verify-459/steps.zsh`.

The base is `~/graphtraj-verify-459`, a new path. No other verify directory is touched.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `459 fix: tool_descendants allowed: True \| reconcile reads it: True \| owner samples: True \| agents driver records it: True`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5`, and `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-459/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once. It starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for 01's Main, refuses (`STOP`, signals nothing) unless the child's descendants record lists a live `sleep 459`, kills the child's owner and Runtime group, does one reconciling read, prints four `CHECK` lines and `summary: ALL PASS`, and writes `02-kill.json`. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/03-suite.txt`. It is done when the file shows `== totals:`. |

## What each step does

### 00: preflight

As 451's: a scratch venv from the commit under test (`git archive`, editable install), click 8.5.0, yaml and
websockets copied read-only from production `.venv-runtime`, an isolated project with `graphtraj setup`, one
`team_leader` role (`claude`, `claude-opus-5-5`, `permission_mode: auto`), probe Task 1 set to ready, the Claude
host configuration, one `claude -p` login/model line and the plugin check. One extra line proves the fix is in the
venv.

### 01: the member and its child

The `claude -p` Main dispatches the member with `swarm`. The member uses only the agents tool. It creates a
Claude child with `Use the Bash tool once to run exactly: sleep 459 . Then reply DONE-459.`, replies
`CREATE <agent> <execution>` and ends its turn. Main runs `probe.py child` until it prints `CHILD-RUNNING`:
the member's turn ended, the child record is `running` with a `runtime_pid`, and a `sleep 459` is alive. Its
state line says `tool_marker recorded=True|False` and `tool_descendants recorded=True|False`; the marker value is never printed.

The child's `sleep 459` ends by itself about 7.6 minutes after it starts, so run 02 as soon as 01's Main ends.

### 02: kill, one read, the checks

`probe.py kill` refuses (prints `STOP`, signals nothing) unless the member's turn ended, the child is `running`,
its `worker_pid` is the member's last Worker, the record has a `tool_marker` and a `tool_descendants` path, that
record lists a `sleep 459` still alive with its recorded start time, and the recorded `runtime_pid` (if alive)
carries the child's marker. **The "before the kill" lines print the record's entries (pid, argv)**, the live
`sleep 459` and its recorded parent (the Bash tool shell, expected `/bin/zsh -c …`). Then it:

1. SIGKILLs the recorded owner Worker, then the child Runtime's process group (only when the Runtime leads its own
   group; otherwise only that pid), each only if its pid still has the start time read before;
2. prints the recorded descendants still alive (the escaped tools);
3. starts three bystanders of its own, each in its own session: Python with a different random
   `GRAFTLING_MEMBER_RUN`, Python without it, and a `/bin/sleep 901` (a platform binary that is not a descendant);
4. does one reconciling read (`GraphTrajAgents.reconcile_children`, as the Runner Worker's sweep does);
5. prints `CHECK` 1 (child `failed`/`owner-exited`), 2 (`escaped_processes` lists the `/bin/zsh` tool shell and
   `sleep 459` as stopped, `remaining` empty, no `error`), 3 (none of the recorded identities and no `sleep 459`
   alive, read only) and 4 (the three bystanders alive);
6. stops only its own bystanders.

### 03: full suite

As 451's step 05, against the Worktree HEAD, six shards, stopped at 25 minutes.

## Rehearsal without a model (sandbox)

`VERIFY459_NO_MODEL=1 VERIFY459_BASE=$TMPDIR/rh459 VERIFY459_OUT=$TMPDIR/rh459-out`, then `S 00` and `S 02`.
00 stops before Claude Code. 02 runs `probe.py stub` first: a fake member session and a child record made through
`AgentControl`; a stand-in owner Worker (Python, own session) that runs the real descendant sampler on a stand-in
Runtime (Python, own group, the child's marker), which starts a real `/bin/zsh -c 'sleep 459; :'` in its own
session. In the stub, the probe's read-only `sleep 459` listing also shows the stand-in Worker and Runtime, whose
Python code contains that text; the CHECKs use the record, not that listing. Not rehearsed: 00's model, host
configuration and plugin check, 00u, 01, Claude Code's own Bash tool shell, and 03.
