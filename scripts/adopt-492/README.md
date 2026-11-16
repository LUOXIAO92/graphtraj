# 492 production adoption: dev 9faa0274 (480, 481, 484, 485, 486, 487; verify scripts, AGENTS.md rule)

`steps.zsh` installs the wheels built from `git archive 9faa0274e7eb0102cbc17109869f4b6562d6e680` into production
`.venv-runtime`. Production holds 478's `a3fe1b92251d0510b962d8adddb49f690e1d1f07` now (installed 2026-11-16 10:23).
It is `scripts/adopt-478/` copied and adapted; every 478 protection stays: isolated real-Claude rehearsal project
(`tmp/492/vproject`, own git, own `.graphtraj`, own `.claude/settings.local.json`, isolation check, Vu once),
file-by-file equality (`proddiff.py`), backup `tmp/492/backup` with rollback R from the backup's own copy of the
tools, a guard that waits, never signals, and is rerun right before `pip install`, no exported key value in raw output
(`done` counts files). Versions do not change (graphtraj 0.1.0, graftling 0.5.0); install claims come from
`proddiff.py`, `markers.py` and I's import lines.

- Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/492-production-adoption-480-487/scripts/adopt-492/steps.zsh`
  (Main runs `zsh $S <step>`; every step prints the next command with real values).
- Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/492-production-adoption-480-487/adoption/raw-9faa0274/`
  (control-record snapshots in its `ctl/`).
