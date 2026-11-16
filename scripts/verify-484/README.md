# 484: 401 for an interactive Codex Main on Codex's shared background server

`S` = `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/484-codex-main-root-agent-end-delivery/scripts/verify-484/steps.zsh`.
Evidence `OUT`: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/484-codex-main-root-agent-end-delivery/realhost/`.
Fresh isolated project `$P` = `tmp/484/project` (own git repo, so Codex and Claude read no Harness AGENTS.md/CLAUDE.md).
The candidate (the Worktree's committed HEAD, printed by 00) is installed into `tmp/484/venv`; its dependencies are
symlinked read-only from production `.venv-runtime` (graphtraj/graftling excluded), which is never changed (F checks
its RECORD hashes). The project's `.codex/config.toml` names `tmp/484/venv/bin/graphtraj-mcp`; `.codex/hooks.json`
names the venv's Python. Codex model `gpt-6-luna`. Production Main is never yielded (F checks).

| Step | Who | Command | Dialog | Wait limit | Success line(s) |
|---|---|---|---|---|---|
| 00 | Main | `S 00` | none (no project trust or Main claim needed) | 60 s (MCP entry) + 300 + 300 s (codex ask, claude ask) + 60 s (proxy) + install ≈ 120 s | `under venv: True`; `roles OK`; `task 1 ready`; `project own: True`; `MCP initialize: OK`; `graphtraj tools agents and tasks served: YES`; `task_graph shows probe Task 1: YES`; `codex logged in: YES`; both `answer: OK` with `loaded: none`; `app-server proxy thread/loaded/list: YES` (a connect failure is allowed here, see the note it prints) |
| I1 | USER (the only one) | `S I1` prints the command and one prompt | Codex's first-launch trust for the fresh project, shown together at first start: folder trust → Yes, then hook review for `.codex/hooks.json` → approve; no other dialog | user ≈ 300 s | TUI shows `GraphTraj Main Session associated`, prints `H484-CREATE …`, later a turn by itself with `H484-NOTICE …`; Codex kept open (if the association line or the tool is missing after trusting: /exit, run the same command once more) |
| I2 | Main, Codex still open | `S I2 2>&1 \| tee OUT/I2.txt` | none | 60 s (proxy) | `PASS Main thread loaded in the shared background server`; `NOTIFICATION … delivered \| notification_error null`; `PASS 401 interactive delivered once` |
| S | Main | `S S 2>&1 \| tee OUT/S.txt` | none | 1500 s (self-limit; stops the process group) | `outside the Harness …: YES`; totals tail and `leftover processes …` line; `failures.txt (0)`; `PASS S no new failures (baseline had none)` |
| F | Main | `S F 2>&1 \| tee OUT/F.txt` | none | none (read only) | `PASS F production Main`; `PASS F production .venv-runtime unchanged`; PASS/FAIL summary |

Main's run-time estimate (sum of limits): 00 ≤ 840 s + I1 ≈ 300 s (user) + I2 ≤ 60 s + S ≤ 1500 s = **≤ 2700 s ≈ 45 min**
worst case; each host call returns when done, so typically far less (00 a few minutes, S the suite's own duration).

## What each step observes
- **MCP entry (00 b)**: `probe.py mcp` starts the server exactly as `$P/.codex/config.toml` names it (command, args,
  cwd) and makes initialize, tools/list and one read-only `tasks` `task_graph` call; no model and no trust involved.
- **Cause (I2 first line group)**: `probe.py daemon` makes one read-only `thread/loaded/list` call through
  `codex app-server proxy`, the same channel `send_event` uses (`src/graphtraj/runtimes/codex/host_events.py`), and
  says whether the Main's thread is loaded in the shared background server for its `CODEX_HOME`. If it is not,
  Codex ran that Session without the shared server and a push cannot reach it (`thread not found`).
- **Push result**: `probe.py agent` prints the control record's `notification` and, new in 484, `notification_error`
  (`code`, `message`) kept when the push raised (`src/graftling/control.py`, `ExecutionEvents.finished`).
- **401, exactly once**: `probe.py rollout` reads that thread's rollout under `CODEX_HOME/sessions` (read only) and
  counts model-input records (`response_item`, not model-written) carrying the pushed event (`"source": "graphtraj"`,
  the agent id, the execution id and the outcome). Host echo records (`event_msg`) and tool results without the event
  (status/wait/create pulls) are listed, not counted. PASS needs exactly 1 and `notification: delivered`.
- **S**: the full suite of the Worktree checkout in `tmp/484/venv-test` (editable install of the checkout), run as
  `scripts/run_test_shards.py --shards 6 --log-dir OUT/S-shards` (pytest temp outside the Harness) under a 1500 s limit
  that stops the whole process group. Compared with dev a3fe1b92's record (Task 478 `adoption/raw-a3fe1b92/S-suite.txt`:
  0 failed / 4128 passed / 69 skipped; base 6160ed7a = a3fe1b92 + AGENTS.md only): PASS needs shards exit 0 and an
  empty `failures.txt`.
- **F**: Harness continuity last claim == 00's; production `.venv-runtime` graphtraj/graftling RECORD hashes == 00's.

## Rehearsal without models
`VERIFY484_NO_MODEL=1 VERIFY484_BASE=<dir outside the Harness> VERIFY484_OUT=<dir>/out S 00` installs the candidate venv,
writes the project, runs the MCP entry check (b) and stops before any model or host call; `S I1`, `S I2` (fails at the entry check without a claim),
`S S` (prepares the test venv, does not run the suite) and `S F` run as well.
