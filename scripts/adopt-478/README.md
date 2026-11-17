# 478 production adoption: dev a3fe1b92 (466, 467, 468, 470–474, 476, 477; with 479, 482, 483)

`steps.zsh` installs the wheels built from `git archive a3fe1b92251d0510b962d8adddb49f690e1d1f07` into production
`.venv-runtime`. Production holds 475's `4ca57419137a7593f9275da210cd4c9ed54a8b99` now. It is
`scripts/adopt-475/` copied and adapted; every 475 protection stays: isolated real-Claude rehearsal project
(`tmp/478/vproject`, own git and `.graphtraj`, isolation check, Vu once), file-by-file equality (`proddiff.py`),
backup `tmp/478/backup` with rollback R, a guard that waits, never kills, and is rerun right before `pip install`,
no exported key value in raw output (`done` counts files). Versions do not change (graphtraj 0.1.0,
graftling 0.5.0); install claims come from `proddiff.py`, `markers.py` and I's import lines.

- Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/478-production-adoption-466-477/scripts/adopt-478/steps.zsh`
  (Main runs `zsh $S <step>`; every step prints the next command with real values).
- Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/478-production-adoption-466-477/adoption/raw-a3fe1b92/`
- Base: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/478/` (`backup/`, `vproject/`,
  `vvenv-a3fe1b92/`, `svenv-a3fe1b92/`, `sprobe-a3fe1b92/`, `scratch/`, `main.session`). 00 lists 475's backup
  `tmp/475/backup` (and its `COMPLETE` marker) and never modifies it; it is kept until 478 is accepted.
- Only `rehearse.zsh` sets `ADOPT478_*`.

## Changes from adopt-475

1. **Target.** `TARGET=a3fe1b92…`, `OLD=4ca57419…`, `TASK=478-production-adoption-466-477`, child `n478`, outputs
   `raw-a3fe1b92/` and `*-a3fe1b92`. Claude Code 2.1.325: `cv` prints
   `claude: <path> -> <resolved> | version: … | expected 2.1.325: yes|NO` in every real-host step.
2. **Markers** (`markers.py`, 16 lines the diff `4ca57419..a3fe1b92 -- src` adds; 470, 471, 472, 482, 483 change
   only tests/scripts, which are not installed). On `git archive` trees: `present: PASS (16/16)` for a3fe1b92,
   `absent: PASS (16/16)` for 4ca57419 (rehearsal-output.txt).

   | Task | File | Line |
   |---|---|---|
   | 466 | `graftling/sessions/reading.py` | `DEFAULT_COUNT = 5` |
   | 466 | `graphtraj/interfaces/agents.py` | `if action == "session_read":`; `def _member_session(self, arguments…)` |
   | 467 | `graphtraj/execution/execution_budget.py` | `def _superseded(notice…)`; `def _stop_cleared(notice…, state…)` |
   | 468 | `graftling/sessions/archive.py` | `def _identity(status: os.stat_result) -> tuple:`; `def batch(self) -> Iterator[None]:` |
   | 468 | `graphtraj/execution/runner_worker.py` | `BUDGET_SAMPLE_SECONDS = 1.0` |
   | 473 | `graftling/codex/managed_session.py` | `async def in_thread(function: Callable, *args: object) -> object:` |
   | 474 | `graphtraj/execution/runner_control.py` | `return {"alias": alias, "interrupt_status": "interrupted", "execution_record": "pending"}` |
   | 476 | `graphtraj/execution/approved_recovery.py` | `def _restore_reopened_worktree(project: Any, alias: str) -> None:` |
   | 476 | `graphtraj/execution/runner_control.py` | `def missing_worktree(worktree: Path, detail: str = "") -> RunnerError:` |
   | 477 | `graftling/control.py` | `def take_push(self, notice…)`; `def _waited(execution…)` |
   | 477 | `graphtraj/interfaces/agents.py` | `_main_notice.defers_push = True` |
   | 479 | `graphtraj/runtimes/pi/extension.mjs` | `const child = spawn(installedCommand('graphtraj-session', env.PATH), ['pi'], {` |

   I keeps 464's and 475's import lines and adds three:
   `466 session_read DEFAULT_COUNT 5 | agents _member_session: _member_session`,
   `468 archive _identity _identity | BUDGET_SAMPLE_SECONDS 1.0`, `477 take_push take_push | _waited _waited`
   (checked against the a3fe1b92 source tree in this sandbox; the rehearsal checks them after a stub install).
3. **Process kinds.** New spawn lines in the diff: two in `src/graphtraj/runtimes/pi/extension.mjs` (479: Pi's
   extension starts `<venv>/bin/graphtraj-session pi` and `… pi --collect` itself) and two threads (473's Codex owner
   thread `codex-owner-*`; 477's member-hold thread in the agents interface), which live inside existing processes.
   The guard's table does not change in effect: a `graphtraj-session pi` process runs from `$RT/bin`, so it was and
   stays BLOCKING; `kind_of` now names it `Pi session tool (479; a Pi member's)`. Production Main is Claude and uses
   no Pi extension, so none is expected. Timers NON-BLOCKING; Worker, swarm batch, hosts, anything under `$RT`
   BLOCKING; 450 marked processes information only.
4. **Plugin and trust dialog.** `git diff --stat 4ca57419 a3fe1b92 -- src/graftling/claude/host_context.mjs
   src/graftling/claude-plugin plugins '*.mjs' '*hooks*'` lists only `src/graphtraj/runtimes/pi/extension.mjs`
   (Pi, not the Claude plugin). V prints it apart (`Pi only (not the Claude plugin): …`) and checks the rest is
   empty. **Prediction: plugin bytes unchanged, no trust dialog at `claude --continue`.** I still prints
   `plugin bytes as before the install` or `CHANGED` from the real bytes.
5. **Guard in I** names active Tasks as 475 does: every Task whose `status` is not `integrated`, except 478.
6. **S (full suite, Main, background).** pytest temporary root is `PYTMP` = Main's `$TMPDIR` if outside the
   Harness, else `/private/tmp/graphtraj-478-pytest` (482); S stops if the root lies under the Harness and refuses
   while another `run_test_shards` runs. `_Srun` passes `TMPDIR=$PYTMP` to run_test_shards and to each
   single-failure rerun. It prints `== failures in the suite: n (ATTRIBUTED: k)` and `== new failures: n-k`.
   Compared with the full suites in the input Tasks' accepted records (leader.md):

   | Task | Accepted full suite (failed / passed / skipped) | Failing tests named |
   |---|---|---|
   | 466 | 4 / 4060 / 69 | agent_runner_cleanup `native_interrupt[waiting]`; claude_runner `child_registration_follows_its_owning_execution`; claude_termination `current_group[owned]`; hosted_cli `slow_read` |
   | 467 | none recorded | — |
   | 468 | 0 / 4057 / 69 | — |
   | 470 | 1 / 4050 / 69 | `test_srt_gone_before_launch_is_refused` (also `test_native_start_selects_harness_for_external_cwd` named) |
   | 471, 472, 479, 483 | none recorded | — |
   | 473 | 2 / 4048 / 71 | `test_claude_later_prompt_hook_is_answered_during_one_slow_collection`; `test_grandchild_under_a_codex_child_keeps_its_parentage` |
   | 474 | 2 / 4048 / 71 | `test_another_process_holding_a_record_lock_does_not_hold_the_host` |
   | 476 (R2) | 4 / 4051 / 71 | `test_srt_gone_before_launch_is_refused`; `test_replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session`; `test_public_interrupt_reconfirms_an_undrained_worker`; `test_installed_alias_control_resumes_and_interrupts_one_team_session`; `test_resume_with_restore_active_continues_the_same_session_to_integrated` |
   | 477 (R3) | 1 / 4089 / 71 | `test_resume_with_restore_active_continues_the_same_session_to_integrated` |
   | 482 | 2 / 4062 / 69 (temp outside) | `test_child_registration_follows_its_owning_execution`; `test_resume_with_restore_active_…_to_integrated`; also named `test_claude_later_prompt_hook_…`, `test_host_does_not_follow_request_or_response_links`, `test_native_start_selects_harness_for_external_cwd` |

   `ATTRIBUTED` in steps.zsh holds exactly these names (substring match on the test id) with the Task records that
   name them. The names were extracted from the leader.md texts; whether each record attributed its failure to
   load/environment or to an owner was not re-judged here (Main decides on any ATTRIBUTED failure).
7. **475's reported nr475 defects** (475 leader.md §3) were fixed by 471 (`f550a9fd`, already in a3fe1b92) in
   `nr475.py`, copied here as `nr478.py`: `SESSION-READ-… session=claude:<id>` is accepted (bare ids compared), and
   archives are found by their first line's header (directories are sha256 of `<runtime>:<id>`), exactly one, else
   NOT OBSERVED with the candidates. `steps.zsh`'s `nr_read` used `sessions/<session id>/session.jsonl` for the
   member; it now finds the member's archive by header too. Rehearsed (Nr positive with `claude:sess-c` and archives
   in arbitrary directories `cdir`/`mdir`).
8. **New production check N** (one dispatch; member `opus_coding_team.advisor` of Task 478; child `n478` via agents
   create, configuration `opus_coding_team.advisor`). Child: 43 scripted steps, one Bash each (step 01
   `echo n478-tool && sleep 3` for 459; step 02's sentence holds `KW478-ORCHID`; steps 02–42
   `seq -f '478-NN-%g' 1 400`; step 43 echoes `api_key=sk-probe478fake''value0000`, so the full fake value appears only
   in the child's tool output, never in a prompt), then exactly `DONE-478`. Member: create; agents wait (finite,
   repeated) and quote last_message; agents status `{agent}` and quote last_message; agents `session_read` on the
   child: default, `start -10 stop -5`, `search KW478-ORCHID` (compact lines only) plus the line
   `SESSION-READ-478 session=… events=…` (475's 465 check); own Bash `echo member-bash-ok`; list graphtraj parent
   inputs; retire the child; no submit_result/submit_report.
9. **Nw** starts two bounded background readers: `watch459.py` (459 descendants record; now ends when every
   execution ended, 478 has one) and `cpu468.py sample` (468: raw `ps -o pid,ppid,pcpu,time,etime,command` of the
   Task 478 member's Runner Worker every ~10 s, ≤ 15 min, ends when the Worker is gone). The Worker is the process
   to sample: an agents child is owned by a thread in the member's own Worker (452/459), and the child's Claude archive
   collection (468, `graftling/sessions/archive.py`) runs in that owner; while the member waits, the member is idle.
10. **Nr** CHECK lines (PASS only when observed; else BLOCKED/FAIL with the error text and file): 475's (459 Bash
    start, descendants record, no alive tool process; 465 settings and session_read id; member Bash; 455; 452;
    member end and report to Main), and 478's:
    - 466 `default read = last 5` (indices == `range(total)[-5:]`), `page back [-10:-5]`, `keyword search hits the
      child events holding the keyword (before the last 10)` (hit seq is a child-archive event containing it),
      `fake key redacted …` (counts only: child archive ≥ 1, results 0, `[redacted]` > 0, member archive 0, member
      native transcript 0; the value is never printed);
    - 477 `wait last_message == DONE-478`, `status last_message == DONE-478`, `child end not pushed to the member
      after wait delivered it (graphtraj notification inputs = 0)` (user/message events naming the execution with
      source graphtraj that are not tool results), and per execution `no parent input pushed for waited execution`;
    - 468 `Worker CPU below 475's 0.84-0.97 and < 0.25` (CPU-s per wall-s from the first and last sample of one
      Worker while the child ran, ≥ 60 s apart; else BLOCKED).
    449/451 is Main's side: exactly one completed notice of the member to Main (`N-main-notice.txt`, inbox
    `duplicate ids: 0`). The 475 rule "one parent input per child execution" is replaced by 477's "0 after wait".
11. **Preflight 00** makes one real read-only call through each host entry later steps use: `claude -p` (model and
    login line), production `graphtraj task graph --task-id 478` (the Task graph Main's tasks tool reads; prints
    `task graph rc=0 … Task 478 named: n`), and the guard/`task members` listing. Vc makes the candidate's hosted
    tools call (`tasks discover`, `agents status`) through real `claude -p` in `vproject`. 00 prints
    `stopped: false` and the role line: Task 478 is ready for dispatch.
12. **README 3(a) timer judgement (timer_probe.py on 4ca57419 → a3fe1b92):** a budget idle timer started before the
    install has `graphtraj.execution.execution_budget` (changed by 467) OLD in memory; at its threshold it loads the
    new `runner_control`, `runner_status`, `runner_worker`, `graftling.control`, `graftling.sessions.*`, whose imports
    from `execution_budget` (`caller_notice_fd`, `execution_budget_monitor`) exist in the old module; the lazy import
    succeeds. Effect: such a timer delivers without 467's superseded-stop handling (a stop notice that a recovery
    cleared may still be delivered once by a timer started before the install). Timers stay NON-BLOCKING; Main
    registers this if it matters.

## Steps

`S` = the script path above. Main's Bash never runs a foreground sleep; only I and R (USER's Terminal) wait in a loop.

