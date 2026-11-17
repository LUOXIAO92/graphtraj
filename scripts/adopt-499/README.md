# 499 production adoption: dev 871aaaa9 (496, 498)

`steps.zsh` installs the wheels built from `git archive 871aaaa9ea7f63998990cb6600ca098d320e18c8` into production
`.venv-runtime`. Production holds 497's `2da634af052273180dfeef4d920a2911364a05e5` (installed 2026-11-16 22:34:47).
It is `scripts/adopt-497/` copied and adapted (adopt-497 is unchanged). Every 497 protection stays:
- the isolated real-Claude project `tmp/499/vproject` (own git, own `.graphtraj`, own `.claude/settings.local.json`
  written by `scripts/verify-common/claude_isolation.py`, isolation check, answer check, Vu once);
- file-by-file equality (`proddiff.py`); markers (`markers.py`); I's import lines;
- the backup `tmp/499/backup`, with rollback R from the backup's own copy of the tools;
- a guard that waits and never signals, rerun right before `pip install`;
- no exported key value in raw output (`done` counts files);
- timers listed, never signalled; S starts only on a quiet host; pytest temp `TMPDIR=${TMPDIR:-/tmp}` outside the
  Harness (printed; S STOPs if it is inside).

Versions do not change at 871aaaa9 (graphtraj 0.1.0, graftling 0.5.0; checked in `pyproject.toml` and
`graftling.__version__`).

- Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/499-production-adoption-496-498/scripts/adopt-499/steps.zsh`.
  Main runs `zsh $S <step>`. Every step prints the next command with real values.
- Raw output: `.graphtraj/core/state/tasks/499-production-adoption-496-498/adoption/raw-871aaaa9/`.
- Base: `tmp/499/` (`backup/`, `vproject/`, `vvenv-871aaaa9/`, `svenv-871aaaa9/`, `checkout-871aaaa9/`, `sdeps/`,
  `main.session`, `cc.version`).
- 00 lists 497's backup `tmp/497/backup` and its `COMPLETE` marker and never modifies them (kept until 499 is
  accepted).
- Only `rehearse.zsh` sets `ADOPT499_*`.

## Changes from adopt-497

1. **Target.** `TARGET=871aaaa9…`, `OLD=2da634af…`, `TASK=499-production-adoption-496-498`, child `n499`. Keyword
   `KW499-ORCHID`, reply `DONE-499`, fake key `sk-probe499fake''value0000` (split in the prompt), seq lines `499-NN`.
2. **Claude Code version is not assumed.** 00 records `claude --version` of the installed Claude Code once in
   `tmp/499/cc.version` (`Claude Code installed: …`); every later step prints `same as recorded at 00 (…): yes|NO`.
3. **Markers** (`markers.py`, 8 lines that `git diff 2da634af 871aaaa9 -- src` adds). The diff changes 4 files:
   `graftling/control.py` and `graftling/tool_descendants.py` (modules), and `graftling/CHANGELOG.md` and
   `PUBLIC_API.md`. The two `.md` files **are installed** (package-data in `src/graftling/pyproject.toml`; production
   has both), so proddiff compares them file by file; they carry no code and get no marker. The rehearsal shows
   `present: PASS (8/8)` on 871aaaa9's git-archive tree and `absent: PASS (8/8)` on 2da634af's, plus both negatives.

   | Task | File | Line |
   |---|---|---|
   | 496 | `graftling/control.py` | `    return not has_exited(pid)` (in `_alive`) |
   | 496 | `graftling/tool_descendants.py` | `def has_exited(pid: int) -> bool:` |
   | 498 | `graftling/tool_descendants.py` | `def _verdict(pid: int, marker: str, recorded: bool = False) -> str:`; `def _executed(pid: int) -> bool:` |
   | 498 | `graftling/tool_descendants.py` | `    def _settle(self, live: …) -> None:`; `def _beneath(live: …, roots: …) -> set[…]:` (cascade) |
   | 498 | `graftling/tool_descendants.py` | `_signal`'s `… _verdict(item.pid, marker, recorded=True) in (OURS, PROVISIONAL):`; `'remaining': [… sorted({*alive, *unsettled})]}` (stop-time rule) |

   I keeps every earlier import line (464, 465, 469, 478, 492, 497) and adds:
   - `496 has_exited has_exited | control._alive uses has_exited: True`
   - `498 verdicts ours foreign provisional later | _verdict _executed _platform _beneath _settle | unsettled only under remaining: True`
4. **Plugin and trust dialog.** `git diff --stat 2da634af 871aaaa9 -- src/graftling/claude/host_context.mjs
   src/graftling/claude-plugin plugins '*.mjs' '*hooks*'` is empty. **Prediction: no dialog at `claude --continue`.**
   V still compares the regenerated plugin files (`SAME` ×3) and I compares the real bytes (`plugin bytes as before
   the install` or `CHANGED`).
5. **497's script defects, fixed** (497 `rounds/2/leader-2.md`, "To register" (b) and (d)):
   - **Notice count** (`notices499.py`). 497 counted every line containing `completed`, so Main's header made it 2.
     Now only lines that start with the notice's own shape count:
     `[Graftling notice from <member alias> · completed · execution <hex>] …` (the shape in 497's raw
     `N-main-notice.txt`), and only for the member alias Nr found. Main saves every notice as received, one per line;
     an explanatory line may be added, on its own line, not starting with `[Graftling notice` (for example `# …`).
     On 497's real `N-main-notice-with-header.txt` the count is 1 (497 printed 2).
   - **session_id.** The by-hand prompt is `session_read with {"session_id":"<id>","limit":400}`. The installed schema
     (`tasks describe session_read`) requires `session_id`.
   - **S occupancy** (`busy499.py`). `ours` is now only our `_Srun` job, or a process that runs a suite (pytest,
     py.test, `-m pytest`, `run_test_shards.py`) from our test venv. Other processes of our test venv (a
     `budget_idle_timer` or Worker an earlier S left) are leftovers: listed, never signalled, never a refusal.
6. **ATTRIBUTED (S).** 497's entries are kept. Added:
   - 496: accepted suite 0 failed / 4170 / 69 (nothing to attribute);
   - 497's adoption suite: 0 failures;
   - 498: accepted with 5 failed / 4176 / 69, all 5 pass on a quiet rerun
     (`498-…/realhost/S-shards/failures.txt`): `test_the_next_host_names_a_surviving_runtime_and_records_no_stop`,
     `test_concurrent_starts_over_a_stale_channel_serve_once[graftling.claude.host]`,
     `test_graphtraj_session_end_is_one_stop_line[serving]`,
     `test_start_replaces_an_unusable_channel_file[empty-graphtraj.runtimes.claude.host]`,
     `test_start_replaces_the_channel_of_a_killed_host[graftling.claude.host]`.
7. **498 production observation (new).** It is the first bullet of definition item 3. See the next section.
8. **496: no production runtime check.** This is the Leader's judgement. Observing it would need a Runtime that dies
   in the middle of an execution, with an exiting or zombie window while control reconciles. Producing that means
   signalling a process the steps did not start. The window is also transient, so a read-only step cannot catch it on
   purpose. Coverage is the installed bytes:
   - proddiff, file by file;
   - markers (2 lines);
   - I's `496` import line (`control._alive uses has_exited: True`).
9. **Timers, judgement 3(a) for 2da634af → 871aaaa9** (`timer_probe.py`, in rehearsal-output.txt). A timer started
   under 2da634af has no changed module in memory: `budget_idle_timer.py` did not change. At its threshold the lazy
   imports load the new `graftling.control` and `graftling.tool_descendants`, and the delivery succeeds
   (`OLD in memory before the install: none`; `loaded NEW: ['graftling.control', 'graftling.tool_descendants']`).
   Timers are still only listed.
10. **Kept:**
    - M/Mps/inbox (restart, notices not repeated);
    - Mpre/N484 (484/486);
    - Nt/T (490);
    - Nr's 452/455/459/465/466/468/477/486/487/494/495 checks;
    - 00's preflight: `claude -p` from the vproject with the model and login line, `task graph --task-id 499`, task
      members, control snapshot.

## 498 production observation

Only a Claude child that an agents tool creates has a tool-process record in production (498 F and `leader-2.md`).
So the observation runs in N's child `n499`.

**N, Step 01b (one Bash call):**
`( sleep 1201; true ) >/dev/null 2>&1 & sleep 1202 >/dev/null 2>&1 & sh -c 'sleep 1203; : api_key=sk-probe499fake''value0000' >/dev/null 2>&1 & sleep 4; echo n499-bg-started`
- The subshell is a fork copy of the tool shell that never executes (`; true` prevents the exec): P_EXEC is clear,
  and it is provisional when the shell is a platform image.
- `sleep 1202` is an executed child.
- `sh -c …` has a recorded command line that carries the fake credential.
- `sleep 4` keeps the tool shell alive for more than one sample (1 s), so the sampler sees its children before the
  shell exits.
- All three are detached, so the Bash call returns. They end by themselves after 1201–1203 s, even if never stopped.
  They are still running at the child's end (Steps 02–43 follow).

**Nw starts `watch498.py`** (background, read only, never signals, ends itself 15 s after the execution ends; at most
25 min). Every 0.5 s it reads, with the candidate's own readers from B's git archive (`_table`, `_process_view`,
`_executed`, `_platform`, `shown_command`):
- the child's control record `executions[*].process`: `runtime_pid`, `tool_marker` (only compared, never written),
  and `tool_descendants` (`graphtraj/execution/agent_driver.py`);
- the sidecar `{'version': 1, 'runtime_pid', 'entries': [{pid, ppid, pgid, uid, start, argv}]}`
  (`tool_descendants.write_sidecar`; argv already redacted);
- for each process, facts as classes only. The Runtime's env is None, empty or readable, and its marker is this, other,
  none or n/a. Each Runtime descendant gets P_EXEC, platform (csops), env class and marker class. Recorded entries
  that are no longer under the Runtime are kept too (`outside`).

Changed samples go to `raw/Nw498-samples.jsonl`.

**Nr runs `nr498.py`:**
- **Observation lines:** the child Runtime pid, the env classes seen from Main's watcher, and the marker classes.
  Also one line per tool process (`subshell`, `sub-sleep`, `bg`, `sh`, `sh-sleep`): P_EXEC, platform, env, marker,
  and whether it was recorded and seen under the Runtime.
- `CHECK 498 Runtime environment and marker observed`. An unreadable environment is reported as `env ['None']`.
- `CHECK 498 record lists this execution's tool commands (subshell, background sleeps)`. Each of subshell,
  `sleep 1201`, `sleep 1202` and `sh -c` appears in the record (pid and start).
- `CHECK 498 record contains no other execution's process`.
  - FAIL when a recorded entry reads readable without this execution's marker.
  - BLOCKED (not met) when a recorded entry was never seen under the Runtime and has no recorded parent chain to it.
- `CHECK 498 recorded tool processes stopped at the execution end (gone; listed under found and stopped)`.
- `CHECK 498 unsettled reads only under remaining, not signalled`. An unsettled read is remaining minus found. One
  that is gone before its own end (start + its sleep) means it was signalled: FAIL. One still alive passes. Its pid
  and the time it ends by itself are printed, and nothing is signalled.
- `CHECK 498 credential masked in the record and the stop record`: the fake value occurs 0 times in the samples,
  sidecar and stop record, and the recorded `sh -c` entry shows `[redacted]`. 495 (466)'s check on the results stays
  in nr499.py.

**Which event stops them, and why Nr is the right step.** For a Claude child, `graftling/claude/execution.py` stops the
recorded tools when the execution ends, not at retire:
1. The run loop ends at the turn end (`turn_ended`).
2. Its `finally` takes a last sample (`descendants.finish()`) and closes the Runtime (`_close`).
3. It then calls `stop_tool_processes(…)` and writes `claude-termination-<execution>.yml` with `escaped_processes:
   {found, stopped, remaining[, error]}`. The file sits next to the sidecar in `.graphtraj/swarm/native/<agent>/`.

`found` lists every target, all signalled. `remaining` lists those still alive after SIGKILL, plus unsettled (later)
reads that were never signalled. Retire of a standby child runs no stop. So the check belongs to Nr, after the child's
execution ended. Nr runs before retire, and the record is retained, so a rerun after retire gives the same result.
While the execution still runs, Nr prints PENDING.

**If a long-lived process is still alive after the end,** Nr prints its pid and `ends by itself at HH:MM:SS (never
signalled here)`. No step signals it.

## Steps

`S` = the script path above. Main's Bash never runs a foreground sleep. Only I and R (the user's Terminal) wait.

