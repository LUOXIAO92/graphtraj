# 464 production adoption: dev b3d522ad (457, 459; not 460-463) and the production check

`steps.zsh` installs the wheels built from `git archive b3d522ad6f1a90c33dad19f81babc9c1d587d24f` (a fixed id,
not HEAD) into production `.venv-runtime`. Production holds 458's 4e3aafce now. The steps and protections are
458's (`scripts/adopt-458/`):

- an isolated real-Claude rehearsal (Vc);
- file-by-file equality (`proddiff.py`);
- a backup with rollback (R);
- a guard that waits, and never kills, until no BLOCKING process runs, rerun right before `pip install`.

The versions do not change (graphtraj 0.1.0, graftling 0.5.0), so versions prove nothing.
Install claims come from `proddiff.py` and from `markers.py`.

Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/464-production-adoption-457-459/scripts/adopt-464/steps.zsh`
Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/464-production-adoption-457-459/adoption/raw/`
Base: `~/graphtraj-adoption-464` (backup at `backup/`). The 393, 417, 448, 453 and 458 bases are never touched.
**458's backup (`~/graphtraj-adoption-458/backup`) stays untouched until 464 is accepted.**

## Changes from adopt-458

1. **Target.** `TARGET=b3d522ad6f1a90c33dad19f81babc9c1d587d24f`, `OLD=4e3aafce…` (production now),
   `TASK=464-production-adoption-457-459`, base `~/graphtraj-adoption-464`. 00 lists the 393/417/448/453/458
   backups without touching them. R runs from the 464 backup's own copy of the tools (`backup/tools/steps.zsh`).
2. **Guard.** The waiting line names Tasks 460, 461, 462 and 463, in Chinese and English: wait for their members,
   do not kill them; Ctrl-C gives up safely. The process kinds were rechecked against 4e3aafce..b3d522ad (table
   below): **no new process kind**.
