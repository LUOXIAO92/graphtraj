# verify-553: the candidate concept-clarification guide under 552's four-agent setup

Main runs from this Worktree in Main's own non-sandboxed Bash: `zsh scripts/verify-553/steps.zsh <step>`. No step has a
native dialog. Every step prints its observable and a ready-to-paste next command.

Unchanged from 552: the answer key `scripts/verify-550/design.md`; the texts in `scripts/verify-552/design-552.md`
(U research sentence, the 3 auditor additions); the four S agents (sonnet `claude-sonnet-5-5` high, haiku
`claude-haiku-5-5` high, codex `gpt-6-luna` high, dsh `deepseek-flash` high); U = `claude-fable-5-2` high; A =
`claude-sonnet-5-5`; MAX_EXCHANGES 6; the DONE rule; 3 runs per agent per scenario (48 runs); all of 552's isolation
measures and probes; the DSH relay `scripts/verify-552/mcp_tasks_only.py`. `drv553.py` and `stub553.py` are copies of
552's files with the tags renamed (552 → 553); `diff scripts/verify-552/drv552.py scripts/verify-553/drv553.py` shows
every other change, each marked `553:` in a comment.

| step | dialog | observable that proves it |
|---|---|---|
| `V [commit]` | none | `candidate commit: <full id>`; `graftling dev <id> -> <wheel>`; `venv imports: graphtraj <venv>/lib/... \| graftling 0.6.2 <venv>/lib/...`; one `MATCH manuals/<path> <sha256>` per manual file of the commit (no `DIFF`/`EXTRA`); `production .venv-runtime guide sha256: before X, after X (unchanged)`; `CHECK 553 V: PASS`. Default commit: the Worktree's HEAD. Built from `git archive <commit>`, never the working tree. |
| `00` | none | Versions (claude, codex printed and not refused if newer; `dsh ... (expected 0.2.2-rc.5: yes)`). Project set up with the candidate venv. `candidate guide manual_ref: <venv>/share/...`, `sha256`, `prod_sha256`, `new_line`. `codex: Logged in ...`, `DEEPSEEK_API_KEY: set`. `CHECK 553 READY-553-U/A: PASS`, each with `init model`. `CHECK 553 codex sandbox: PASS`, `CHECK 553 dsh sandbox: PASS`. Per agent: `probe (a) describe + guide read`, `probe (a) manual_ref under the candidate venv + candidate text read`, `probe (b)` lines (BASE/u, u/research, logs, sibling ws, candidate venv task-delivery guide, production task-delivery guide, design.md, listing), `probe (c)`, `probe (d) READY`, `CHECK 553 READY-553-S-<agent>: PASS`. `summary`: `<agent>: PASS (R allowed)` or FAIL (blocks that agent; Main reports it to the Leader). |
| `P <agent>...` | none | As 00 for only those agents (re-probe after a correction). |
| `F` | none | `S#: <552 realhost/u-research/S#.md> sha256 X -> BASE/u/research/S#.md sha256 X` for S1-S4 (same hash on both sides). |
| `R <agent\|all> <S#\|all> [runs=3] [cap=8]` | none | `batch started`; `BASE/logs/R-batch-*.out` lists the run ids and `<run> ended rc=0`; each `logs/<run>/driver.log` has one `turn NN ...` line per turn and ends with `END {...}`. |
| `W` | none | Per run `ended {...} \| audit: ...`, `running` or `queued`; `runs: N known, E ended, A audited`. |
| `A <agent\|all\|run id> [cap=8]` | none | `audits started`; first line of `logs/<run>/audit.md` is `AUDIT: CLEAN`, `CHEATED` or `UNCLEAR`. |
| `C` | none | `<run>: copied -> <Worktree>/.state/realhost/<agent>/<S#>-r<k> \| ok \| audit: ...` (552 layout: `digest.md`, `logs/`, `S-final-files/`, `audit.md`, dsh `dsh-session-store/`), `u-research/`, `step-logs/`, `runs-table.md`, `candidate.txt` (commit + guide sha256). |
| `T` | none | `.state/realhost/compare-552.md`: per run, 552 vs 553 exchanges, DONE, AUDIT verdict, first edit vs first question, guide / other out-of-ws reads; then per agent and scenario counts `552 -> 553`. No judgment (K0a-K6 stay with the Leader). |
| `G [pytest args]` | none | No args: full suite of HEAD, 6 shards, background, `started in the background`; output `.state/realhost/G-<sha>-<time>/suite.txt` ending `exit=N`. With args: plain pytest on them, foreground, `N passed` and `exit=0`. Both print `pytest temp: TMPDIR=... (outside the Harness)` and the graftling dev commit. |
| `Gt` | none | Focused tests `tests/test_gateway.py tests/test_wheel_installation.py`: `N passed`, `exit=0`, `(no FAILED/ERROR lines)`. |
| `GR` | none | Newest G and Gt; every FAILED/ERROR line `known (554 ...)`, `known (516)` or `NEW`. Known lists: Task 554's integrated G `G-a19d75b3-20261121T222317/suite.txt` (the latest integrated full suite: 1 failed, the 516 item-6 test) and Task 516's `task.md`. |