| Step | Who | Command | Native dialog | Success observable | Wait limit |
|---|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | `Claude Code installed: …`; `isolation: OK`; `answer check (expect clean): OK`; `control records snapshot 00.json`; timer listing; `task graph rc=0`, `Task 499 named` ≥ 1; `markers expected absent: PASS (8/8)`; `stopped: false`; `tmp/499/backup` No such file; `497 backup COMPLETE marker: present`; `MAIN=<id>` | 5 min |
| B | Main | `zsh $S B` | none | graphtraj-0.1.0 and graftling-0.5.0 wheels, `leaked: 0` | 3 min |
| V | Main | `zsh $S V` | none | `SAME` ×3, `source diff: empty`, markers present and absent `PASS (8/8)`, ✘ not above the baseline | 5 min |
| S | Main | `zsh $S S` (background) | none | `ours: 0` (test-venv leftovers listed, not refused), checkout clean, imports OK, `pytest temp base TMPDIR=…` outside the Harness; later `== quiet at … start`, `== DONE`, `== new failures: 0` | 3 min (+ quiet wait ≤ 20 min, suite ≤ 30 min) |
| Vu | USER | `cd …/tmp/499/vproject && claude`, then `/exit` | folder trust for `tmp/499/vproject`: **Yes, proceed** | Vc shows `loaded: YES` | — |
| Vc | Main | `zsh $S Vc` | none | `isolation: OK`, `answer check (expect clean): OK`, `loaded: YES`, PASS tasks and agents | 3 min |
| Mpre | Main | `zsh $S Mpre` | none | `control records snapshot Mpre.json` | 1 min |
| — | USER | `/exit` in Main | none | Main closed | — |
| I | USER (Terminal) | `zsh $S I`, Enter once | none | waits for BLOCKING (never signals); backup; guard again; `Successfully installed …`; `PASS n FAIL 0`; `markers expected present: PASS (8/8)`; all import lines incl. `496 …` and `498 …`; `SAME-AS-VALIDATED`; `plugin bytes as before the install` | ~5 min + waiting |
| — | USER | `cd <harness> && claude --continue` | none expected | the same Session resumes | — |
| M | Main | `zsh $S M`, paste prompts a, b | none | no notice seen before the resume repeats | 2 min |
| Mps | Main | `zsh $S Mps` | none | host from `.venv-runtime`, parent `claude --continue`, two `CHECK 486 …: PASS` | 1 min |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` per file | 1 min |
| Nw | Main | `zsh $S Nw` (background; Nw, Nw468, Nw498) | none | `started at` | 1 min |
| N | Main | `zsh $S N`, paste the swarm prompt; save N.txt, N-main-notice.txt (every notice as received, one per line), N-reply.txt | none | launch_status not failed; one completed notice | 1 min + member ≤ 15 min |
| Nt | Main | `zsh $S Nt` after the member ends, before retire | none | `CHECK 490 a timer started by the new version …: PASS` | < 30 s |
| Nr | Main | `zsh $S Nr`, then the printed retire prompt | none | every CHECK PASS, including six `CHECK 498 …` and `CHECK 494 Main got exactly one completed notice` | 2 min |
| Nt | Main | `zsh $S Nt` (after retire) | none | the member's timer `absent` | < 30 s |
| N484 | Main | `zsh $S N484` | none | three `CHECK 484 …: PASS` | 1 min |
| S2 | Main | `zsh $S S2` (after `== DONE`) | none | `leftover processes of the suite (never signalled): 0` | 1 min |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`, markers present, key count 0, Nw `== END` | 2 min |
| T | Main, after the Leader accepts 499 | `zsh $S T` | none | two `CHECK 490 …: PASS` | < 30 s |
| timers | anyone, any time | `zsh $S timers` | none | listing only | < 10 s |
| R | USER, only on failure | `/exit` Main, `zsh <harness>/tmp/499/backup/tools/steps.zsh R` | none | venv and plugin `SAME differences=0`, entry files OK | ~5 min |

