# 449 real-host check: Agent and execution identity in swarm results, notices and task_sessions

Main runs every step except 00u. Each Main command returns within 10 minutes or starts
its work in the background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/449-agent-identity-in-status-notice-swarm/realhost/`.
`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/449-agent-identity-in-status-notice-swarm/scripts/verify-449/steps.zsh`.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | `449 view: True`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5`, `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd ~/graphtraj-verify-449/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once: it starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits up to 9 minutes for that Main to end, then prints one `CHECK PASS/FAIL` line per criterion and `summary: ALL PASS`. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/realhost/03-suite.txt`; done at `== totals:`. |

What it does:

- 00 builds a scratch venv from the commit under test (`git archive`, editable
  install) and copies click, yaml and websockets out of production `.venv-runtime`
  without changing it; it stops unless click is production's 8.5.0 (Conda's 8.2.1
  fails one Pi test, 448). It builds an isolated project at
  `~/graphtraj-verify-449/project` (git, `graphtraj setup`, a `team_leader` Claude
  role, probe Task 1, the Claude host configuration) and checks login and model
  with one `claude -p` line.
- 01: the `claude -p` Main dispatches the member through `mcp__agents__tasks`
  (`swarm`) and prints the raw result. The member uses the `agents` tool to create
  one Claude child (`PONG-449-A`), ends its turn, and on that child's end notice
  sends it once more (`PONG-449-B`). On the second notice it calls `agents status`
  without an Agent and replies with every parent input verbatim, the create and
  send executions and the raw status. Main polls with `probe.py wait` (each call at
  most 100 s, no standalone sleep), then calls `agents status` and `agents retire`
  with the swarm result's `agent`.
- 02 checks:
  1. the swarm result has `agent`, equal to the member's mapping `agent`; the
     member's `task_sessions` node lists the child's Agent reference;
  2. the child has two ended executions; each has exactly one distinct end notice in
     the project's records naming that `execution`, with core `notification:
     delivered`; no notice of the child lacks `execution`; the member's reported
     inputs name the two executions in order;
  3. Main's `agents status` and `retire` by the swarm `agent` succeed.
- 03 builds a suite venv the same way (same Conda Python, click 8.5.0, yaml and
  websockets copied from production) but editable from the Worktree, because
  `tests/conftest.py` requires the venv to resolve the checkout the suite runs
  from. It runs `scripts/run_test_shards.py --shards 6` in its own process group
  and stops that group at 25 minutes. Baseline: 448's run at 2be27dd6 and its
  recheck (448 `adoption/raw/S-suite.txt`, `S-rerun.txt`).

Fallbacks are printed next to each check. It never touches the user's dotfiles,
`~/.claude` or `~/.codex`, and never prints a key. `VERIFY449_BASE`,
`VERIFY449_OUT`, `VERIFY449_NO_MODEL` and `VERIFY449_CLAUDE` (a stub host) exist
for rehearsal only.

Rehearsed in the sandbox without a model (base and output under `$TMPDIR`): 00's
venv (`deps: click 8.5.0`, `449 view: True`), `graphtraj setup` and probe
preparation (`roles OK`, `task 1 ready`); 01 with a stub host (prompt and swarm
arguments written, background start, pid); 02 against the stub stream (FAIL lines,
no crash) and against synthetic records (`summary: ALL PASS`). Not rehearsed: the
real `claude -p` login and plugin check, the dispatch, the member's and child's
model turns, real notice records, and 03 (the suite is Main's to run).
