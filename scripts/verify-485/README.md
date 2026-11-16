# 485: the interactive Codex Main's completion check fails with "failed to load workspace requirements"

`S` = `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/485-codex-main-completion-check-workspace-requirements/scripts/verify-485/steps.zsh`.
Evidence `OUT`: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/485-codex-main-completion-check-workspace-requirements/realhost/`.
Fresh isolated projects `$P` = `tmp/485/project` (I1, R) and `$P2` = `tmp/485/project2` (R3), each with its own git repo
(Codex reads no Harness AGENTS.md), `graphtraj setup`, `.codex/hooks.json` and the graphtraj MCP entry in `.codex/config.toml`.
The candidate (the Worktree's committed HEAD, printed by 00) is installed into `tmp/485/venv`; its dependencies are
symlinked read-only from production `.venv-runtime`, which is never changed (F checks its RECORD hashes).
Codex model `gpt-6-luna`. Production Main is never yielded (F checks).

| Step | Who | Command | Dialog | Wait limit | Success line(s) |
|---|---|---|---|---|---|
| 00 | Main | `S 00` (writes `OUT/00.txt` itself) | none | 60 s (MCP) + 300 s (codex exec) + 60 s (proxy) + install | `under venv: True`; `roles OK`; `task 1 ready`; both `project own: True`; `MCP initialize: OK`; `graphtraj tools agents and tasks served: YES`; `task_graph shows probe Task 1: YES`; `codex logged in: YES`; `codex answer: OK` (model line is not the prompt echo) with `loaded: none`; `app-server proxy thread/loaded/list: YES` |
| E | Main, read only | `S E 2>&1 \| tee OUT/E.txt` | none | none | 484's failed check printed: `outcome`, `error`, `configuration`, `parent_configuration`, `authorized_difference`, trace error lines, Codex log lines naming `requirements` |
| R | Main, no user | `S R 2>&1 \| tee OUT/R.txt` | none | per project 960 s (each turn 180 s) | per project `[<label>] REPRODUCED (<cases>)` or `[<label>] NOT reproduced`, with each case's status and verbatim error |
| I1 | USER (the only one) | `S I1` prints the command and the prompt | first launch: folder trust → Yes, hook review → approve | user ≤ 10 min | reply `H485-DONE`, then the Stop hook's `Completion Check · …` lines; user copies them to Main; Codex kept open |
| I2 | Main, Codex still open | `S I2 2>&1 \| tee OUT/I2.txt` | none | 60 s (proxy) | `PASS Main thread loaded in the shared background server`; `PASS I2 completion check reached a conclusion` |
| S | Main | `S S 2>&1 \| tee OUT/S.txt` | none | 1500 s (stops the process group) | `nested venv imports: OK`; `test venv imports the checkout: OK`; `outside the Harness …: YES`; `PASS S no new failures` |
| F | Main | `S F 2>&1 \| tee OUT/F.txt` | none | none | `PASS F production Main`; `PASS F production .venv-runtime unchanged` |

## What each step observes
- **E**: `probe.py evidence` reads `tmp/484/project/.graphtraj/runner/main-sessions/finalize_*/checks/*/`
  (`main_finalize.session_binding`/`bind_checker`): `session.yml`, `execution.yml` (the fork's `configuration`,
  `parent_configuration`, `authorized_difference`, `outcome`, `error`) and error lines of the retained `events.jsonl`;
  then lines naming `requirements` in `CODEX_HOME/log/*` (read only).
- **R**: `probe.py repro` connects exactly as the checker does (`finalize.proxy`: `codex app-server proxy --sock
  <control socket>` on the shared server), starts a Main-like thread (model and cwd only) and one trivial turn, then
  R1 = `fork_session(parent, network_profile=graphtraj_checker, unix_socket=<control socket>)` with the checker's own
  `start_execution` + `wait`; R2 = the same fork without profile/socket; R1b = R1 while a base turn is in progress (as
  at Stop). Done in `$P` (R), `$P2` (R3, a second fresh project) and `tmp/484/project` (R4, where it was seen).
  Fork requests/responses are printed (`->`/`<-`). The base thread is archived; forks are ephemeral. R can be rerun
  after I1, when `$P` is trusted.
- **I2**: the codex continuity claim since I1, whether that thread is loaded in the shared server, and the newest
  retained check: PASS when its outcome is `completed` with a checker status (`completed`/`waiting`/`actionable`).

## Rehearsal without models
`VERIFY485_NO_MODEL=1 VERIFY485_BASE=<dir outside the Harness> VERIFY485_OUT=<dir>/out VERIFY485_P484=<stub> S 00`
installs the venv, writes both projects and checks the MCP entry; `S E`, `S R` (prints, no host call), `S I1`, `S I2`,
`S S` (prepares the test venv only) and `S F` run as well. `probe.py repro` was also rehearsed against a stub
`codex app-server proxy` peer.