Main's foreground step limits add up to about 37 min, and the N member adds ≤ 15 min, so about 52 min in total. S
runs in parallel in the background. The user does only Vu, `/exit`, I, `claude --continue`, and R on failure.

## Criterion → observable

| Item | Observable |
|---|---|
| 1 install, 497's protections | V, Vc, I (backup `COMPLETE`, guard before pip, `PASS n FAIL 0`, import lines, `SAME-AS-VALIDATED`, plugin bytes), `done`, R |
| 2 full suite, no new failures | S's setup lines, `== new failures: 0`, each failure rerun alone, S2 leftovers 0 |
| 3 · 498 | Nw498 samples; Nr's six `CHECK 498 …` and the observation lines |
| 3 · 496 | no runtime check (change 8): proddiff, markers ×2, I's `496` line |
| 3 · 497/492/478 | Nr (452, 455, 459, 465, 466, 468, 477, 486, 487/494, 495), N484, Mps, Nt/T (490) |
| 4 restart and notices | M prompt a, Mps, inbox `duplicate ids: 0`, `CHECK 494 Main got exactly one completed notice` |
| 5 script defects | `notices499.py`, `session_id` in Nr's prompt, `busy499.py` (rehearsed) |

## Rehearsal

Run `zsh scripts/adopt-499/rehearse.zsh` (set -u; in `$TMPDIR`). It uses stub `claude`, `ps` and `sysctl`, a fake
production venv built from 2da634af wheels, and fixtures in the real result shapes (`rehearse_fixtures.py`, plus
`rehearse498.py` for the watcher samples and the `claude-termination-*.yml` stop record).

