# 445 real-host check: idle timed Leader's planned end

Main runs these steps; the user does nothing. Each step: one command, no native dialog
expected. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/445-budget-notice-idle-timed-leader/realhost/`.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/445-budget-notice-idle-timed-leader/scripts/verify-445/steps.zsh 00` | `timer module:` under `~/graphtraj-verify-445/src`, `roles OK`, `task 1 ready`, `result: MODEL OK` with `claude-opus-5-5` in `models`. Prints the 01 command. |
| 01 | Main | `zsh …/steps.zsh 01 2>&1 \| tee …/realhost/01.txt` | About 5 minutes. Ends with the 02 output. |
| 02 | Main | `zsh …/steps.zsh 02` (01 runs it too) | `CRITERION PASS`: `elapsed_minutes:1 delivered= True observer= …team_leader`, its `occurred_at` later than the Leader's last execution end, and Main inbox or Main stream records of `execution-budget-exceeded`. |

What it does:

- 00 builds a scratch venv from the commit under test (`git archive`, editable
  install). It copies click, yaml and websockets out of production `.venv-runtime`
  without changing it. It also builds an isolated project at
  `~/graphtraj-verify-445/project` (git, `graphtraj setup`, a `team_leader` Claude
  role, probe Task 1 with `estimated_minutes.total: 1`, and the Claude host
  configuration). It checks login and model with one `claude -p` line.
- 01 makes a `claude -p` Main in the isolated project the root. It dispatches the
  Leader through `mcp__agents__tasks` (`swarm`). The Leader replies `PROBE DONE`
  and ends its turn. Main then only runs `sleep 100` three times and sends the
  Leader nothing, past the planned end (started_at + 60 s) plus a margin.
- Receiver: the root is this `claude -p` Main, through the Leader's
  `parent_connection`. The Runner records Main's received events under
  `project/.graphtraj/runner/main-sessions/inbox/`, and the Main stream
  (`realhost/01-main-stream.jsonl`) shows what reached Main's input.

Fallbacks are printed next to each check. If the result is `delivered= False`
and the Main stream count is 0, Main had already ended. Report both outputs.

It never touches the user's dotfiles, `~/.claude` or `~/.codex`, and never
prints a key.

Rehearsed in the sandbox without a model: 00's venv, setup and probe
preparation (`roles OK`, `task 1 ready`), and 02's observer on a synthetic
record. Not rehearsed: `claude -p`, the dispatch and the real timer delivery.
