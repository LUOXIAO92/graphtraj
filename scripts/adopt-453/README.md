# 453 production adoption: dev cfd5e432 (449, 450) and 449's production check

`steps.zsh` installs the wheels built from `git archive cfd5e432` into production
`.venv-runtime`. Production has 448's 2be27dd6 now. The steps and protections are
448's: an isolated real-Claude rehearsal (Vc), file-by-file equality (`proddiff.py`),
a backup with rollback (R), and no member running at install time. The versions do
not change (graphtraj 0.1.0, graftling 0.5.0 in both pyproject files), so versions
prove nothing. Every install claim comes from `proddiff.py`.

Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/453-production-adoption-449-450/scripts/adopt-453/steps.zsh`
Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/453-production-adoption-449-450/adoption/raw/`
Base: `~/graphtraj-adoption-453` (backup at `backup/`). The 393, 417 and 448 bases are never touched.

## Changes from adopt-448

1. **Resume uses `claude --continue`.** The user resumes Main with `cd <H> && claude --continue`. 00's `detect_main` also accepts that form: the host's parent argv is `claude --continue`, which carries no id, so the id comes from the project's newest transcript. Mps passes when the parent is `claude --continue` or `--resume $MAIN`. If `--continue` opens a different conversation, I prints the fallback `claude --resume <id>`.
2. **Backup entry copies really are 600.** In 448, `$BK/entries/*` matched nothing because every name starts with `.`. The script now uses `chmod 600 $BK/entries/*(D)`, prints `stat -f '%Sp %N'` for each copy, and stops if one is not `-rw-------`.
3. **The guard is classified and waits instead of refusing** (see the table below). Step I waits until no BLOCKING process remains, checking every 20 s. It prints which processes still run and a Chinese line saying it is waiting for Task 451/452 (or other) members, that they must not be killed, and that Ctrl-C gives up safely. The guard runs again right before `pip install` (after the backup). After the install, I lists any BLOCKING process that started during the install window, as information for Main. R uses the same wait.
4. **S** uses 450's method: Conda python3.13 `-m venv --system-site-packages`, then editable `-e src/graftling -e .` from this Worktree. Production's click, yaml, `_yaml`, pyyaml, and websockets (with their dist-info) are copied into the venv's site-packages so they shadow Conda's. S prints the click version (expected 8.5.0) and stops if `graphtraj.__file__` is not under this Worktree. It also prints loadavg and any other pytest or run_test_shards processes, and refuses while another run_test_shards runs. The suite runs with `--shards 6 --timeout 1500`. Each failure is marked BASELINE (also failed in 450's bb8b07db suite: 3 failed, 3963 passed, 71 skipped) or NEW, then rerun alone with `-rA`.
5. **V** keeps the `const PLUGIN = null;` check. It replaces 448's "inert" judgement with 449's display change (below), and checks that `body.execution` appears only in the candidate. I checks that the installed `host_context.mjs` contains `body.execution`. It imports `graftling.member_processes` and checks that `MEMBER_RUN_ENV` is the same in graphtraj and graftling. These replace 448's `445 timer` import line.
6. **Vc** truncates `Vc.txt` and removes `Vc.ok` at the start of each run. In 448, a rerun's summary showed a stale FAIL.
7. **N/Nr are 449's production check.** See the step table. Nr finds the member **by alias** in the Runner's Session directory, falling back to a retired record in the Task Traces (as `scripts/verify-449/probe.py` does). 448's lookup by `agent == alias` found nothing. Nr reads the retire target from the `agent` value in `raw/N.txt`, not from the alias.
8. **M** says that notices from 451/452 members that ended while Main was exited may arrive once at resume. That is expected; they must not repeat.

## Guard: process kinds that use `.venv-runtime`

| Kind (argv) | Started by (code) | Class |
|---|---|---|
| `-m graphtraj.execution.budget_idle_timer` | `graphtraj/execution/budget_idle_timer.py:57` (a detached process when a timed Session goes idle) | **NON-BLOCKING**, listed separately |
| `-m graphtraj.execution.runner_worker` | `runner_control.py:1302` (resume), `teams/team_round.py:1339` (launch) | BLOCKING: a member is executing |
| `-m graphtraj.teams.team_round` | `teams/team_round.py:382` (a swarm batch dispatching members) | BLOCKING |
| `… claude.host serve --config <this project>` | Claude Code starts it from `.mcp.json` (Main's host) | BLOCKING: Main has not exited |
| other `… serve`, the DSH watcher (`graftling/dsh/service.py:158`), a CLI call, anything else under `$RT` or naming Main's id | members' own hosts, Main's commands | BLOCKING |
| 450 marked process (`GRAFTLING_MEMBER_RUN` in its environment, read with `ps -E`) | `graftling/member_processes.py` (a member's escaped process) | information only; blocking only if it also runs from `$RT`, and then it already appears above |

There is no separate gateway or Runner batch daemon. A Runner batch is the
`team_round` and `runner_worker` processes listed above.

### Judgement on 3(a): a timer that wakes after the files are replaced

A timer sleeps in 30 s slices. At start it has already imported
`budget_idle_timer`, `execution_budget`, `runner_heartbeat`, `runner_models` and
`runner_status`. It does not import `runner_control` at start. At the threshold,
`ExecutionBudgetMonitor.deliver_parent_notices` lazily imports
`graphtraj.execution.runner_control` (`execution_budget.py:311`). After the
install, that import loads the new `runner_control.py`, which runs
`from graphtraj.execution.runner_models import MEMBER_RUN_ENV`. The old
`runner_models` already in the timer's `sys.modules` has no `MEMBER_RUN_ENV`
(450 added it). The import therefore raises `ImportError`.

I checked this in the sandbox. Loading the 2be27dd6 modules the way a timer
does, then pointing the package at the cfd5e432 sources, gives:
`ImportError cannot import name 'MEMBER_RUN_ENV' from 'graphtraj.execution.runner_models'`.
`main()` does not catch `ImportError`, so the timer exits with a traceback to
`/dev/null`.

The effect is that the timer drops that Session's elapsed-budget notice. The
threshold is still observed at that Session's next execution start, where the
monitor checks it (budget_idle_timer docstring), and the next idle period starts
a timer on the new code. Nothing is written in a half-done way:
`check_elapsed` runs before the failing import, and delivery uses the existing
keys. So the timer is not a reason to block the install. The worst case is one
late budget notice per idle timed Session whose threshold falls after the
install. The guard lists the timers so Main knows which Sessions those are.

## 449's change to production's plugin copy (team judgement)

Production's `hooks/host_context.mjs` is written by `configuration --write` from
`src/graftling/claude/host_context.mjs`, with `const PLUGIN = null;` unchanged.
From 2be27dd6 to cfd5e432, only 53456214 (449) touches this file, with 2 lines
added and 1 removed. When a queued notice's body has an `execution`, the notice
title gains ` · execution <id>`:
`[Graftling notice from <alias> · <event> · execution <id>]`. Notices without
`execution` look as before. This is a behaviour change, but for display only.
The notice text sent to Main changes; the delivery path does not.
`main_continuity.render_notices` (the Python side) gets the same title change.
V records the diff in `raw/V-plugin.diff`. Because the bytes change, resume may
show one plugin/hooks trust dialog. Criterion 4 (Main still shows the notice
normally) is checked by saving Main's own received notice for the member's end
as `raw/N-main-notice.txt`. Nr checks that it names the execution.

## Steps

Each step prints who runs it, its dialog (at most one) and the next command with
real values. The Main Session id is detected in 00 and saved to
`~/graphtraj-adoption-453/main.session`.

| Step | Who | Command | Dialog | Success |
|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | zsh; `answer:` with `claude-opus-5-5`; 0.1.0/0.5.0; `pip check rc=0`; 451/452/453 member list (running members are allowed); classified guard (timers NON-BLOCKING); Task 453 Team 1 active, `stopped: false`; no backup yet; `MAIN=<id>` |
| B | Main | `zsh $S B` | none | two wheels with sha256; `leaked: 0` |
| V | Main | `zsh $S V` | none | `449 hook change: notice title gains ' · execution <id>'` and no STOP; candidate `✘` lines no more than baseline; entry predictions SAME or explained; `read_session … failures=0` |
| S | Main | `zsh $S S` (returns at once; refuses if another run_test_shards runs) | none | `click 8.5.0`, `graphtraj.__file__` under this Worktree; poll `tail -n 25 …/raw/S-suite.txt` until `== DONE`; no `NEW` failure; each failure has a `PASSED/FAILED/SKIPPED alone:` line |
| Vc | Main | `zsh $S Vc` | none | `graphtraj-claude-host loaded: YES`; `PASS mcp__agents__tasks`, `PASS mcp__agents__agents` |
| Vu | **USER**, only if Vc says `loaded: NO` | `cd ~/graphtraj-adoption-453/vproject && claude`, then 'Yes, proceed', then `/exit` | folder trust | Main reruns Vc |
| — | **USER** | `/exit` in Claude Main | none | |
| I | **USER** | `zsh $S I` (Enter to confirm) | none | waits while BLOCKING processes run, never kills; then `-rw-------` ×3, `Successfully installed`, `PASS n FAIL 0`, `450 member_processes`, `SAME-AS-VALIDATED`, `449 installed host_context.mjs names body.execution`; install-window BLOCKING list (information). On failure it prints R |
| — | **USER** | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | at most one plugin/hooks trust (host_context.mjs changed): trust | |
| M | Main | `zsh $S M`, then paste its prompts | none | criterion 4: no notice seen before the install appears again (451/452 ends during the exit may arrive once) |
| Mps | Main | `zsh $S Mps` | none | host uses `.venv-runtime`; `parent is claude --continue or --resume <id>: yes`; `outcome=ok` |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` |
| N | Main | `zsh $S N`, paste the swarm prompt; save the raw swarm result to `raw/N.txt`; when the member's completion notice arrives, paste it raw into `raw/N-main-notice.txt` | none | an `opus_coding_team.advisor` member of Task 453 creates child `n453` (preset role `opus_coding_team.advisor`), waits, sends once, waits, quotes its task_sessions entry, reports inputs per execution, retires the child |
| Nr | Main | `zsh $S Nr` | none | `CHECK two executions: PASS`; `notification delivered: PASS` ×2; `CHECK one notice for execution …` ×2 (or count by hand); `CHECK swarm result has agent: PASS`; `CHECK Main's notice title names the execution: PASS`; then the printed session_read, task_sessions and **retire-by-agent** prompts |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`; `raw files containing an exported key value: 0` |
| R | **USER** (Main exited) | `zsh ~/graphtraj-adoption-453/backup/tools/steps.zsh R` | none | waits like I; venv and plugin `SAME differences=0`; entries OK; pip check; then `claude --continue` |

The user does only these: Vu (only if needed), `/exit` Main, run I (which may
wait for 451/452/453 members to go idle), and `claude --continue`, which may
show one trust dialog. R is needed only if something fails.

If I is abandoned with Ctrl-C after the backup (during the second wait),
production is unchanged but `backup/` exists without `INSTALL-STARTED`. Main
renames it aside before I is run again.

## What was rehearsed

`rehearse.zsh` ran in the sandbox on a fake production in `$TMPDIR`: old wheels
from 2be27dd6, click and yaml from Conda, an import-only websockets stub, and
`claude` and `ps` stubs. The ps stub lists Main's host (whose parent is
`claude --continue`), a stub `budget_idle_timer`, and a stub member
`runner_worker` that goes away after about 3 s.

These passed:

- 00: Main found through `--continue` and the newest transcript; the timer classified NON-BLOCKING.
- B.
- V: 449's change recognised, with the diff recorded.
- S's refusal while another run_test_shards runs.
- I: waited while the Worker and host ran, never listed the timer as BLOCKING, then passed. Entry copies `-rw-------` ×3; `PASS 246 FAIL 0`.
- R from the backup's tools.
- Mps with a `claude --continue` parent.
- Nr on synthetic records: member found by alias, one notice per execution, retire prompt using the swarm `agent`, Main notice title check.
- The M and N prints.

Output: `rehearsal-output.txt`.

Not rehearsed:

- real `claude -p` (00, Vc) and `claude plugin validate`;
- the full suite (S beyond its quiet-host refusal);
- real `ps` and `ps -E` against production (the guard's marker listing);
- the real N dispatch;
- the waiting loop's Ctrl-C path.
