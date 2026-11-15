# 444: unattended Main-swap checks (Codex, Pi, DSH as Main; Pi member)

`S` = `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/444-unattended-main-swap-checks/scripts/verify-444/steps.zsh`.
Evidence: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/444-unattended-main-swap-checks/realhost/` (`…/realhost`).
Isolated project: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/444/project` (`$P`), production `.venv-runtime` first on PATH.

The production Claude Main is never yielded, exited or reconfigured. Each probe Main runs only in `$P`, so its
continuity claims and notice queues are `$P/.graphtraj/runner/main-sessions/`, not the Harness's. Step F proves the
Harness's last continuity claim is the same one 00 recorded.

| Step | Who | Command | Dialog | Success line(s) |
|---|---|---|---|---|
| 00 | Main | `S 00` | none | 4 × `answered: YES`, `Harness instruction file loaded: none`, `codex logged in: YES`, `roles OK`, `task 1 ready`, `project own: True`, `graphtraj-claude-host loaded: YES`, `pi sandbox missing: nothing`, `dsh GraphTraj plugin: YES` |
| 00u | USER, only if 00 says so | printed by `S 00u` | trust dialogs (Claude folder + MCP, Codex folder + hooks, Pi folder) | 00 then passes |
| B1 | Main | `S B1` | none | returns at once (background `claude -p` Main creates root agent h397, 90 s) |
| B2 | Main | `S B2 2>&1 \| tee …/realhost/B2.txt` | none | `PASS 397 precondition` (`QUEUED` h397 end for the exited Claude Main) |
| C1 | Main | `S C1` | none | returns at once (background `codex exec -m gpt-6-luna` Main) |
| C2 | Main | `S C2 2>&1 \| tee …/realhost/C2.txt` | none | `PASS C entry`, `PASS 397`, `PASS 373[C1] raised/answered/member saw answers`; starts the resume turn |
| C3 | Main | `S C3 2>&1 \| tee …/realhost/C3.txt` | none | `PASS 401` |
| P1 | Main | `S P1` | none | returns at once (background `pi --print` Main with GraphTraj's Pi extension) |
| P2 | Main | `S P2 2>&1 \| tee …/realhost/P2.txt` | none | `PASS P entry`, `PASS 373[P1] …` |
| E1 | Main | `S E1` | none | returns at once (background Claude Main dispatches role `pi_member`) |
| E2 | Main | `S E2 2>&1 \| tee …/realhost/E2.txt` | none | `PASS 425` |
| D1 | Main | `S D1 2>&1 \| tee …/realhost/D1.txt` | none | `PASS 398 part 1` (≤ 9 min) |
| D2 | Main | `S D2 2>&1 \| tee …/realhost/D2.txt` | none | `PASS 398 part 2` |
| D3 | Main | `S D3 2>&1 \| tee …/realhost/D3.txt` | none | `PASS 373[D3x] …` |
| F | Main | `S F 2>&1 \| tee …/realhost/F.txt` | none | `PASS F production Main`, every pid `ended`, PASS/FAIL summary |

How each check is observed (records, not a model's self-report alone):
- **373**: the asker role is Claude with `permission_mode: default` (393 risk: `auto` may never ask). `probe.py
  requests` counts distinct request ids for the asker in the Main's notice queues (Claude/Pi/DSH Mains) or in the
  Main's stream (Codex host events / tool results); ≥ 2 required, a `deny` reply per id, and the asker's records show
  the denials.
- **397**: B2 sees h397's end queued and undelivered for the exited Claude Main; C2 sees a `codex` continuity claim,
  the Claude queue cursor past it (delivered), duplicate ids 0, and `H397-COUNT 1` in the Codex Main's session-start notices.
- **398**: D1 sees g398's end queued and undelivered after headless DSH exits; D2 sees `G398-COUNT 1` on `--session-id` resume.
- **401**: h401's end appears exactly once across the Codex Main's turn and its resume turn.
- **425**: E2 checks the Pi member's reply carries README.md's first line, and that no session record under its
  directory is marked missing (plus the Main's `session_read` line `E-MISSING`).
- **F**: Harness `.graphtraj/runner/main-sessions/continuity.jsonl` last claim == the one 00 printed.

Rehearsal without models: `VERIFY444_NO_MODEL=1 VERIFY444_BASE=… VERIFY444_OUT=… S 00` stops before any model.