3. **Mixed version (as 458's 3(a)).** `timer_probe.py` now also calls `graftling.control._stop_escaped` after the
   swap, which makes its lazy imports (`member_processes`, `review`, `tool_descendants`). Result below.
4. **Markers.** `markers.py` holds 11 lines from the actual diff 4e3aafce..b3d522ad (table below), present in the
   candidate and absent in production. I's import line prints
   `457 _stop_escaped | 459 SAMPLE_SECONDS 1.0 DescendantSampler | 459 correction shown_command` from `.venv-runtime`.
5. **Plugin and hooks.** No plugin or hook source changes in 4e3aafce..b3d522ad. The prediction stays
   **no trust dialog at resume**; V and I keep their byte checks.
6. **S.**
   - Refuses unless `git diff --quiet b3d522ad HEAD -- src tests pyproject.toml` holds and those paths are clean.
   - Refuses while another `run_test_shards` runs; Main queues suites, one at a time on this host.
   - Same venv as 458's S: editable from this Worktree, production click/yaml/websockets copied in.
   - Baseline: 459 at 81fc829e, 2 failed, 4024 passed, 69 skipped. Its two failures are BASELINE:
     `tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations[waiting]` and
     `tests/test_claude_runner.py::test_second_child_batch_starts_while_first_batch_is_running`.
     For comparison it also prints 458's 4e3aafce result: 0 failed, 4011 passed, 71 skipped.
   - Every suite failure and both baseline ids are rerun alone with `-rA`; each line says `(failed|passed in the suite)`.
   - It prints run_test_shards' own `leftover processes of run …` line.
7. **S2.** Unchanged in kind: leftover processes of the suite, counted, never signalled.
8. **Nw (new), N, Nr.**
   - N: the member (an `opus_coding_team.advisor` of Task 464) creates `n464` with configuration
     `opus_coding_team.advisor` and the message
     `Use the Bash tool once to run exactly: echo n464-tool && sleep 3 . Then reply DONE-464.`, waits, sends once
     (`PONG-464-2`, no tool), waits, quotes the raw create result, its own task_sessions entry and the child's status
     entry, reports every source-graphtraj input verbatim, retires the child, and does not call submit_result or
     submit_report. One clause was added: if the child asks the member to approve that one Bash command, the member
     approves exactly that command once.
   - **Nw (Main, before N, background, read only).** The 459 sampler *drops* a recorded process once it has ended
     (`DescendantSampler.sample` keeps only entries whose pid still has its start time). After a normal end the
     record file therefore no longer lists `echo n464-tool && sleep 3`. Nw (`watch459.py`) reads the child record and
     its descendants record every 0.2 s and copies every distinct content to `raw/Nw-snapshots.jsonl`. It never
     writes production and never signals. It ends by itself when both n464 executions have ended, when the child is
     retired, or after 15 minutes (`== END` in `raw/Nw.txt`). Without Nw the second 459 line can only say
     `NOT OBSERVED`.
   - Nr keeps 458's CHECK lines and adds (`nr459.py`, read only, never signals):
     - `CHECK 459 create execution recorded tool_marker and tool_descendants` (booleans only; the marker value is
       never printed);
     - `CHECK 459 descendants record lists the Bash tool command` (an entry of the create execution's record, in an
       Nw snapshot or now, whose redacted argv names `n464-tool` or `sleep 3`);
     - `CHECK 459 no recorded tool process alive after the end` (no recorded identity alive with the same pid, uid
       and start time, judged by the target's own `graftling.tool_descendants._alive` imported from B's
       `git archive`; and no process whose argv names `n464-tool`). It is `PENDING` while an execution still runs,
       and `CHECK BY HAND` if ps or libproc cannot see Main's host (a restricted shell);
     - the `escaped_processes` kept at the normal end (where it is stored: see below).
9. **M, Mps, inbox, done.** As 458's with the new names. M: ends of 460-463 members that arrived while Main was
   exited may arrive once; they must not repeat. done also prints the Nw `== END` line.
10. **Rules.** Every step prints who runs it, its dialog (or none), how to judge success and the next command with
    real values. Main steps contain no foreground `sleep` and Main runs them as `zsh $S <step>` (not `zsh -c`). No
    step signals a process it did not start. Only rehearse.zsh sets `ADOPT464_*`.

## Guard: process kinds that use `.venv-runtime` (rechecked for 4e3aafce..b3d522ad)

`git diff --quiet 4e3aafce b3d522ad` holds for `budget_idle_timer.py`, `execution_budget.py`, `runner_control.py`,
`runner_worker.py` and `teams/`: nothing that starts a process changed. The product diff touches only
`graftling/claude/{driver,execution}.py`, `graftling/control.py`, `graftling/member_processes.py`, the new
`graftling/tool_descendants.py` and `graphtraj/execution/agent_driver.py`.

| Kind (argv) | Started by | Class |
|---|---|---|
| `-m graphtraj.execution.budget_idle_timer` | `budget_idle_timer.py` `start_idle_budget_timer` | **NON-BLOCKING**, listed separately (judgement 3(a)) |
| `-m graphtraj.execution.runner_worker <runner>/sessions/<alias>/{launch,resume}.yml` | `runner_control.py` (resume), `teams/team_round.py` (launch) | BLOCKING: a member is executing |
| `-m graphtraj.teams.team_round` | `teams/team_round.py` | BLOCKING |
| `… claude.host serve --config <this project>` | Claude Code, from `.mcp.json` (Main's host) | BLOCKING: Main has not exited |
| other `… serve`, the DSH watcher, a CLI call, anything else under `$RT` or naming Main's id | members' own hosts, Main's commands | BLOCKING |
| 450 marked process (`GRAFTLING_MEMBER_RUN` in `ps -E`) | `graftling/member_processes.py` | information only |

What 457 and 459 change here — **confirmed: no new process kind.**

- **459** `DescendantSampler` is a daemon thread named `tool-descendants` inside the owner of a Claude execution
  (`graftling/claude/execution.py`: `self.descendants.start(self.proc.pid)`), so inside a Worker, a host or a
  member's own host. It writes `tool-descendants-<native id>.json` in the run directory; it starts no process.
- **457/459** stop escaped tools inside existing calls: the owner at its end (`stop_tool_processes` in
  `execution.py`) and `_stop_escaped` inside the owner-exited reconcile of `AgentControl` (any record read).
  Those stop only the execution's own recorded or marked tools, never a member Worker.
- 459's `member_processes._user_pids` retry changes no process.
- A Worker running 4e3aafce code at install time keeps its old in-memory code; I waits for it (BLOCKING).

### Judgement on 3(a): a timer started under 4e3aafce that wakes after the install

At start a timer loads 10 modules (`budget_idle_timer`, `execution_budget`, `runner_heartbeat`, `runner_io`,
`runner_models`, `file_lock`, `configuration.project_roles` and their packages). **None of them changes in
4e3aafce..b3d522ad**, so its loop is exactly the one a new timer has.

`timer_probe.py` (run by `rehearse.zsh`): load the 4e3aafce modules as a timer does, replace the package files
with b3d522ad's as pip does, run the threshold's lazy imports, then call `graftling.control._stop_escaped` on an
execution whose descendants record is empty (it scans nothing and signals nothing). Result lines:

```
lazy import at the threshold: OK
graftling.control from new file (has _stop_escaped): True
_stop_escaped lazy imports after the install: OK {"found": [], "stopped": [], "remaining": []}
changed modules that were OLD in memory before the install: none
changed modules loaded NEW after the install: ['graftling.control', 'graftling.member_processes', 'graftling.tool_descendants']
```

**Such a timer delivers its notice normally, through the new code. Timers stay NON-BLOCKING.**

## Plugin and hooks: 4e3aafce..b3d522ad

`git diff --stat 4e3aafce b3d522ad -- '*.mjs' '*hooks*' '*plugin*' src/graftling/claude-plugin` lists only
`scripts/adopt-458/adopt_plugin.py` (a script, not installed). The rehearsal regenerated the plugin with the new
code: `SAME` for `plugin.json`, `hooks.json` and `host_context.mjs`, and V's source diff was empty.
**Prediction: resume shows no plugin/hooks trust dialog.** V checks this on the real production copy, and I checks
it again against the backup.

## Markers (`markers.py`, from the actual diff)

| Task | File (site-packages) | Line added |
|---|---|---|
| 457 | `graftling/claude/driver.py` | `facts = {'tool_marker': turn.member_marker}` |
| 457 | `graphtraj/execution/agent_driver.py` | `marker = getattr(turn, 'member_marker', None) if run.runtime == 'claude' else None` |
| 457 | `graftling/control.py` | `def _stop_escaped(execution: dict) -> None:` |
| 457 | `graftling/control.py` | `_stop_escaped(current)` |
| 459 | `graftling/tool_descendants.py` | `SAMPLE_SECONDS = 1.0` |
| 459 | `graftling/tool_descendants.py` | `class DescendantSampler:` |
| 459 | `graftling/claude/execution.py` | `self.descendants.start(self.proc.pid)` |
| 459 | `graphtraj/execution/agent_driver.py` | `facts['tool_descendants'] = str(Path(turn.tool_descendants).resolve())` |
| 459 | `graftling/control.py` | `"tool_descendants"}` (allowed process fact) |
| 459 | `graftling/member_processes.py` | `raise OSError(0, 'proc_listallpids kept filling its buffer')` |
| 459 (b3d522ad) | `graftling/tool_descendants.py` | `'argv': shown_command(_argv(item.pid))` (recorded argv redacted) |

## Where the normal-end facts are (code at b3d522ad)

- Child record: `.graphtraj/swarm/control/agents/<agent>.json`, `executions[*].process.tool_marker` (457) and
  `.tool_descendants` (459, absolute path), written by `graphtraj/execution/agent_driver.py` through
  `ExecutionEvents.process`.
- Run directory: `.graphtraj/swarm/native/<agent>/` (`control.py`, `Run.directory`). It holds
  `tool-descendants-<native id>.json` (the sampler's record) and `claude-termination-<native id>.yml`.
- **`escaped_processes` at a normal end** is the owner's own reclaim result
  (`execution.py`: `escaped = redact(stop_tool_processes(…))`). It is written to
  `claude-termination-<native id>.yml` (and the diagnostics' `termination`), and into the native outcome only when
  something was found. The agents driver passes only outcome and last message to `finished`, so **the execution
  record has no `escaped_processes` at a normal end**. Only an owner-exited reconcile (`_stop_escaped`) writes it
  there. Nr prints both: the record's field (expected absent) and the termination file's.

## Steps

Each step prints who runs it, its dialog (at most one), how to judge success and the next command with real
values. 00 detects the Main Session id and saves it to `~/graphtraj-adoption-464/main.session`.

| Step | Who | Command | Dialog | Success |
|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | zsh; `answer:` with `claude-opus-5-5`, `is_error False`; 0.1.0/0.5.0; `pip check rc=0`; `markers expected absent: PASS (11/11)`; member list (460-463 may run); advisor role lines; classified guard (timers NON-BLOCKING); Task 464 `stopped: false`; no 464 backup yet, 393/417/448/453/458 backups listed; `MAIN=<id>` |
| B | Main | `zsh $S B` | none | two wheels with sha256; `leaked: 0` |
| V | Main | `zsh $S V` | none | `SAME` ×3 plugin files; `source diff: empty`; `plugin unchanged: no plugin/hooks trust dialog is expected`; `markers expected present: PASS (11/11)` and `absent: PASS (11/11)`; no STOP; ✘ candidate ≤ baseline; `read_session … failures=0` |
| S | Main (queued: refuses while another run_test_shards runs) | `zsh $S S` (returns at once) | none | `Worktree HEAD … equal b3d522ad… and clean`; `click 8.5.0`; `graphtraj.__file__` under this Worktree; poll `tail -n 25 …/raw/S-suite.txt` until `== DONE`; no `NEW` failure; every failure and both 459 baseline ids have an `… alone: <id> (…in the suite)` line; the 454 leftover line |
| S2 | Main, after `== DONE` | `zsh $S S2` | none | `leftover processes of the suite (never signalled): 0` (else the list goes to Main) |
| Vc | Main | `zsh $S Vc` | none | `graphtraj-claude-host loaded: YES`; `PASS mcp__agents__tasks`, `PASS mcp__agents__agents` |
| Vu | **USER**, only if Vc says `loaded: NO` | `cd ~/graphtraj-adoption-464/vproject && claude`, then 'Yes, proceed', then `/exit` | folder trust | Main reruns Vc |
| — | **USER** | `/exit` in Claude Main | none | |
| I | **USER** (Main exited) | `zsh $S I` (Enter to confirm) | none | waits while BLOCKING processes (e.g. Tasks 460-463's) run, never kills; `-rw-------` ×3; `Successfully installed`; `PASS n FAIL 0`; `markers expected present: PASS (11/11)`; the 457/459 import line; `SAME-AS-VALIDATED`; `plugin bytes as before the install: no trust dialog expected`; install-window BLOCKING list (information). On failure it prints R |
| — | **USER** | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | none expected (plugin bytes unchanged); any dialog: decline and tell Main | |
| M | Main | `zsh $S M`, then paste its prompts | none | criterion 4: notices display normally; none seen before the install appears again (460-463 ends during the exit may arrive once) |
| Mps | Main | `zsh $S Mps` | none | host uses `.venv-runtime`; `parent is claude --continue or --resume <id>: yes`; `outcome=ok` |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` |
| Nw | Main, right before N | `zsh $S Nw` (returns at once) | none | `started at …`; `tail -n 3 …/raw/Nw.txt` shows `start: watching` |
| N | Main | `zsh $S N`, paste the swarm prompt; save the swarm result to `raw/N.txt`, the member's completion notice to `raw/N-main-notice.txt`, its reply to `raw/N-reply.txt` | none (the child's Bash request, if any, goes to the member) | an `opus_coding_team.advisor` member of Task 464 creates `n464` (configuration `opus_coding_team.advisor`), runs the one Bash command, waits, sends once, waits, quotes status, reports source-graphtraj inputs, retires the child; no submit_result/submit_report |
| Nr | Main, after the member's end | `zsh $S Nr` | none | CHECK lines all PASS (below); the escaped_processes lines; then the printed session_read, task_sessions and **retire-by-agent** prompts |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`; `markers expected present: PASS`; `raw files containing an exported key value: 0`; S `== DONE`; S2 leftover line; `Nw watcher: … == END` |
| R | **USER** (Main exited), only on failure | `zsh ~/graphtraj-adoption-464/backup/tools/steps.zsh R` | none | waits like I; venv and plugin `SAME differences=0`; entries OK; pip check; then `claude --continue` |

Nr's CHECK lines (criterion 3):

- **459 (normal end):**
  - `CHECK 459 create execution recorded tool_marker and tool_descendants`;
  - `CHECK 459 descendants record lists the Bash tool command` (needs Nw);
  - `CHECK 459 no recorded tool process alive after the end` (read only; never signalled);
  - information: the record's `escaped_processes` (expected absent) and the termination file's
    (`found=… stopped=… remaining=… error=…`).
- **455:** `CHECK 455 stored record: configuration and model not null`; `CHECK 455 create/status result quoted by the member …`.
- **452:** `CHECK 452 child execution <id> ended completed, not owner-exited` ×2; `CHECK 452 member execution ended and recorded`;
  `CHECK 452 member reported its end to Main`; `CHECK 452 no runner_worker of the member alive after its end`
  (read-only `ps`; if one is still there, rerun Nr a minute later and never kill it).
- **449/451:** `CHECK execution <id> notification delivered` ×2; `CHECK 449/451 one parent input for execution <id>` ×2
  (archive events of type `user/message` naming the execution with source graphtraj; anything else is
  `CHECK BY HAND` with the printed session_read prompt, as 453 and 458 did).
- `CHECK swarm result has agent`.

The user does only these:

- Vu, only if needed;
- `/exit` Main;
- run I while Main is exited; it may wait for Task 460-463 members to end (do not kill them);
- `claude --continue`;
- R, only on failure.

If I is abandoned with Ctrl-C after the backup (during the second wait), production is unchanged, but `backup/`
exists without `INSTALL-STARTED`. Main renames it aside before I is run again.

## What was rehearsed

`rehearse.zsh` ran in the sandbox on a fake production in `$TMPDIR`: old wheels from 4e3aafce, new from b3d522ad;
click and yaml from Conda and an import-only websockets stub; `claude` and `ps` stubs. The ps stub lists Main's host
(parent `claude --continue`), a budget timer, and a Task 460 member Worker that goes away after about 3 s.

Result: **ALL PASS (55 checks)**. Output: `rehearsal-output.txt`. These passed:

- 3(a) timer probe: lazy imports at the threshold and `_stop_escaped`'s lazy imports work after the install; no
  changed module was old in memory.
- 00: Main found through `--continue`; timer NON-BLOCKING; the 418 variable reported; markers absent (11/11).
- B; V (plugin SAME ×3, no-dialog prediction, source diff empty, markers present/absent, no entry-file writes).
- S: refusal while another run_test_shards runs; Worktree equality with b3d522ad.
- S2 on a synthetic finished suite: 2 leftovers counted; an older basetemp ignored.
- I: waited with the Tasks 460-463 line (Chinese and English, no kill, Ctrl-C safe); the Worker shown with its Task
  460; the timer never BLOCKING. Then `-rw-------` ×3, `PASS n FAIL 0`, markers 11/11, the 457/459 import line,
  plugin bytes as before, `claude --continue` printed; backup tools include `markers.py`, `nr459.py`, `watch459.py`.
- R from the backup's tools; markers absent again after R.
- Mps with a `claude --continue` parent.
- Nw: started in the background, copied the record while the synthetic child "ran" (an entry naming n464-tool),
  ended by itself with `== END (both executions ended)`, never copied the marker value.
- Nr on synthetic records, all CHECK lines PASS, including the three 459 lines (the recorded tool process is a real
  process that had ended) and the termination file's `escaped_processes`; the marker value never printed.
- Nr negative: null configuration, owner-exited end, live member Worker (458's), and for 459: no `tool_marker`
  → FAIL; Nw ran but no record named the command → FAIL; a recorded entry still alive with its start time (a real
  `/bin/sleep` the rehearsal started) and a process naming n464-tool → `FAIL (1 alive, 1 named`; the record's
  owner-exited `escaped_processes` printed; the live process was not signalled by Nr (the rehearsal stopped its own
  sleep afterwards).
- M names Tasks 460-463; N names task 464, the preset role and the exact Bash command, forbids
  submit_result/submit_report and asks for source-graphtraj inputs verbatim.

Not rehearsed:

- real `claude -p` (00, Vc), `claude plugin validate`, and Claude Code's own Bash tool shell under a real child;
- the full suite (S beyond its refusal) and S2 against real processes;
- real `ps` and `ps -E` against production, and libproc visibility from Main's shell;
- the real N dispatch, the child's possible Bash approval request, and Nw against a real sampler's timing (a 3 s
  `sleep` is sampled about once a second; Nw reads every 0.2 s);
- the waiting loop's Ctrl-C path;
- `nohup` was replaced by zsh `&!` plus SIGHUP ignored in the watcher, because `nohup` cannot detach in the sandbox.
  S still uses `nohup` as in 458 (it worked in 458's production run).
