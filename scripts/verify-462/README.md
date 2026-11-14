# 462 real-host check: a killed owner's Codex child leaves no tool process after reconciliation

Adapted from `scripts/verify-459`. Main runs every step except 00u. Each Main command returns within 10 minutes
or starts its work in the background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/462-codex-child-tool-process-reclaim/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/462-codex-child-tool-process-reclaim/scripts/verify-462/steps.zsh`.

The base is `~/graphtraj-verify-462`, a new path. No other verify directory is touched.

The Main and the member are Claude (`claude-opus-5-5`), as in 459. The child is Codex with `gpt-6-luna` only: its
model comes from the project's only Codex preset, `codex_child` (`probe.py prepare`). The member's `create` names no
model: GraphTraj's agents driver refuses a selected model, connection, preset or reasoning effort (`invalid-config`,
seen on the first real-host run, Correction 1). One Codex run.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `462 fix: reconcile reads tool_descendants: True \| Codex owner samples: True \| Codex owner reclaims: True \| agents driver records Codex: True`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `codex logged in: YES`, `codex result: MODEL OK`, `result: MODEL OK` with `claude-opus-5-5`, and `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-462/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once. It starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for 01's Main, refuses (`STOP`, signals nothing) unless the child's descendants record lists a live `sleep 462`, kills the child's owner and the app-server's group, does one reconciling read, prints four `CHECK` lines and `summary: ALL PASS`, and writes `02-kill.json`. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/03-suite.txt`. It is done when the file shows `== totals:`. |

## What each step does

### 00: preflight

As 459's, plus the Codex lines. The Codex login check prints only `YES` or `NO` (it greps `codex login status`
for `Logged in` and prints nothing of its text). `codex exec -m gpt-6-luna --sandbox read-only --json` (the `codex_child` preset's model) answers one
line in the isolated project; only its last agent message is printed. No key value, account text or `~/.codex`
file is read or printed.

### 01: the member and its Codex child

The `claude -p` Main dispatches the member with `swarm`. The member uses only the agents tool. It creates a child
with `{"runtime": "codex", "instruction": "Use your shell tool once to run exactly: sleep 462 . Wait for it.
Then reply DONE-462."}` (model from the `codex_child` preset: `gpt-6-luna`), replies `CREATE <agent> <execution>` and ends its turn. Main
runs `probe.py child` until it prints `CHILD-RUNNING`: the member's turn ended, the child record is `running` with
a `runtime_pid` (the owned Codex app-server, the `codex` launcher), and a `sleep 462` is alive. Its state line says
`tool_marker recorded=True|False` and `tool_descendants recorded=True|False`; the marker value is never printed.

The child's `sleep 462` ends by itself about 7.7 minutes after it starts, so run 02 as soon as 01's Main ends.

### 02: kill, one read, the checks

`probe.py kill` refuses (prints `STOP`, signals nothing) unless the member's turn ended, the child is `running`,
its `worker_pid` is the member's last Worker, the record has a `tool_marker` and a `tool_descendants` path, that
record lists a `sleep 462` still alive with its recorded start time, and the recorded `runtime_pid` (if alive)
carries the child's marker (the `codex` launcher's environment is readable). The "before the kill" lines print
the record's entries (pid, argv): expected the native `codex` app-server, the tool shell (if Codex keeps one) and
`sleep 462`. Then it:

1. SIGKILLs the recorded owner Worker, then the app-server's process group (the launcher leads its own group; the
   native binary is in it), each only if its pid still has the start time read before;
2. prints the recorded descendants still alive (the escaped tools; Codex's tool shells are in their own sessions);
3. starts three bystanders of its own, each in its own session: Python with a different random
   `GRAFTLING_MEMBER_RUN`, Python without it, and a `/bin/sleep 901`;
4. does one reconciling read (`GraphTrajAgents.reconcile_children`, as the Runner Worker's sweep does);
5. prints `CHECK` 1 (child `failed`/`owner-exited`), 2 (`escaped_processes` lists every recorded process alive
   after the kill, including `sleep 462`, as stopped, `remaining` empty, no `error`), 3 (none of the recorded
   identities and no `sleep 462` alive, read only) and 4 (the three bystanders alive);
6. stops only its own bystanders.

A normal-end observation is not part of this run (it would need a second Codex turn). The dev tests cover it, and
a model-free probe showed Codex stops its tools itself when its stdin closes (engineer report).

Real-host run 3 showed the same for a model turn: after the owner Worker was killed, the app-server saw stdin EOF
and stopped its tool processes itself before the group kill and the reconciling read. So CHECK 2 can legitimately
find nothing to stop (`escaped_processes` empty) while CHECK 3 still shows no `sleep 462` alive. The reclaim
matters when the app-server itself dies without closing its tools (the dev tests and the model-free probe).

### 03: full suite

As 459's step 03, against the Worktree HEAD, six shards, stopped at 25 minutes. Base for comparison: `b3d522ad`.

## Rehearsal without a model (sandbox)

`VERIFY462_NO_MODEL=1 VERIFY462_BASE=$TMPDIR/rh462 VERIFY462_OUT=$TMPDIR/rh462-out`, then `S 00` and `S 02`.
00 stops before Codex and Claude Code. 02 runs `probe.py stub` first: a fake member session and a child record
made through `AgentControl`; a stand-in owner Worker (Python, own session) runs the real descendant sampler on a
stand-in Runtime (Python, own group, the child's marker, like the `codex` launcher), whose readable child in the
same group (like the native app-server, with the marker) starts a real `/bin/zsh -c 'sleep 462; :'` in its own
session. In the stub, the read-only `sleep 462` listing also shows the stand-ins, whose Python code contains that
text; the CHECKs use the record. Not rehearsed: 00's models, logins, host configuration and plugin check, 00u, 01,
Codex's own tool shell, and 03.
