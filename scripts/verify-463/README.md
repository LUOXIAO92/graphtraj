# 463 real-host check: a killed owner's DSH child leaves no tool process after reconciliation

Main runs every step. No step needs the USER, unless 00 stops on a missing key variable or 02 shows an unanswered
approval (see below). Each command returns within 10 minutes or starts its work in the background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/463-dsh-child-tool-process-reclaim/realhost/`
(`…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/463-dsh-child-tool-process-reclaim/scripts/verify-463/steps.zsh`.

The base is `~/graphtraj-verify-463`, a new path. No other verify directory is touched.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `463 fix: dsh owner samples: True \| sets the marker: True \| dsh driver records it: True \| agents driver records dsh: True`, `deps: click 8.5.0`, a `dsh role (from …)` line with your model and connection, `key variable (name only): …`, `roles OK`, a `dsh:` version line and `set in this shell: yes` (or `none (DSH login)`). Prints the 01 command. |
| 00k | USER, only if 00 prints `STOP: the dsh role's key variable … is not set` | Tell Main which shell or file holds that variable; Main reruns 00 from a shell that has it. The value is never printed. | 00 passes. |
| 01 | Main | `S 01` | Returns at once. It starts the probe owner in the background, prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 8 minutes for `CHILD-READY`, refuses (`STOP`, signals nothing) unless the child's descendants record lists a live setsid'd `/bin/sleep 4632`, SIGKILLs only the owner, prints `RESIDUE … still alive: [(<pid>, <pid>, '/bin/sleep 4632')]`, does one reconciling read, prints four `CHECK` lines and `summary: ALL PASS`, writes `02-kill.json`. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/03-suite.txt`. Done when the file shows `== totals:`. |

## What each step does

### 00: preflight

A scratch venv from the commit under test (`git archive`, editable install), click 8.5.0, yaml and websockets copied
read-only from production `.venv-runtime`, and one line proving the fix is in that venv. An isolated project with
`graphtraj setup` and one role, `dsh`, copied unchanged from this project's `.graphtraj/roles.yml` (the role named
`dsh`, or the only role with `runtime: dsh`): your connection (resolved from `~/.graphtraj/connections.yml`) and
model, so the child uses the DSH connection and model you configured. Only the name of the role's key variable is
printed and passed to the steps' child commands; its value is never printed. The DSH version line comes from the
installed `dsh`. The model answers for the first time in 01.

### 01: the owner and its DSH child

The probe owner is one Python process of the scratch venv. Through GraphTraj's own agents control
(`GraphTrajAgents(project).control`, the path a member's agents tool uses) it creates one DSH child with:

`Use the Bash tool exactly once to run exactly this command, unchanged: /usr/bin/perl -MPOSIX -e 'setsid(); exec "/bin/sleep","4632"' & /bin/sleep 4631`

and keeps owning it. DSH starts the tool detached (its own session and group). The tool's `perl` calls setsid and
becomes `/bin/sleep 4632`, outside every group DSH or GraphTraj knows; `/bin/sleep 4631` stays in the tool's group.
The owner log is `…/realhost/01-owner.log`; it prints `CREATED <agent>`.

Approvals: the child's `permission` preset is `approval: ask`. If DSH asks before running the command, no native
dialog appears (`dsh web` runs headless and the request goes to the child's parent). The owner answers `allow` only
for a request whose command holds both `4632` and `4631`, and logs `APPROVAL answered allow …`. Any other request is
left unanswered and logged; then 02 stops at `NOT READY` and signals nothing.

### 02: kill, residue, one read, the checks

`probe.py ready` waits until the child is `running` and its `tool_descendants` record lists a live `/bin/sleep 4632`
that leads its own process group. `probe.py kill` refuses (`STOP`, signals nothing) unless that holds, the child's
`worker_pid` is the owner's pid, and `tool_marker` is recorded. It prints the record's entries, then:

1. SIGKILLs the owner only (pid and start time checked right before);
2. waits up to 30 s for `dsh web` to end: its watcher sends SIGINT, and DSH then stops the tool's group itself. Only
   if `dsh web` is still alive after 30 s is its recorded group SIGKILLed (and the line says so);
3. **prints `RESIDUE after the kill, before reconciliation: recorded descendants still alive`**: the evidence that
   DSH's own shutdown leaves the setsid'd sleep (Task requirement 1 on the real host);
4. starts three bystanders of its own, each in its own session: Python with a different random
   `GRAFTLING_MEMBER_RUN`, Python without it, and a `/bin/sleep 901`;
5. does one reconciling read (`control.unconfirmed_ends(<child>)`, as `GraphTrajAgents.reconcile_children` does);
6. prints `CHECK` 1 (child `failed`/`owner-exited`), 2 (`escaped_processes` stopped every survivor, `remaining`
   empty, no `error`), 3 (none of the recorded identities alive) and 4 (the three bystanders alive);
7. stops only its own bystanders.

### 03: full suite

As 459's step 03, against the Worktree HEAD, six shards, stopped at 25 minutes.

## Rehearsal without a model (sandbox)

`VERIFY463_NO_MODEL=1 VERIFY463_BASE=$TMPDIR/rh463 VERIFY463_OUT=$TMPDIR/rh463-out VERIFY463_DEPS=<site-packages with
websockets>`, then `S 00` and `S 02`. 00 uses a stand-in role (`deepseek-flash`, no connection) and stops before
DSH. 02 runs `probe.py stub` first: a child record made through `AgentControl`, and a stand-in owner (Python, own
session) running the real descendant sampler on a stand-in `dsh web` (Python, own session, the child's marker). The
stand-in starts the exact tool command in a real `/bin/zsh -c` in its own session and stops that group when its
owner dies, as DSH does. Rehearsed 2026-11-14 00:00: `RESIDUE … [(…, …, '/bin/sleep 4632')]` and
`summary: ALL PASS`. Not rehearsed: copying production's deps, the real `dsh web`, its watcher, the model, an
approval, and 03.