Order: `V` → `00` → `F` → `R all all` → `W` (repeat) → `A all` → `W` → `C` → `T`; `G` → `Gt` → `GR` any time after
V. Main saves the raw output of each step.

## Differences from 552 (Leader brief (a)-(i))

- **(a) Step V.** `<H>/tmp/553/venv` is a plain venv (no system site-packages, as production) holding the graphtraj
  wheel built from `git archive <commit>` and the graftling wheel built from `git archive` of graftling `dev`, plus
  production's click/yaml/websockets copied (read only; no PyPI on this host). `<H>/.venv-runtime` is only read.
- **(b) Candidate MCP.** BASE=/private/tmp/cc-553. The scratch project is set up and Claude-host-configured with the
  candidate venv. Every S's MCP server is `<venv>/bin/graphtraj-mcp` (claude `--mcp-config`, codex
  `mcp_servers.graphtraj.command`, dsh relay argument). `manual_dir()` stops if manual_ref is not under the venv.
  New probe (a) line: the describe result names the candidate manual_ref, and a read result holds the first line
  of the candidate guide that production's guide lacks (`drv553.py guide` prints it with both sha256 values).
- **(c) Reads outside the ws.** claude: unchanged mechanism (`deny_except` of the whole workspace tree down to the
  candidate concept-clarification directory: every sibling, including `.venv-runtime` and the other manual
  directories, is denied). codex: unchanged (the profile grants only the guide directory). dsh: the outer profile
  no longer re-allows `$H/.venv-runtime`; layer 2 re-allows only `<venv>/bin`, `<venv>/lib`, `<venv>/pyvenv.cfg`
  (what the MCP child executes), and layer 4 re-allows the concept-clarification directory. Every layer names the
  same operations (`file-read-data file-read-xattr`), as 552 correction 2 requires. New canaries for every agent
  and in both no-model gates: the task-delivery guide of the candidate venv and of production (read refused, its
  heading `# Task Delivery` absent from S's output).
- **(d) DSH 0.2.2-rc.5.** 00/P print the expectation. The session-record parser was checked on a real rc.5 record
  (below). claude/codex versions are printed, never refused.
- **(e) F** copies 552's retained notes instead of new research; U's input is identical to 552's. U still has
  WebSearch/WebFetch as in 552.
- **(f) C** as 552 (into this Task's `.state/realhost/`); **T** writes `compare-552.md`.
- **(g) G/Gt/GR** as verify-531, with graftling dev and pytest TMPDIR outside the Harness.

## Rehearsal (`zsh scripts/verify-553/rehearse.zsh <empty dir>`, output in `rehearsal/`)

Run from an empty directory under `$TMPDIR` (Harness `tmp/` is not writable in the Engineer sandbox) through the same
`zsh steps.zsh <step>` entry: usage, 00 (refused before V), V, 00, P codex dsh, F, W, R all all 1 8 (16 runs), W,
A all, W, C, T, and `G tests/test_gateway.py tests/test_wheel_installation.py`.

- **Stub (`stub553.py`, first on PATH):** every model; `claude`, `codex`, `dsh` themselves; their permission
  enforcement (probe refusals end in `(stub)`), `curl`, Codex's Seatbelt in `codex sandbox` and the outer
  `sandbox-exec` around dsh (the stub evaluates the profile's rules for cat/ls/pwd and dsh's `--patch`, last match
  deciding, with 552's observed precedence; it is not Seatbelt). Not proved by the rehearsal: any real deny rule,
  Seatbelt profile or network block, any real model's behaviour.
- **Real in the rehearsal:** step V (both wheels from `git archive`, the venv, the sha256 comparison, production
  guide unchanged); the candidate venv's `graphtraj setup` and Claude host configuration; each S's
  `tasks describe concept-clarification` as a real tools/call to the candidate `graphtraj-mcp` (dsh: through the real
  relay), so probe (a)'s manual_ref and candidate line come from the real server and file; F's copy and hashes;
  the relay loop, audits folders, C, T against 552's real records; and a real pytest run through `steps.zsh G`.
- **Real, outside the stubbed rehearsal (Engineer, no paid model):** `rehearsal/real-dsh-rc5-boot/`: the real
  `dsh 0.2.2-rc.5` booted headless with the run's patch shape, a fake key and no network (turn ended `TRANSPORT`).
  Its MCP row connected through the relay to the candidate venv's `graphtraj-mcp`. Its session record's
  `request/header.tools` are `{name, description, parameters}` objects; `drv553.parse_dsh` reads them
  (`parse_dsh-output.txt`: tools = create_goal, edit, get_goal, glob, grep, list_mcp_resource_templates,
  list_mcp_resources, mcp__graphtraj__tasks, read, read_image, read_mcp_resource, todo_write, update_goal,
  working_directory, write; model deepseek-flash; effort high). The real Seatbelt (codex sandbox, the dsh outer
  profile) cannot run inside the Engineer's own sandbox (`sandbox_apply: Operation not permitted`, 552 README) and is
  proved only by Main's 00.