| Step | Who | Command | Native dialog (choice) | Success observable | Wait limit |
|---|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | `expected 2.1.325: yes`; answer with `claude-opus-5-5`, `is_error False`; `task graph rc=0`, `Task 478 named` ≥ 1; graphtraj 0.1.0 / graftling 0.5.0; `pip check rc=0`; `markers expected absent: PASS (16/16)`; `isolation: OK`; `stopped: false`; `tmp/478/backup` No such file; `475 backup COMPLETE marker: present`; `MAIN=<id>` | 5 min |
| B | Main | `zsh $S B` | none | graphtraj-0.1.0 and graftling-0.5.0 wheels, `leaked: 0` | 3 min |
| V | Main | `zsh $S V` | none | `SAME` ×3, `plugin unchanged: no plugin/hooks trust dialog`, `Pi only (not the Claude plugin): …extension.mjs`, `source diff: empty`, markers present/absent `PASS (16/16)`, ✘ not more than baseline | 5 min |
| S | Main | `zsh $S S` (background) | none | `pytest temporary root: … (outside the Harness …)`; later `tail -n 25 …/S-suite.txt` shows `== DONE` and `== new failures: 0` | 2 min (+ background ≤ 30 min, overlaps) |
| Vu | USER | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/478/vproject && claude`, then `/exit` | folder trust for the new path: **Yes, proceed** | Vc then shows `graphtraj-claude-host loaded: YES` | — |
| Vc | Main | `zsh $S Vc` | none | `isolation: OK`, `graphtraj-claude-host loaded: YES`, PASS tasks and agents | 3 min |
| — | USER | `/exit` in Main | none | Main closed | — |
| I | USER (Terminal) | `zsh $S I` | none (press Enter once) | waits for BLOCKING processes (never kills), backup, guard again, install; `Successfully installed …`, `PASS n FAIL 0`, `markers expected present: PASS (16/16)`, the 466/468/477 import lines, `SAME-AS-VALIDATED`, `plugin bytes as before the install` | ~5 min + waiting for other Tasks' members |
| — | USER | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | none expected (plugin bytes unchanged); any other box: Esc and tell Main | Main resumes the same Session | — |
| M | Main | `zsh $S M` then paste prompt a, b | none | no notice seen before the resume repeats (definition item 4) | 2 min |
| Mps | Main | `zsh $S Mps` | none | `host uses .venv-runtime: yes`, `parent is claude --continue …: yes`, `outcome=ok` > 0 | 1 min |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` per file | 1 min |
| Nw | Main | `zsh $S Nw` (background, ≤ 15 min, ends itself) | none | `started at`; `Nw468.txt` shows `468 sampler: waiting …` | 1 min |
| N | Main | `zsh $S N`, paste the swarm prompt, save N.txt, N-main-notice.txt, N-reply.txt | none (child Bash approvals, if any, are the member's) | launch_status not failed; one completed notice of the member | 1 min + member ≤ 15 min |
| Nr | Main | `zsh $S Nr` | none | every CHECK PASS (459, 465, member Bash, 455, 452, 466 ×4, 477 ×3+, 468) | 2 min |
| S2 | Main | `zsh $S S2` (after `== DONE`) | none | `leftover processes of the suite (never signalled): 0` | 1 min |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`, markers present, `raw files containing an exported key value: 0`, Nw `== END` | 2 min |
| R | USER, only on failure | `/exit` Main, then `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/478/backup/tools/steps.zsh R` | none | venv and plugin `SAME differences=0`, entry files OK | ~5 min |

**Main's estimated run time** = sum of Main step wait limits = 5 + 3 + 5 + 2 + 3 + 2 + 1 + 1 + 1 + 1 + 2 + 1 + 2
= **29 min** of foreground steps, plus the N member's ≤ 15 min wait = **44 min**; S's suite (≤ 30 min) runs in the
background in parallel. The user's I time (backup and install ~5 min) is extra, plus any wait for other Tasks' members.

**The user does only:** Vu (trust the new path once), `/exit` Main, run I, `claude --continue`, and R only on failure.

## Criterion → observable (definition items 1–4)

| Item | Observable |
|---|---|
| 1 install, 475's protections | V (`SAME` ×3, markers 16/16 both ways), Vc (`isolation: OK`, real `claude -p` PASS), I (backup `COMPLETE`, guard again before pip, `PASS n FAIL 0` proddiff, imports, `SAME-AS-VALIDATED`), `done` (`PASS n FAIL 0`, key count 0); R exists from the backup's own copy of the tools |
| 2 full suite, no new failures | S's `== totals:`, `== failures in the suite: n (ATTRIBUTED: k)`, `== new failures: 0`, each failure rerun alone; S2 leftover 0; pytest temp outside the Harness |
| 3 production checks | Nr: 466 four CHECKs, 477 CHECKs, 468 CHECK with the CPU-s per wall-s figure vs 0.84–0.97, 475's CHECKs; raw ps lines in `Nw468-ps.txt` |
| 4 restart and notices | M prompt a (no repeated notice), Mps, inbox `duplicate ids: 0`, one completed notice in `N-main-notice.txt` |

## Rehearsal

`zsh scripts/adopt-478/rehearse.zsh` in `$TMPDIR` (stub `claude` and `ps`; fake production venv built from 4ca57419
wheels; fixtures by `rehearse_fixtures.py`): **ALL PASS (86 checks)**, saved in `rehearsal-output.txt`. Covered: markers,
timer 3(a), 00 (including that it makes the `task graph --task-id 478` call; the stub tree has no registered 478), B, V, Vu, Vc's isolation part, S's refusal and labels, S2, I (wait, backup, install, import lines),
R, Mps, Nw (both readers end by themselves), Nr positive and negatives for 466, 477, 468, the two fixed 475 defects
and 475's E2BIG case, N prompt contents, `done`'s key count.
Not rehearsed: real Claude Code (Vc's `claude -p`, Vu's dialog, N's real member and child), the real suite, real
`ps` sampling of a production Worker, 00's real `task graph` call against production (the stub tree has no Task
graph CLI state of its own).

## Correction (Round 2): 466 production check rerun — N466 / N466r

First production Nr: `CHECK 466 … FAIL (total=None indices=[])`. nr478.py did not unwrap the real result. In the
member archive, the tool_result content is a JSON string `{action, agent, session, execution, message, result:
{session, content, total, start, stop, events:[{index, seq, type, text}], earlier, pending, omitted}}` (seen in
member Session `claude:6d5623bc…` seq 151–152 through tasks session_read). Credential masking was never exercised:
the reads used content `text`, and the fake key is only in tool output. The 477, 468 and 475 checks stand.

`nr466.py` finds each `mcp__agents__agents` tool_use with feature `session_read` and its matching tool_result. It
walks nested dicts, lists and JSON strings until it finds a dict with `total`. If it finds none, it prints a
structural diagnostic (keys, types and lengths only).

| Step | Who | Command | Dialog | Success | Wait limit |
|---|---|---|---|---|---|
| N466 | Main | `zsh $S N466`, then paste the swarm prompt; save `N466.txt` (swarm result, has "alias") and `N466-reply.txt` | none | launch_status not failed; the member quotes 5 compact lines | 1 min + member ≤ 5 min |
| N466r | Main, after the member's completion notice | `zsh $S N466r` | none | four `CHECK 466 …: PASS` lines | 2 min |

The N466 member (Task 478, `opus_coding_team.advisor`, no submit calls) reads the retired probe child by
`session` `claude:5585dafa-88d0-4ff2-8633-05090a2d9c7d`: (1) default; (2) start -10 stop -5; (3) search
KW478-ORCHID; (4) content tools, search probe478; (5) content all, start -6.

| Criterion (definition 3, 466) | Observable in N466r |
|---|---|
| default = last 5 | `CHECK 466 default read = last 5: PASS (total=… indices=range(total)[-5:])` |
| one page back | `CHECK 466 page back [-10:-5]: PASS` |
| keyword search correct | `CHECK 466 keyword hits are child-archive events holding the keyword: PASS` (hit seqs ⊆ child-archive seqs containing KW478-ORCHID) |
| credentials masked | `CHECK 466 credential masked …: PASS`: in the tools/all results the fake value count is 0, '[redacted]' appears at the events whose seq holds the value in the child archive, and the member archive and native transcript contain the value 0 times (counts only) |

Rehearsal: `rehearse466.py` builds fixtures in the real shape (one masked positive and one leaking negative), and
the N466 prompt was printed in a fake Harness. Result: ALL PASS, saved in `rehearsal466-output.txt`.

**Correction (Round 3, masking only).** Search runs on redacted text, and `api_key=sk-…` becomes `api_key="[redacted]"`, so searching for the value can never hit. nr466.py now ignores child events without a seq; before, it crashed with an int-vs-None TypeError.
`N466b` (Main; 1 min + member ≤ 5 min; no dialog): a new Task 478 member makes three reads with content tools: search api_key, search [redacted], and the default. It reports counts and yes/no only. Save `N466b.txt` and `N466b-reply.txt`.
`N466br` (Main; 2 min; no dialog): `CHECK 466 credential masked …: PASS` only if one result shows an event at a child seq holding the value with `[redacted]`, and the value appears 0 times in all results, the member archive and the native transcript. Default/page back/keyword are not re-checked (they passed in N466r). Rehearsal: `rehearsal466-output.txt`, ALL PASS.
