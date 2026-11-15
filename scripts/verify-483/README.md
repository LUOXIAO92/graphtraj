# 483: 373 and 401 with Codex as Main (recheck of 444's unobserved items)

`S` = `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/483-codex-main-373-401-recheck/scripts/verify-483/steps.zsh`.
Evidence `OUT`: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/483-codex-main-373-401-recheck/realhost/`.
Fresh isolated project `$P` = `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/483/project` (own git repo; never
`tmp/444`, whose probe Task was budget-stopped). Production `.venv-runtime` first on PATH; Codex model `gpt-6-luna`.
Trimmed from `scripts/verify-444` (Codex-Main checks only). The probe Task 1 is new: budget total 120 min,
planned_sessions asker 3 / advisor 3.

| Step | Who | Command | Dialog | Wait limit | Success line(s) |
|---|---|---|---|---|---|
| 00 | Main | `S 00` | none | 3 × 300 s (codex ask, claude ask, codex MCP) | `codex logged in: YES`; `codex answer: OK` and `claude answer: OK`, each `Harness instruction file loaded: none`; `roles OK`; `task 1 ready`; `project own: True`; two `MCP … -> OK`; four `create schema key … YES`; `task_graph shows probe Task 1 ready: YES`; `app-server proxy … YES`; `claimed Main in $P: YES` |
| 00u | USER, only if 00 says so | printed | Codex folder trust → Yes, hooks → approve; Claude folder → Yes, project MCP → approve | user | 00 then passes |
| A1 | Main | `S A1` | none | returns at once | background `codex exec` Main: creates root Agent `h401`, swarms the asker, denies every request |
| A2 | Main | `S A2 2>&1 \| tee OUT/A2.txt` | none | 540 s | `PASS A entry`, `PASS 373[A1] (a)…(d)`; `AGENT h401 id …` + `NOTIFICATION …`; starts the `exec resume` turn |
| A3 | Main | `S A3 2>&1 \| tee OUT/A3.txt` | none | 300 s | one `401-EXEC:` line (delivered / EXEC-NO-CHANNEL / POSSIBLE LOSS / NOT SETTLED) |
| I1 | USER | `S I1` prints the command and one prompt | Codex folder trust → Yes and hooks → approve, only if asked | user ≈ 5 min | the TUI prints `H401I-CREATE …`, later a turn with `H401I-NOTICE …` |
| I2 | Main | `S I2 2>&1 \| tee OUT/I2.txt` | none | none (read only) | `PASS 401 interactive delivered once` |
| F | Main | `S F 2>&1 \| tee OUT/F.txt` | none | none | `PASS F production Main`, every pid `ended`, summary |

Main's run-time estimate (sum of limits): 00 ≤ 900 s + A2 ≤ 540 s + A2's resume start 0 s + A3 ≤ 300 s + I1 ≈ 300 s
(user) = **≤ 2040 s ≈ 34 min** worst case, typically far less (each host call returns when done).

## How each check is observed
- **373** (`probe.py requests`, 444's logic): ≥ 2 distinct request ids of the asker reached the Codex Main (its stream's
  tool results/host events, model text and tool-call arguments excluded), each with a reply result `reply_status:
  submitted`; the asker's native records show both touch calls refused; `tmp/483/373-codex-a` and `-b` absent.
- **401, exec form** (A2/A3): `probe.py agent` prints h401's control record **before** any pull; graftling sets
  `notification` after the push attempt (`src/graftling/control.py:510-538`: delivered / unconfirmed / held /
  unavailable). `probe.py ends` counts deliveries by event identity in the A1 and A3 streams. A3 classifies.
- **401, interactive form** (I1/I2): the Codex thread is the codex continuity claim made after I1 started;
  `probe.py rollout` reads that thread's rollout under `~/.codex/sessions` (read only) and counts model-input records
  (`response_item`) carrying h401i's agent id + execution id + end outcome; tool results (status/wait pulls) are listed,
  not counted. The I1 prompt forbids status/wait for h401i.
- **F**: Harness continuity last claim == 00's; every pid the scripts started has ended.

## Why exec may have no receiving channel (source)
- Codex is a push Main, not a queued one: `src/graphtraj/execution/main_continuity.py:241-246` (`QUEUED_RUNTIMES` =
  claude, pi, dsh).
- A root Agent's end for a Codex Main is pushed once by `src/graphtraj/interfaces/agents.py:289-311`
  (`send_host_event`), i.e. `src/graphtraj/runtimes/codex/host_events.py:160-229`: a `codex app-server proxy` connection
  to the daemon for `CODEX_HOME`, `send_host_event(thread, event)`. A failure is recorded only in the control record
  (`control.py:526-531` → `unconfirmed`), never queued or retried.
- The Codex hand-over/receipt paths do not cover it: `main_continuity.py:443-491` and
  `runtimes/codex/display_hook.py:22-40` handle Runner Session receipts (`parent-notices.jsonl`, `delivery:
  retained`), not agents-tool Agents' ends.
- So a `codex exec` Main whose process has ended has no channel unless a daemon holds its thread; `exec resume` sees
  the end only by a `status` pull. A3 prints which case occurred.

## Rehearsal without models
`VERIFY483_NO_MODEL=1 VERIFY483_BASE=… VERIFY483_OUT=… S 00` stops before any model or host call.