Result: **ALL PASS (134 checks)**, saved in `rehearsal-output.txt`. It covers all of adopt-497's checks, retargeted,
plus these for 499:
- **Markers:** both ways (8/8), with both negatives.
- **Timer 3(a):** for 2da634af → 871aaaa9.
- **S:**
  - leftovers of our test venv (a timer and a Worker): not refused, `ours: 0`;
  - a pytest of our test venv: refused;
  - our `_Srun` job or our shard runner: refused.
- **Notices:**
  - Nr with Main's header line plus one notice: PASS (1);
  - a header plus two notices: FAIL (2);
  - 497's real `N-main-notice-with-header.txt`: 1;
  - another alias: 0.
- **session_id:** in Nr's by-hand prompt.
- **I:** the `496` and `498` import lines against the fake production venv after the install.
- **ATTRIBUTED:** a 498 test is attributed; an unknown one is NEW.
- **N prompt:** Step 01b, exact text.
- **498:**
  - positive: six `CHECK 498 …: PASS` inside Nr;
  - a foreign entry in the record: FAIL;
  - a recorded process alive after the end: FAIL, with its pid reported and the process left running;
  - an unsettled process alive: PASS;
  - an unsettled process gone before its own end (signalled): FAIL;
  - Runtime environment unreadable: reported `env ['None']`;
  - no samples: six BLOCKED and exit 1;
  - `watch498.py` on a live tree started by the rehearsal (zsh, subshell, two sleeps of 61/62 s): it samples the
    subshell (P_EXEC false) and the sleeps, ends itself, and never writes the marker value. The rehearsal then stops
    only its own tree, found by ppid through libproc (pgrep is denied in the sandbox).

**Not rehearsed:**
- real Claude Code (00/Vc `claude -p`, Vu's dialog, N's member and child, Main's notices);
- whether Claude Code's Bash tool really leaves the Step 01b processes running past the call (if it ends them,
  nr498's stop check reports them as not listed under stopped);
- whether the real tool shell is a platform image (zsh/bash from /bin: provisional; a Homebrew shell: later, so the
  subshell would not be recorded and the "lists" check FAILs);
- whether Main's Bash can read the child Runtime's environment (the observation reports `None` if not);
- the real suite; real `ps`; the real Task end and T's timing; 00's real `task graph`.
