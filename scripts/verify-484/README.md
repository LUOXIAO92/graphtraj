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
| 00 | Main | `S 00` | none | 300 + 300 + 300 + 60 s (codex ask, claude ask, codex MCP, proxy) + install ≈ 120 s | `under venv: True`; `codex logged in: YES`; both `answer: OK` with `loaded: none`; `roles OK`; `task 1 ready`; `project own: True`; two `MCP … -> OK`; `create schema served: YES`; `task_graph shows probe Task 1: YES`; `app-server proxy thread/loaded/list: YES` (a connect failure is allowed here, see the note it prints); `claimed Main in $P: YES` |
| 00u | USER, only if 00 says so | printed | Codex folder trust → Yes, hooks → approve; Claude folder → Yes, project MCP → approve | user | 00 then passes |
| I1 | USER | `S I1` prints the command and one prompt | Codex folder trust → Yes and hooks → approve, only if asked | user ≈ 300 s | TUI prints `H484-CREATE …`, later a turn by itself with `H484-NOTICE …`; Codex kept open |
| I2 | Main, Codex still open | `S I2 2>&1 \| tee OUT/I2.txt` | none | 60 s (proxy) | `PASS Main thread loaded in the shared background server`; `NOTIFICATION … delivered \| notification_error null`; `PASS 401 interactive delivered once` |
| S | Main | `S S 2>&1 \| tee OUT/S.txt` | none | 1800 s | `outside the Harness …: YES`; pytest summary with no new failures; `pytest exit: 0` |
| F | Main | `S F 2>&1 \| tee OUT/F.txt` | none | none (read only) | `PASS F production Main`; `PASS F production .venv-runtime unchanged`; PASS/FAIL summary |

Main's run-time estimate (sum of limits): 00 ≤ 1080 s + I1 ≈ 300 s (user) + I2 ≤ 60 s + S ≤ 1800 s = **≤ 3240 s ≈ 54 min**
worst case; each host call returns when done, so typically far less (00 a few minutes, S the suite's own duration).

## What each step observes
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
- **S**: the full suite of the Worktree checkout in `tmp/484/venv-test` (editable install of the checkout), with
  pytest's temporary directory outside the Harness.
- **F**: Harness continuity last claim == 00's; production `.venv-runtime` graphtraj/graftling RECORD hashes == 00's.

## Rehearsal without models
`VERIFY484_NO_MODEL=1 VERIFY484_BASE=<dir outside the Harness> VERIFY484_OUT=<dir>/out S 00` installs the candidate venv,
writes the project and stops before any model or host call; `S I1`, `S I2` (fails at the entry check without a claim),
`S S` (prepares the test venv, does not run the suite) and `S F` run as well.