- Base: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/492/` (`backup/`, `vproject/`,
  `vvenv-9faa0274/`, `svenv-9faa0274/`, `checkout-9faa0274/`, `sdeps/`, `main.session`). 00 lists 478's backup
  `tmp/478/backup` and its `COMPLETE` marker and never modifies it; it is kept until 492 is accepted.
- Only `rehearse.zsh` sets `ADOPT492_*`.

## Changes from adopt-478

1. **Target.** `TARGET=9faa0274…`, `OLD=a3fe1b92…`, `TASK=492-production-adoption-480-487`, child `n492`, outputs
   `raw-9faa0274/` and `*-9faa0274`, keyword `KW492-ORCHID`, reply `DONE-492`, fake key `sk-probe492fake''value0000`
   (split in the prompt). Claude Code 2.1.325 (`cv` in every real-host step). 478's N466/N466b steps are gone: their
   corrected reads are folded into N (item 8).
2. **Markers** (`markers.py`, 10 lines the diff `a3fe1b92..9faa0274 -- src` adds). On `git archive` trees:
   `present: PASS (10/10)` for 9faa0274, `absent: PASS (10/10)` for a3fe1b92 (rehearsal-output.txt).

   | Task | File | Line |
   |---|---|---|
   | 480 | `graphtraj/runtimes/pi/pi_adapter.py` | `'write_paths': list(request['reports']),` |
   | 481 | `graphtraj/runtimes/dsh/main_entry.py` | `def main_patch(python: Path) -> list[dict]:` |
   | 481 | `graphtraj/runtimes/dsh/tool.mjs` | `async function attachMain(agent, python) {` |
   | 484 | `graftling/control.py` | `def _push_error(…)`; `ended['notification_error'] = failure`; `document['last_result']['notification_error'] = …` |
   | 485 | `graphtraj/runtimes/codex/finalize.py` | `child = await client.fork_session(parent)` |
   | 486 | `graphtraj/interfaces/mcp.py` | `def stop_owned_agents() -> None:`; `def _terminated(signum…)` |
   | 487 | `graftling/control.py` | `if waiters.pop(token, None) is not None and not waiters:` |

   I keeps 464's, 465's, 469's and 478's import lines and adds four: `481 main_entry main_patch main_patch | 484
   _push_error _push_error`, `486 stop_owned_agents stop_owned_agents | _terminated _terminated`, `485 finalize imports
   CHECKER_PERMISSION_PROFILE: False | 480 member_policy write_paths: True`, `487 wait timeout pops its waiter: True`.
3. **Process kinds and the Task 490 timer.** New spawn/signal lines in the diff: `dsh/tool.mjs` `spawn(executable,
   args)` (481: with the patch's `python`, a user-started DSH Main starts `<python> -I -m graphtraj.runtimes.native_entry
   dsh`; `attachMain` starts `<python> -I -m graphtraj.interfaces.mcp`), and `interfaces/mcp.py` installs a SIGTERM
   handler in its own process (486). No new long-lived process kind in a Claude Main or Claude member. Guard effect:
   unchanged; `kind_of` names `graphtraj MCP server (486; a Codex/DSH/Pi Main's)` and `DSH native entry (481)`; under
   `$RT` they are BLOCKING as anything under `$RT` was. Production Main is Claude, so none is expected.
   **Zombies** (`ps` stat `Z`) are information only, never BLOCKING: a zombie runs no code and holds no files (only its
   process-table entry until its parent reaps it); the guard prints `guard: zombies (…): n`. Timers stay NON-BLOCKING;
   anything else under `$RT` stays BLOCKING. The guard (00, I twice, R) prints
   `Task 490 timer pid 39497: present|absent, state <stat>, children n: <pid(stat)…> | <command>`; no step signals it.
   **Timer judgement 3(a)** (`timer_probe.py` rerun for a3fe1b92 → 9faa0274; rehearsal-output.txt): a timer started
   under a3fe1b92 has none of the changed modules in memory (`OLD in memory before the install: none`); at its threshold
   the lazy import succeeds and loads the new `graftling.control` (484 notification_error, 487 wait). Effect: such a
   timer delivers with the new control code; nothing old is mixed in. The stale timer pid 39497 (Task 490) was started
   from production `.venv-runtime` earlier; it is reported, not judged further, and never signalled.
4. **Plugin and trust dialog.** `git diff --stat a3fe1b92 9faa0274 -- src/graftling/claude/host_context.mjs
   src/graftling/claude-plugin plugins '*.mjs' '*hooks*'` lists only `src/graphtraj/runtimes/dsh/{tool,finalize}.mjs`
   (481; DSH's plugin, loaded only by Node inside DSH sessions). V prints them apart (`DSH only (not the Claude plugin):
   …`) and checks the rest is empty. **Prediction: Claude plugin bytes unchanged, no trust dialog at `claude
   --continue`.** I still prints `plugin bytes as before the install` or `CHANGED` from the real bytes.
5. **Isolation (Task 489).** As verify-462 (85877396) and verify-484: `vsettings` writes only the vproject's own
   `.claude/settings.local.json` (never `~/.claude`), merging `claudeMdExcludes` for the Harness
   `CLAUDE.md`/`CLAUDE.local.md`/`AGENTS.md` (and `**/` forms) and `enabledPlugins: {"cc-plugin-agents-md@builtin":
   false}`; rerun after every `configuration --write`. 00 and Vc ask `claude -p` from the vproject for two lines
   (`<TAG> <model>, logged in` and `FILES: <instruction files or NONE>`); `ans492.py` STOPs if there is no answer, the
   answer equals or contains the prompt (echo), FILES names a Harness file outside the vproject, or the answer holds the
   Harness AGENTS.md's longest line (compared in memory, never printed). 00's model call moved from `tmp/492/scratch`
   into the vproject (scratch is under the Harness and has no exclusions).
6. **Preflight 00:** one real read-only call through each host entry later steps use: `claude -p` (above),
   production `graphtraj task graph --task-id 492`, `graphtraj task members`; plus the 484/486 control snapshot
   `ctl/00.json`.
7. **S (full suite, Main, background)**, modelled on verify-486/487 SUITE: fresh `git clone --shared` checkout of
   9faa0274 at `tmp/492/checkout-9faa0274`; test venv from production's base Python with production's dependencies
   (never graphtraj/graftling) linked into its own site-packages (`sdeps/`); the checkout must be what it imports;
   nested-venv import check fail-fast; pytest temp `TMPDIR=${TMPDIR:-/tmp}` printed and STOP if under the Harness;
   refuses while another `run_test_shards` runs; 6 shards, `--timeout 1500`; each failure rerun alone. Prints
   `== failures in the suite: n (ATTRIBUTED: k)` and `== new failures: n-k`.

   | Task | Accepted full suite (failed / passed / skipped) | Failing tests named (ATTRIBUTED) |
   |---|---|---|
   | 486 | 0 / 4136 / 71 | — |
   | 485 | 0 / 4135 / 71 | — |
   | 484 | 0 / 4130 / 69 | — |
   | 487 | SUITE 2 failed | both in `tests/test_dsh_tool_reclaim_463.py` (R463 0/30 on dev and candidate) |
   | 481 | 6 / 4125 / 69 | `native_interrupt_confirms_only_pre_runtime_allocations[absent]`; `test_claude_later_prompt_hook_is_answered_during_one_slow_collection`; `test_send_and_resume_continue_the_same_dsh_session[0.2.0-rc.2]`; `test_a_busy_member_input_is_retried_within_the_operation_window`; `test_unconfirmed_termination_keeps_the_session_stopped`; `test_wait_and_push_racing_deliver_the_reply_exactly_once[6-True]` |
   | 480 (T2) | 5 / 4125 / 69 | `[6-True]` (as above); `test_claude_host_routes_a_dsh_child_with_its_own_choices`; `test_send_and_resume_continue_the_same_dsh_session[0.2.1-alpha.5]`; `test_hosted_cli_waits_for_full_parent_observation`; `[absent]` (as above) |

   Names taken from the records' text and `realhost/SUITE.txt` failure lines; whether each was flakiness was not
   re-judged (Main decides on any ATTRIBUTED failure).
8. **N** (one dispatch; member `opus_coding_team.advisor` of Task 492; child `n492` via agents create): 478's N
   plus 478's corrected 466 reads, so one dispatch covers 459, 465, 466, 468 (Nw), 455, 452, member Bash and 487.
   Member: create; **first** `agents wait {agent, timeout_seconds: 5}` while the child still runs (must show
   `timed_out` true); then `timeout_seconds 300` repeated until the end, quote last_message; status; session_read
   ×5 (default; start -10 stop -5; search KW492-ORCHID; content tools search `api_key`; content tools search
   `[redacted]`), counts and yes/no only; `SESSION-READ-492 …`; own Bash; list graphtraj parent inputs; retire.
9. **Nr** (`nr492.py` = nr478.py with nr466.py's walker): results are decoded through nested JSON strings until the
   dict with `total` (real shape `{action, agent, …, result: {session, content, total, start, stop, events: [{index,
   seq, type, text}]}}` inside `[{type: text, text}]`); without one it prints a structural diagnostic. New CHECK lines:
   `CHECK 466 credential masked …` (Round 3 rule: a content-tools search result shows an event at a child seq holding
   the value, with `[redacted]`; value 0 in all results, member archive and native transcript; counts only),
   `CHECK 487 first wait timed out while the child ran …`, `CHECK 487 reply delivered once (DONE-492 through
   wait/status; graphtraj inputs pushed for that execution = 0)`, `CHECK 486 child n492 execution <id> ended
   completed, not interrupted`, `CHECK 486 member end normal (execution.yml outcome completed)`; all 478 CHECKs stay.
10. **N484 (new, 484):** `ctl492.py snap` records per agent execution: state, outcome, error code, notification,
    notification_error, owner pids (00 → `ctl/00.json`, I right before pip → `ctl/I.json`, N484 → `ctl/N484.json`).
    `N484` compares with I's snapshot (else 00's): `CHECK 484 pre-existing executions keep their final notification`
    (pending/queueing/held → final is listed as settled, information), `CHECK 484 new delivered executions have no
    notification_error`, `CHECK 484 notification_error only with notification unavailable|unconfirmed`.
11. **Mpre / Mps (new, 486):** Main runs `Mpre` after Vc, right before the user exits Main (`ctl/Mpre.json`). Mps
    (after `claude --continue`) prints `486 Main tool host: graphtraj-claude-host from .venv-runtime: yes`, lists
    `graphtraj-mcp` descendants of Main (`CHECK 486 no graphtraj-mcp server under the Claude Main`; 486 changes only
    `graphtraj-mcp`, which Codex/DSH/Pi Mains use), snapshots `ctl/Mps.json` and lists every execution whose
    state/outcome changed across the restart with its owner pids and parent (`CHECK 486 no execution ended interrupted
    across the Main restart`; normal ends of other Tasks' members are listed for Main to judge).
12. **480/481/485: no production runtime check.** They change only the Pi member sandbox (480), a user-started DSH
    Main (481) and the Codex Main completion checker (485); production Main and team are Claude. Their installed bytes
    are covered by proddiff (file by file), markers (480, 481 ×2, 485) and I's import lines.

## Steps

`S` = the script path above. Main's Bash never runs a foreground sleep; only I and R (USER's Terminal) wait in a loop.

| Step | Who | Command | Native dialog (choice) | Success observable | Wait limit |
|---|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | `expected 2.1.325: yes`; `isolation: OK`; `answer check: OK` (MODEL-OK, `claude-opus-5-5`, no Harness file, `echo of the prompt: no`); `control records snapshot 00.json`; `guard: Task 490 timer pid 39497: …` (present or absent, reported as is); `task graph rc=0`, `Task 492 named` ≥ 1; graphtraj 0.1.0 / graftling 0.5.0; `pip check rc=0`; `markers expected absent: PASS (10/10)`; `stopped: false`; `tmp/492/backup` No such file; `478 backup COMPLETE marker: present`; `MAIN=<id>` | 5 min |
| B | Main | `zsh $S B` | none | graphtraj-0.1.0 and graftling-0.5.0 wheels, `leaked: 0` | 3 min |
| V | Main | `zsh $S V` | none | `SAME` ×3, `plugin unchanged: no plugin/hooks trust dialog`, `DSH only (not the Claude plugin): …tool.mjs / finalize.mjs`, `source diff: empty`, markers present/absent `PASS (10/10)`, ✘ not more than baseline | 5 min |
| S | Main | `zsh $S S` (background) | none | `checkout … (clean)`, `test venv imports the checkout: OK`, `nested venv imports: OK`, `pytest temp base TMPDIR=…`; later `tail -n 25 …/S-suite.txt` shows `== DONE` and `== new failures: 0` | 3 min (+ background ≤ 30 min, overlaps) |
| Vu | USER | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/492/vproject && claude`, then `/exit` | folder trust for the new path: **Yes, proceed** | Vc then shows `graphtraj-claude-host loaded: YES` | — |
| Vc | Main | `zsh $S Vc` | none | `isolation: OK`, `answer check: OK` (VC-OK), `graphtraj-claude-host loaded: YES`, PASS tasks and agents | 3 min |
| Mpre | Main | `zsh $S Mpre` | none | `control records snapshot Mpre.json` | 1 min |
| — | USER | `/exit` in Main | none | Main closed | — |
| I | USER (Terminal) | `zsh $S I` | none (press Enter once) | waits for BLOCKING processes (never signals), backup, guard again, `control records snapshot I.json`, install; `Successfully installed …`, `PASS n FAIL 0`, `markers expected present: PASS (10/10)`, the 478 and 492 import lines, `SAME-AS-VALIDATED`, `plugin bytes as before the install`, Task 490 timer line | ~5 min + waiting for other Tasks' members |
| — | USER | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | none expected (plugin bytes unchanged); any other box: Esc and tell Main | Main resumes the same Session | — |
| M | Main | `zsh $S M` then paste prompt a, b | none | no notice seen before the resume repeats (definition item 4) | 2 min |
| Mps | Main | `zsh $S Mps` | none | `host uses .venv-runtime: yes`, `parent is claude --continue …: yes`, `outcome=ok` > 0, `486 Main tool host … yes`, two `CHECK 486 …: PASS` | 1 min |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` per file | 1 min |
| Nw | Main | `zsh $S Nw` (background, ≤ 15 min, ends itself) | none | `started at`; `Nw468.txt` shows `468 sampler: waiting …` | 1 min |
| N | Main | `zsh $S N`, paste the swarm prompt, save N.txt, N-main-notice.txt, N-reply.txt | none (child Bash approvals, if any, are the member's) | launch_status not failed; one completed notice of the member | 1 min + member ≤ 15 min |
| Nr | Main | `zsh $S Nr` | none | every CHECK PASS (459, 465, member Bash, 455, 452, 466 ×4, 477 ×3+, 468, 487 ×2, 486 ×2) | 2 min |
| N484 | Main | `zsh $S N484` | none | three `CHECK 484 …: PASS` | 1 min |
| S2 | Main | `zsh $S S2` (after `== DONE`) | none | `leftover processes of the suite (never signalled): 0` | 1 min |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`, markers present, `raw files containing an exported key value: 0`, Nw `== END` | 2 min |
| R | USER, only on failure | `/exit` Main, then `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/492/backup/tools/steps.zsh R` | none | venv and plugin `SAME differences=0`, entry files OK | ~5 min |

**Main's estimated run time** = sum of Main step wait limits = 5 (00) + 3 (B) + 5 (V) + 3 (S) + 3 (Vc) + 1 (Mpre)
+ 2 (M) + 1 (Mps) + 1 (inbox) + 1 (Nw) + 1 (N) + 2 (Nr) + 1 (N484) + 1 (S2) + 2 (done) = **32 min** of foreground
steps, plus the N member's ≤ 15 min wait = **47 min**; S's suite (≤ 30 min) runs in the background in parallel. The
user's I time (backup and install ~5 min) is extra, plus any wait for other Tasks' members.

**The user does only:** Vu (trust the new path once), `/exit` Main, run I, `claude --continue`, and R only on failure.

## Criterion → observable (definition items 1–4)

| Item | Observable |
|---|---|
| 1 install, 478's protections | V (`SAME` ×3, markers 10/10 both ways), Vc (`isolation: OK`, `answer check: OK`, real `claude -p` PASS), I (backup `COMPLETE`, guard again before pip, `PASS n FAIL 0` proddiff, imports, `SAME-AS-VALIDATED`), `done` (`PASS n FAIL 0`, key count 0); R from the backup's own copy of the tools |
| 2 full suite, no new failures | S's setup lines (checkout, imports, nested, TMPDIR outside), `== totals:`, `== failures in the suite: n (ATTRIBUTED: k)`, `== new failures: 0`, each failure rerun alone; S2 leftover 0 |
| 3 · 487 | Nr `CHECK 487 first wait timed out …: PASS`, `CHECK 487 reply delivered once …: PASS`, 477's `no parent input pushed for waited execution …: PASS` |
| 3 · 486 | Mps `486 Main tool host … yes`, `CHECK 486 no graphtraj-mcp server under the Claude Main: PASS`, `CHECK 486 no execution ended interrupted across the Main restart: PASS` (changes listed); Nr `CHECK 486 child … ended completed, not interrupted`, `CHECK 486 member end normal` |
| 3 · 484 | N484's three `CHECK 484 …: PASS` against `ctl/I.json` |
| 3 · 478's checks | Nr: 459, 465, member Bash, 455, 452, 466 (default, page back, keyword, credential masked), 477, 468 CHECKs |
| 3 · 480/481/485 | no runtime check (item 12 above): proddiff, markers, I's import lines |
| 4 restart and notices | M prompt a (no repeated notice), Mps, inbox `duplicate ids: 0`, one completed notice in `N-main-notice.txt` |

## Rehearsal

`zsh scripts/adopt-492/rehearse.zsh` in `$TMPDIR` (stub `claude` and `ps`; fake production venv built from a3fe1b92
wheels; fixtures by `rehearse_fixtures.py` in the real result shape). Result and count: `rehearsal-output.txt`.
Covered: markers both ways, timer 3(a) for a3fe1b92 → 9faa0274, `ans492.py` (positive; negatives: prompt echo, Harness
AGENTS.md path, distinctive AGENTS.md line, no result), 00 (vproject settings, answer check, Task 490 timer line, zombie
child as information, control snapshot), B, V (DSH listed apart), Vu, Vc's isolation and answer check, S's refusal,
S's setup without the suite (fresh checkout, own site-packages, nested check, TMPDIR), S's labels, S2, I (wait,
zombie under `$RT` never BLOCKING, backup, I snapshot, install, all import lines), R, Mpre/Mps (positive and a
negative with an interrupted end and a graphtraj-mcp under Main), Nw, Nr positive and negatives for 466, 477, 487,
486, 468 and 475's E2BIG case, N484 positive and a negative, N and M prompt contents, `done`'s key count.
Not rehearsed: real Claude Code (00's and Vc's `claude -p`, Vu's dialog, N's real member and child), the real suite,
real `ps` (zombie state and pid 39497 come from the stub), real production control records, 00's real `task graph`
call against production.
