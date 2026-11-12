# 451 real-host check (round 2): a reconciled end is held while the member is idle, and its next run receives it once

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
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for 01's Main. With the member idle, it kills the child's owner and Runtime if alive, then reads twice. Prints `read 1/2: … notification=held` and `HELD-TWICE`, and writes `02-held.json`. Prints the 03 command. |
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

The `claude -p` Main dispatches the member with `swarm`. The member uses only the agents tool. It creates a
Claude child with the instruction `Use the Bash tool once to run exactly: sleep 400 . Then reply DONE-451.`,
replies `CREATE <agent> <execution>` and ends its turn at once (no `wait`). Main runs `probe.py child` (each
call at most 100 s, at most 5 calls) until the member's turn has its terminal record and the child's record
still says `running` with a `runtime_pid` (CHILD-RUNNING). It then stops. It retires nothing.

### 02: the member is idle; the child loses its owner

1. STOP, doing nothing, unless the member's last execution is terminal. A running member's Worker is never
   killed, and the member's Runtime is never touched (a resume after a killed Worker is Task 456).
2. The child's owner is the member's ended Worker (`worker_pid` equals the mapping's). If it is still alive
   (452's daemon=False fix keeps it; that fix is not in this base), SIGKILL it; otherwise print that it
   already exited at the turn end. Then SIGKILL the child's Runtime group if it is alive.
3. Two reads with GraphTraj's receiver, while the member is idle:
   `GraphTrajAgents(project).reconcile_children({alias, member_agent})` from the venv. Each prints the child's
   notification; both must be `held`, with no Runner call (a read never resumes the member).
4. It writes `02-held.json`.

### 03: resume the member normally

The `claude -p` Main calls `agents` `resume` on the member alias with this message:

> Execute agents feature wait with {"agent": "<child>", "timeout_seconds": 60} once. Then reply with every input whose JSON has source graphtraj, verbatim, then REPORT-451-END.

The member's `wait` is a read with a receiver while the member runs, so it claims the held end and the
member receives it once (or its Worker's 15 s sweep does). Main polls `probe.py wait` until the member's
`execution.yml` holds `REPORT-451-END`.

### 04: observe (read only)

1. The child execution is `failed`, with error `owner-exited` and `notification` `delivered` (or `queued`).
2. The project's records hold exactly one distinct notice for that execution, and the member's report holds
   exactly one `failed` input with that execution.
3. It was `held` at both idle reads (`02-held.json`), and is delivered after the member's resumed execution
   started.
4. No killed process and no `sleep 400` process is alive.

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

## Rehearsed in the sandbox without a model (round 2)

Base and output were under `$TMPDIR`.

- 00 with `VERIFY451_NO_MODEL` at the round-2 commit: guard passed, `451 sweep: True 15.0`, `roles OK`,
  `task 1 ready`.
- 02 against a stub Runner state: the test fixture's valid member mapping under the probe's alias, a terminal
  `execution.yml`, core member and child records, and two real stand-in processes (reparented, as a real
  Worker and Runtime are). `probe.py child` printed CHILD-RUNNING; `probe.py kill` killed the stand-in Worker
  ("alive after the turn ended") and the child Runtime group, and the real `GraphTrajAgents(project)` reads
  printed `notification=held` twice and `HELD-TWICE`.
- 04: before any resume, checks 1-3 FAIL and 4 PASS; after a synthetic resume and delivery, ALL PASS.
- 03 with a stub host: the prompt names the real child in the `wait` message; the pid is in `03-main.pid`.

Not rehearsed: the `claude -p` steps 01 and 03, the member's real `wait` and delivery into its turn, and 05.
