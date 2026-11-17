# 497 production adoption: dev 2da634af (488, 489, 490, 491, 494, 495)

`steps.zsh` installs the wheels built from `git archive 2da634af052273180dfeef4d920a2911364a05e5` into production
`.venv-runtime`. Production holds 492's `9faa0274e7eb0102cbc17109869f4b6562d6e680` (installed 2026-11-16 17:07).
It is `scripts/adopt-492/` copied and adapted. Every 492 protection stays:
- the isolated real-Claude rehearsal project `tmp/497/vproject` (own git, own `.graphtraj`, own `.claude/settings.local.json`, isolation check, Vu once);
- file-by-file equality (`proddiff.py`);
- the backup `tmp/497/backup`, with rollback R from the backup's own copy of the tools;
- a guard that waits and never signals, rerun right before `pip install`;
- no exported key value in raw output (`done` counts files);
- 00's false-STOP correction (the guard is information only at 00).

Versions do not change (graphtraj 0.1.0, graftling 0.5.0). Install claims come from `proddiff.py`, `markers.py` and
I's import lines.

- Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/497-production-adoption-488-495/scripts/adopt-497/steps.zsh`.
  Main runs `zsh $S <step>`. Every step prints the next command with real values.
- Raw output: `.graphtraj/core/state/tasks/497-production-adoption-488-495/adoption/raw-2da634af/`. Control-record
  snapshots are in its `ctl/`, the timer records in `Nt-timers.json`, `T-end.epoch` and `I-install-{start,end}.epoch`.
- Base: `tmp/497/` (`backup/`, `vproject/`, `vvenv-2da634af/`, `svenv-2da634af/`, `checkout-2da634af/`, `sdeps/`,
  `main.session`).
- 00 lists 492's backup `tmp/492/backup` and its `COMPLETE` marker and never modifies them. They are kept until 497 is
  accepted.
- Only `rehearse.zsh` sets `ADOPT497_*`.

## Changes from adopt-492

1. **Target.** `TARGET=2da634af…`, `OLD=9faa0274…`, `TASK=497-production-adoption-488-495`, child `n497`. Outputs
   are `raw-2da634af/` and `*-2da634af`. Keyword `KW497-ORCHID`, reply `DONE-497`, fake key `sk-probe497fake''value0000`
   (split in the prompt). The seq lines are `497-NN`. Claude Code 2.1.325.
2. **Markers** (`markers.py`): 11 lines that the diff `9faa0274..2da634af -- src` adds (8 files, CHANGELOG not
   installed). On the git-archive trees, the rehearsal shows `present: PASS (11/11)` for 2da634af and
   `absent: PASS (11/11)` for 9faa0274, plus both negatives.

   | Task | File | Line |
   |---|---|---|
   | 488 | `graphtraj/execution/runner_process.py` | `def _worker_arguments(pid: int) -> list[str] \| None:`; `def _process_ended(pid: int) -> bool:` |
   | 490 | `graphtraj/execution/budget_idle_timer.py` | `def _work_ended(…)`; `def _collect_ended_children() -> None:`; `SLICE_SECONDS = 5.0` |
   | 490 | `graphtraj/execution/runner_cleanup.py` | `    return not process_is_zombie(pid)` |
   | 494 | `graftling/claude/host.py` | `    receive.defers_push = True` |
   | 494 | `graftling/control.py` | `ended.pop('push_deferred', None)` |
   | 494 | `graphtraj/interfaces/agents.py` | `_HOLDS.append(thread)` + `thread.start()` both inside `with _HOLDS_LOCK:` (two lines) |
   | 495 | `graftling/tool_descendants.py` | `live[key] = {**entry, 'argv': shown_command(argv)}`; `if live != self.entries:` |

   I keeps every earlier import line (464, 465, 469, 478, 492) and adds one line per input Task:
   - `488 _worker_arguments … | _process_ended …`
   - `490 _work_ended … | _collect_ended_children … | SLICE_SECONDS 5.0 | cleanup uses process_is_zombie: True`
   - `494 Claude host receiver defers_push: True | hold thread started in the lock: True`
   - `495 argv refreshed each sample: True`
3. **Plugin and trust dialog.** `git diff --stat 9faa0274 2da634af -- src/graftling/claude/host_context.mjs
   src/graftling/claude-plugin plugins '*.mjs' '*hooks*'` is empty: no `*.mjs` changed, so the DSH/Pi exclusions are
   gone, and 494's `claude/host.py` is Python. **Prediction: the Claude plugin bytes are unchanged, so no trust dialog
   appears at `claude --continue`.** V still compares the regenerated plugin files (`SAME` ×3), and I prints
   `plugin bytes as before the install` or `CHANGED`, based on the real bytes.
4. **Isolation (489).** `vsettings` is now `scripts/verify-common/claude_isolation.py settings <harness> <vproject>`.
   It writes only the vproject's own `.claude/settings.local.json` and refuses a project outside `<harness>/tmp/`. It
   is rerun after every `configuration --write`.
   - The answer check is `claude_isolation.py check`, which applies `ans492.py`'s criteria: tag, no prompt echo, no
     Harness file on the FILES line, no distinctive Harness AGENTS.md line. It also STOPs when the init plugins list
     `cc-plugin-agents-md`.
   - The prompt is `claude_isolation.py prompt <TAG>`. The success line is now `answer check (expect clean): OK`.
   - `ans492.py` is not copied. verify-common's rule says new adopt scripts use the shared helper.
5. **491.** `nr497.py` is `nr492.py` with dev's corrected wait parsing: only `action: execute` wait calls count; the
   member's `describe` of wait does not. `rehearse_fixtures.py` keeps that describe call first.
6. **Timers (490 and the known interference)** (`timers497.py list`). The `Task 490 timer pid 39497` line is gone.
   Every listing shows each `budget_idle_timer`:
   - pid, ppid, ps stat, start time (`lstart`; `ps` runs with `LC_ALL=C`, because a localized date cannot be parsed);
   - the executable, as `production .venv-runtime` or `other: <path>`;
   - the session directory and token prefix from argv;
   - its children with their stat.

   **When and how they are classed.**
   - Listed at 00, by the guard in I (before the backup and right before pip), and by the guard after the install.
   - Once I has written `I-install-{start,end}.epoch`, each timer is classed `old` (started before pip), `new`
     (started after the install's checks), or `during the install`. The pids are never hard-coded.

   **Effect on I.**
   - Timers are NON-BLOCKING, are never signalled, and a timer alone never makes I refuse.
   - A zombie child is information only.
   - A *live* child of a timer under `$RT` is a different case. It is a parent Worker that a budget delivery started.
     It is BLOCKING like any Worker, is labelled `child of budget_idle_timer <pid>`, and the guard says plainly that
     the user decides. **This is the only way old timers can make I's occupancy check refuse.**

   **Judgement 3(a) for 9faa0274 → 2da634af** (`timer_probe.py`, in rehearsal-output.txt).
   - An old timer has only one changed module in memory: `graphtraj.execution.budget_idle_timer` (old loop: 30 s
     slices, no `_work_ended`, no child collection).
   - At its threshold, the lazy imports load the new `graftling.control` (494), `graftling.tool_descendants` (495) and
     `graphtraj.execution.runner_process` (488/490), and the delivery succeeds.
   - The mix is consistent. The old loop calls only its own module, the unchanged `execution_budget` monitor, and
     the lazily imported names, whose signatures did not change.
   - The effect is that an old timer delivers with the new control code. It still behaves like an old timer: it does
     not exit when its Task ends and does not collect the Workers it starts. That is why old timers are listed and
     not judged.
7. **490 production check (new steps Nt, T).**
   - **Nt** runs after N's member ends, before it is retired, and again after retire. It reads every Task 497
     Session's `budget-timer.yml` token under `.graphtraj/core/runner/sessions/497-*` (the pid there is always null),
     then matches timers by session directory and token in argv. Every timer it ever saw is kept in `Nt-timers.json`
     and printed `present` or `absent` on each run, so a rerun after retire records the retire exit.
     `CHECK 490 a timer started by the new version for a Task 497 Session is listed (start after the install,
     production .venv-runtime)`.
   - **T** is run by Main after the Leader accepts 497 (status `awaiting-integration`). The first run at an ended
     status records the end time from `task.yml`'s mtime (`T-end.epoch`).
     - `CHECK 490 every new-version timer of a Task 497 Session is gone after the Task end`. It covers the Nt-recorded
       timers plus any new one present now. Old ones are printed `old/not judged`.
     - `CHECK 490 no budget notice for Task 497 Sessions after the end`, from `parent_notices` in the Task's
       `execution-budget.yml` (`occurred_at` after the end and `delivered`).
     - Before the end, or < 30 s after it with a timer still present, T prints PENDING and the rerun line. It never
       waits in the foreground.
8. **494 check.** Nr keeps the 477/487 checks, labelled `494 (487) first wait timed out while the child ran`,
   `494 (487) reply delivered once (DONE-497 through wait/status; graphtraj inputs pushed = 0)` and `494 (477) child
   end not pushed …`. It adds:
   - from a control snapshot `ctl/Nr.json` (`ctl497.py n494`): `CHECK 494 child n497 ended execution has notification
     delivered` and `… keeps no push_deferred/push_holder`;
   - `CHECK 494 Main got exactly one completed notice of the member`. Main saves every notice of the member, one per
     line, to `N-main-notice.txt`.
9. **495 check.** The checks are labelled `495 (459) descendants record lists the Bash tool command` (`nr459.py`, with
   Nw's snapshots) and `495 (466) credential masked …` (fake value 0 in all results, member archive and native
   transcript; `[redacted]` present; counts only).
10. **488: no production runtime check.** 488 changes only the identity check of the stop before a Runtime starts
    (`runner_process._worker_arguments`/`_process_ended`). That path runs only when a launching Worker is stopped
    before its Runtime starts, and no production step does that on purpose. Doing it would mean stopping a real
    launch. The installed bytes are covered by proddiff (file by file), markers (2 lines) and I's `488` import line.
11. **Kept:**
    - N484 (three CHECK 484) and Mpre/Mps (486);
    - Nr's 459/465/466/468/455/452/member-Bash/486 checks;
    - Nw's watchers;
    - 00's preflight: the `claude -p` model and login line from the vproject, `task graph --task-id 497`,
      `task members`, the `ctl/00.json` snapshot.
12. **S (full suite).** S makes a fresh `git clone --shared` checkout of 2da634af and links production's dependencies
    into the test venv's own site-packages. It runs the nested-venv check, prints pytest temp `TMPDIR=${TMPDIR:-/tmp}`
    (and STOPs if that is under the Harness), and runs 6 shards with `--timeout 1500`. Each failure is rerun alone.
    - **Quiet host (Correction 1, `busy497.py`):**
      - **What counts as a running suite.** It is decided from argv tokens, never from path substrings. A process
        runs a suite when its executable's basename is `pytest`/`py.test`, when it has `-m pytest`, or when an
        argument's basename is `run_test_shards.py`. S's own process subtree is excluded.
      - **Leftovers.** Other processes under `pytest-of-*` paths are listed as `leftover test processes
        (information; never signalled; not a running suite): n`, with pid, etime and command. On the real host at
        22:21 these were 5 installed-environment timers and 1 Worker, elapsed 2 days 22h.
      - **Foreground.** S prints the loadavg, the CPU count and the limit (half the CPU count; `ADOPT497_LOADMAX` is
        the only override), then sets up and returns. It refuses only while another S of ours runs, meaning its
        `_Srun` job or a shard runner from its test venv (`ours: n`).
      - **Background.** The nohup job checks every 30 s, for up to 20 min, for no running suite and a 1-minute load
        at or below the limit. It logs `quiet check HH:MM:SS loadavg … | running suites n` to `S-suite.txt`, then
        `== quiet at HH:MM:SS start` and the suite. Otherwise it logs `== STOP not quiet within 20 min (1200 s)` and
        does not run the suite.
    - **ATTRIBUTED:** the failures named in the accepted suites:

      | Task | Accepted full suite | Failing tests named |
      |---|---|---|
      | 488 | 1 / 4152 / 69 | `test_wait_and_push_racing_deliver_the_reply_exactly_once[3-True]` |
      | 489 | script only, no suite | — |
      | 490 | 3 failed + 2 errors / 4146 / 69 | `native_interrupt_confirms_only_pre_runtime_allocations[absent]`, `native_owner_retains_control_of_its_recorded_root[child]`, `replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session`, `retry_continues_after_a_later_approved_budget_increment` (error), `failed_merge_retains_conflict_evidence_and_does_not_run_validation` (error) |
      | 491 | 3 / 4137 / 70 | `child_registration_follows_its_owning_execution`, `another_process_holding_a_record_lock_does_not_hold_the_host[dsh]`, `a_locked_parent_does_not_hide_or_hold_its_descendants[pi]` |
      | 494 | 0 failed (PASS SUITE) | — |
      | 495 | 5 / 4150 (load 68; all pass quiet) | `public_interrupt_reconfirms_an_undrained_worker`, `a_locked_parent_does_not_hide_or_hold_its_descendants[dsh]`, `a_request_in_flight_that_finishes_still_gets_its_reply[dsh]`, `reconciliation_stops_only_the_execution_marked_tools`, `installed_alias_control_resumes_and_interrupts_one_team_session` |
      | 492 adoption | 1 NEW | `tests/test_tool_descendants_459.py::test_recorded_and_reported_command_lines_are_redacted` |

      Sources are the leader reports and `realhost/SUITE-shards/failures.txt` of 490, 494 and 495. The 480/481/487
      names of 492's list are dropped: the race `[6-True]` is NEW now.
    - **Output:** `== failures in the suite: n (ATTRIBUTED: k)` and `== new failures: n-k`.

## Steps

`S` = the script path above. Main's Bash never runs a foreground sleep. Only I and R (the user's Terminal) wait in a
loop.

| Step | Who | Command | Native dialog | Success observable | Wait limit |
|---|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | `expected 2.1.325: yes`; `isolation: OK`; `answer check (expect clean): OK`; `control records snapshot 00.json`; `guard: budget_idle_timer processes: n …` and one line per timer; `task graph rc=0`, `Task 497 named` ≥ 1; `markers expected absent: PASS (11/11)`; `stopped: false`; `tmp/497/backup` No such file; `492 backup COMPLETE marker: present`; `MAIN=<id>` | 5 min |
| B | Main | `zsh $S B` | none | graphtraj-0.1.0 and graftling-0.5.0 wheels, `leaked: 0` | 3 min |
| V | Main | `zsh $S V` | none | `SAME` ×3, `plugin unchanged: …`, `source diff: empty`, markers present and absent `PASS (11/11)`, ✘ not above the baseline | 5 min |
| S | Main | `zsh $S S` (background) | none | `CPUs: … load limit …`, `running suites: n`, `leftover test processes …: n` (information), checkout clean, `test venv imports the checkout: OK`, `nested venv imports: OK`, `pytest temp base TMPDIR=…`; later `S-suite.txt` shows `quiet check …` lines, `== quiet at … start`, `== DONE`, `== new failures: 0` (or `== STOP not quiet within 20 min`: Main reruns S later) | 3 min (+ background: quiet wait ≤ 20 min, then ≤ 30 min) |
| Vu | USER | `cd …/tmp/497/vproject && claude`, then `/exit` | folder trust for `tmp/497/vproject`: **Yes, proceed** | Vc shows `graphtraj-claude-host loaded: YES` | — |
| Vc | Main | `zsh $S Vc` | none | `isolation: OK`, `answer check (expect clean): OK` (VC-OK), `loaded: YES`, PASS tasks and agents | 3 min |
| Mpre | Main | `zsh $S Mpre` | none | `control records snapshot Mpre.json` | 1 min |
| — | USER | `/exit` in Main | none | Main closed | — |
| I | USER (Terminal) | `zsh $S I`, Enter once | none | waits for BLOCKING processes (never signals); backup; guard again; the `I.json` snapshot; `Successfully installed …`; `PASS n FAIL 0`; `markers expected present: PASS (11/11)`; all import lines including 488/490/494/495; `SAME-AS-VALIDATED`; `plugin bytes as before the install`; timer listing ×3 | ~5 min + any waiting for other Tasks' members (or a timer's live child) |
| — | USER | `cd <harness> && claude --continue` | none expected | the same Session resumes | — |
| M | Main | `zsh $S M`, then paste prompts a and b | none | no notice seen before the resume repeats (item 4) | 2 min |
| Mps | Main | `zsh $S Mps` | none | host from `.venv-runtime`, parent `claude --continue`, `outcome=ok` > 0, two `CHECK 486 …: PASS` | 1 min |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` per file | 1 min |
| Nw | Main | `zsh $S Nw` (background, ends itself ≤ 15 min) | none | `started at` | 1 min |
| N | Main | `zsh $S N`, paste the swarm prompt; save N.txt, N-main-notice.txt (every notice of the member), N-reply.txt | none | launch_status not failed; exactly one completed notice of the member | 1 min + member ≤ 15 min |
| Nt | Main | `zsh $S Nt` after the member ends, before retire | none | `CHECK 490 a timer started by the new version …: PASS`; one present/absent line per timer | < 30 s (rerun after 30 s if the member just ended) |
| Nr | Main | `zsh $S Nr`, then the printed retire prompt | none | every CHECK PASS: 494 ×6, 495 ×2, 459, 465, member Bash, 455, 452, 466, 477, 468, 486 | 2 min |
| Nt | Main | `zsh $S Nt` (after retire) | none | the member's timer now `absent` | < 30 s |
| N484 | Main | `zsh $S N484` | none | three `CHECK 484 …: PASS` | 1 min |
| S2 | Main | `zsh $S S2` (after `== DONE`) | none | `leftover processes of the suite (never signalled): 0` | 1 min |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`, markers present, key count 0, Nw `== END` | 2 min |
| T | Main, after the Leader accepts 497 | `zsh $S T` | none | two `CHECK 490 …: PASS` (new-version timers gone; no notice after the end) | < 30 s (PENDING → rerun in 30 s) |
| timers | Main or USER, any time | `zsh $S timers` | none | listing only | < 10 s |
| R | USER, only on failure | `/exit` Main, `zsh <harness>/tmp/497/backup/tools/steps.zsh R` | none | venv and plugin `SAME differences=0`, entry files OK | ~5 min |

**Main's estimated run time.** The foreground step limits add up to 37 min: 00 5, B 3, V 5, S 3, Vc 3, Mpre 1, M 2,
Mps 1, inbox 1, Nw 1, N 1, Nt 1 ×2, Nr 2, N484 1, S2 1, done 2, T 1. The N member's wait (≤ 15 min) brings this to
**about 52 min**. S's suite (≤ 30 min) runs in the background in parallel. The user's I time (about 5 min) is extra,
plus any wait for other Tasks' members.

**The user does only:** Vu (trust `tmp/497/vproject` once), `/exit` Main, run I, `claude --continue`, and R only on
failure.

## Criterion → observable (definition items 1–4)

| Item | Observable |
|---|---|
| 1 install, 492's protections | V (`SAME` ×3, markers 11/11 both ways, `source diff: empty`); Vc (`isolation: OK`, `answer check (expect clean): OK`); I (backup `COMPLETE`, guard again before pip, `PASS n FAIL 0`, the import lines, `SAME-AS-VALIDATED`, plugin bytes as before); `done` (`PASS n FAIL 0`, key count 0); R from the backup's tools |
| 2 full suite, no new failures | S's setup lines (checkout, imports, nested, TMPDIR outside, quiet host), `== new failures: 0`, each failure rerun alone; S2 leftover 0 |
| 3 · 494 | Nr `CHECK 494 (487) first wait timed out …`, `CHECK 494 (487) reply delivered once …`, `CHECK 494 (477) child end not pushed …`, `CHECK 494 child n497 ended execution has notification delivered`, `… keeps no push_deferred/push_holder`, `CHECK 494 Main got exactly one completed notice of the member` |
| 3 · 490 | 00/I timer listings (before and after the install, old/new); Nt `CHECK 490 a timer started by the new version …` (present/absent per timer); T `CHECK 490 every new-version timer … gone after the Task end` and `CHECK 490 no budget notice … after the end` |
| 3 · 495 | Nr `CHECK 495 (459) descendants record lists the Bash tool command`, `CHECK 495 (466) credential masked …` |
| 3 · 478/492 checks | Nr: 459, 465, member Bash, 455, 452, 466 reads, 477, 468, 486; N484 (484); Mps (486) |
| 3 · 488 | no runtime check (item 10): proddiff, markers ×2, I's 488 import line |
| 4 restart and notices | M prompt a, Mps, inbox `duplicate ids: 0`, one completed notice in `N-main-notice.txt` |

## Rehearsal

Run `zsh scripts/adopt-497/rehearse.zsh` in `$TMPDIR`. It uses stub `claude` and `ps` (the ps stub serves `lstart`
listings), a fake production venv built from 9faa0274 wheels, and fixtures written by `rehearse_fixtures.py` in the
real result shape. Result: **ALL PASS (118 checks)** (Correction 1; Round 1: 113), in `rehearsal-output.txt`.

**Covered:**
- timer 3(a) for 9faa0274 → 2da634af;
- markers both ways, plus both negatives;
- `claude_isolation.py check`: positive; prompt echo, Harness AGENTS.md path with the plugin loaded, distinctive line
  and no result as negatives; `settings` refusing a project outside `tmp/`;
- 00:
  - the timer listing: an old production timer with a zombie child, a timer from another executable, and a live
    child Worker labelled BLOCKING;
  - the answer check, the control snapshot, 492's backup, 00-first.txt, and an echo STOP;
- B; V (`source diff: empty`); Vu; Vc's isolation part;
- S (Correction 1):
  - `busy497.py` positive: Main's 22:21 shapes (5 timers and 1 Worker under `pytest-of-*`, `grep -E
    pytest|run_test_shards`, `vim …/pytest.ini`) give `running suites: 0` and 6 leftovers;
  - `busy497.py` negatives: `-m pytest`, a `run_test_shards.py` argument, `pytest`/`py.test` executables and
    `-mpytest` are busy; the own subtree is excluded;
  - the setup with the leftovers present, not refused;
  - refusal only for our own `_Srun` job or our own test-venv shard runner;
  - the quiet wait, with a stub `sysctl` load: high, then low (starts); always high with a 2 s limit (STOP); a
    running suite at low load (STOP);
  - the ATTRIBUTED labels (488, 491/495, 492's 459, and `[6-True]` now NEW). The rehearsal sandbox cannot read
    `hw.ncpu`, so it checks only that the printed limit is half of the printed CPU count;
- S2;
- I: waiting, timers listed three times with the old class after the install, the install window, the import lines;
- Nt:
  - positive;
  - present → absent after retire;
  - negatives: only an old 497 timer; no install window;
- T: PENDING before the end; positive; negative (timer still present, notice after the end); PENDING < 30 s after
  the end;
- the `timers` step; R;
- Mpre/Mps; Nw;
- Nr: positive; negatives for 494 (push fields, two notices, `queued` notification, child still running), 466/495,
  477/494, 487/494 and 495/459 (E2BIG);
- N484; the N and M prompt contents; `done`'s key count and its T hint.

**Not rehearsed:**
- real Claude Code: 00's and Vc's `claude -p`, Vu's dialog, N's real member and child, Main's real notices;
- the real suite;
- real `ps`: lstart, zombies and timer pids come from the stub;
- real production control records and `budget-timer.yml`/`parent_notices`;
- the real Task end through the Leader's acceptance, and so T's timing in production;
- 00's real `task graph` call against production.
