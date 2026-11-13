# 458 production adoption: dev 4e3aafce (451, 452, 454, 455, 456; not 457) and the production check

`steps.zsh` installs the wheels built from `git archive 4e3aafce` (a fixed id, not HEAD)
into production `.venv-runtime`. Production holds 453's cfd5e432 now. The steps and
protections are 453's:

- an isolated real-Claude rehearsal (Vc);
- file-by-file equality (`proddiff.py`);
- a backup with rollback (R);
- a guard that waits, and never kills, until no BLOCKING process runs, rerun right before `pip install`.

The versions do not change (graphtraj 0.1.0, graftling 0.5.0), so versions prove nothing.
Install claims come from `proddiff.py` and from `markers.py`.

Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/458-production-adoption-451-456/scripts/adopt-458/steps.zsh`
Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/458-production-adoption-451-456/adoption/raw/`
Base: `~/graphtraj-adoption-458` (backup at `backup/`). The 393, 417, 448 and 453 bases are never touched. 453's backup is kept until 458 is accepted.

## Changes from adopt-453

1. **Target.** The target is `TARGET=4e3aafce…`, `TASK=458-…`, base `~/graphtraj-adoption-458`. 00 lists the 393/417/448/453 backups without touching them.
2. **Guard.**
   - The waiting line names Task 457, in Chinese and English: wait for the listed members, do not kill them, and Ctrl-C gives up safely.
   - A Worker is shown as `[member Worker of Task <id> (<alias>)]`; the Task id comes from its `sessions/<alias>/` argv.
   - The process kinds were rechecked against cfd5e432..4e3aafce; the table below has the result.
3. **V.**
   - V records the source diff of the plugin and hook sources for cfd5e432..4e3aafce (`raw/V-source.diff`, expected empty) and the bytes diff of the regenerated plugin (`raw/V-plugin.diff`).
   - The new prediction is **no trust dialog at resume**. A changed plugin byte now stops V.
   - The `const PLUGIN = null;` check is kept.
   - 449's `body.execution` checks are replaced by `markers.py`. Its 8 markers must be present in the candidate venv and absent in production.
4. **I.**
   - `markers.py` checks the installed site-packages (`markers expected present: PASS (8/8)`).
   - An import line prints 451's `CHILD_SWEEP_SECONDS`, 456's `_reconcile_exited_owner` and 454's `DELIVERY_SECONDS` from `.venv-runtime`.
   - I compares the regenerated plugin with the backup (`plugin bytes as before the install: no trust dialog expected`).
   - `markers.py` is copied into `backup/tools`.
5. **S.**
   - S refuses unless `git diff --quiet 4e3aafce HEAD -- src tests pyproject.toml` holds and those paths are clean.
   - It refuses while another `run_test_shards` runs (457's suite may need the host; Main queues suites).
   - The baseline is 456's at 93cf3b42: 2 failed, 3985 passed, 69 skipped. Its two failures are BASELINE.
   - Every suite failure is rerun alone with `-rA`. Both baseline ids are rerun alone too, even when they pass in the suite, and each line says `(failed|passed in the suite)`.
   - S prints run_test_shards' own 454 line (`leftover processes of run …`).
6. **S2 (new, Main, after `== DONE`).** S2 gives 454's leftover count. It lists and counts processes whose `ps -E` line (argv or environment) names any of:
   - the suite venv;
   - a pytest base temporary directory newer than the one S recorded before the run;
   - this run's `PYTEST_GRAPHTRAJ_RUN=<run id>-`.

   It never signals them.
7. **N/Nr: criterion 3.**
   - The member creates `n458` with `configuration opus_coding_team.advisor`.
   - It quotes the raw create result, its own task_sessions entry and the child's status entry.
   - It reports every input whose JSON has source graphtraj, verbatim.
   - It retires the child, and must not call `submit_result` or `submit_report`. 453's member did call submit_result.
   - Main saves `raw/N.txt` (swarm result), `raw/N-main-notice.txt` (Main's received completion notice) and `raw/N-reply.txt` (the member's reply). Nr prints one CHECK line per observable (table below).
   - 453's lesson: raw line counts include tool results and quotes. Nr therefore counts only archive events of type `user/message` that name the execution with source graphtraj. Any other count is `CHECK BY HAND`, and Nr prints the session_read prompt for Main to count by event type.
8. **M.** At resume, ends of 457 (or other) members that came while Main was exited may arrive once; they must not repeat. `/agents-context` is left out of Main's prompts because only the user can type it.

## Guard: process kinds that use `.venv-runtime` (rechecked for cfd5e432..4e3aafce)

| Kind (argv) | Started by (code at 4e3aafce) | Class |
|---|---|---|
| `-m graphtraj.execution.budget_idle_timer` | `budget_idle_timer.py` `start_idle_budget_timer` (a detached process when a timed Session goes idle) | **NON-BLOCKING**, listed separately (judgement 3(a)) |
| `-m graphtraj.execution.runner_worker <runner>/sessions/<alias>/{launch,resume}.yml` | `runner_control.py:1364` (resume), `teams/team_round.py:1344` (launch) | BLOCKING: a member is executing (see 451/452 below) |
| `-m graphtraj.teams.team_round` | `teams/team_round.py:382` (a swarm batch dispatching members) | BLOCKING |
| `… claude.host serve --config <this project>` | Claude Code, from `.mcp.json` (Main's host) | BLOCKING: Main has not exited |
| other `… serve`, the DSH watcher, a CLI call, anything else under `$RT` or naming Main's id | members' own hosts, Main's commands | BLOCKING |
| 450 marked process (`GRAFTLING_MEMBER_RUN` in `ps -E`) | `graftling/member_processes.py` | information only |

What the adopted Tasks change here:

- **No new process kind.**
  - 451's child sweep is a daemon thread (`child-sweep-<alias>`) inside the Worker, every `CHILD_SWEEP_SECONDS = 15.0`. `runner_worker.py` starts it and stops it in `finally`.
  - 452 changes threads, not processes.
  - 454's run marker `PYTEST_GRAPHTRAJ_RUN` applies to test runs only.
  - 456 runs inside existing calls.
- **452.** Under 4e3aafce, the owner thread of an agents child (`agents-<agent>`, `claude-<agent>`) is non-daemon. A Worker may therefore stay alive after its member's turn ended, until its child reports its end. It is still a member Worker and stays BLOCKING; I waits for it. A Worker running cfd5e432 code at install time (for example a 457 member's) keeps its old in-memory code, and I waits for it in the same way. After the install, I lists any BLOCKING process that started during the install window, as information for Main.

### Judgement on 3(a): a timer started under cfd5e432 that wakes after the install

At start, a timer imports only these modules:
`budget_idle_timer`, `execution_budget`, `runner_heartbeat`, `runner_io`, `runner_models`, `file_lock`, `configuration.project_roles` (10 modules with the packages).

Among the files 4e3aafce changes, only `budget_idle_timer.py` itself is in that set. `git diff --quiet cfd5e432 4e3aafce` holds for `runner_models`, `execution_budget`, `runner_heartbeat`, `runner_io`, `file_lock` and `configuration/`.

At the threshold, `execution_budget.deliver_parent_notices` lazily imports `runner_control.notify_direct_parent` and `runner_status.read_alias_mapping` (`execution_budget.py:311-312`). After the install, these load from the new files. They pull in 34 modules, all new, including the changed `graftling.control`, `graftling.member_processes` and `runner_control`. `notify_direct_parent`'s signature is unchanged, and no new module needs a name that the old in-memory modules lack.

I checked this in the sandbox (`timer_probe.py`, run by `rehearse.zsh`):

1. Load the cfd5e432 modules as a timer does.
2. Replace the package files with 4e3aafce's, as pip does.
3. Run the lazy imports. Result: `lazy import at the threshold: OK`, `runner_control from new file: True`, and `changed modules that were OLD in memory before the install: ['graphtraj.execution.budget_idle_timer']`.

So unlike 453's case (an `ImportError` that dropped the notice), **such a timer delivers its notice normally**. It does so through the new `runner_control`, with the new 451/456 code on the delivery path.

The one difference: the running timer keeps its old cfd5e432 loop. That loop lacks 454's 300 s delivery bound and the "Task directory removed" exit. Such a timer behaves exactly as it did before the install, with no new failure mode, and every timer started after the install has 454's bound. **Timers stay NON-BLOCKING.**

## Plugin and hooks: cfd5e432..4e3aafce

`git diff --stat cfd5e432 4e3aafce` touches no plugin or hook source. The only `*.mjs`/`*plugin*`/`*hooks*` match is `scripts/adopt-453/adopt_plugin.py` (a script, not installed). `src/graftling/claude/host_context.mjs` and `src/graftling/claude-plugin` are unchanged. The rehearsal regenerated the plugin with the new code: `SAME` for `plugin.json`, `hooks.json` and `host_context.mjs`. **Prediction: resume shows no plugin/hooks trust dialog.** V checks this on the real production copy, and I checks it again against the backup.

## Markers (`markers.py`, from the actual diff)

| Task | File (site-packages) | Line added |
|---|---|---|
| 451 | `graphtraj/execution/task_agents.py` | `CHILD_SWEEP_SECONDS = 15.0` |
| 451 | `graphtraj/execution/runner_worker.py` | `watch_member_children(` |
| 452 | `graphtraj/execution/agent_driver.py` | `name=f"agents-{run.agent}", daemon=False` |
| 452 | `graftling/claude/driver.py` | `name=f'claude-{run.agent}', daemon=False` |
| 454 | `graphtraj/execution/budget_idle_timer.py` | `DELIVERY_SECONDS = 300.0` |
| 455 | `graftling/control.py` | `"configuration": applied.get("configuration")` |
| 455 | `graphtraj/execution/agent_driver.py` | `"applied":         {"configuration": name` |
| 456 | `graphtraj/execution/runner_control.py` | `_reconcile_exited_owner(alias, session_directory, mapping)` |

## Steps

Each step prints who runs it, its dialog (at most one), how to judge success and the next
command with real values. 00 detects the Main Session id and saves it to
`~/graphtraj-adoption-458/main.session`.

| Step | Who | Command | Dialog | Success |
|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | zsh; `answer:` with `claude-opus-5-5`, `is_error False`; 0.1.0/0.5.0; `pip check rc=0`; `markers expected absent: PASS`; member list (457 may run); advisor role lines; classified guard (timers NON-BLOCKING); Task 458 `stopped: false`; no backup yet; `MAIN=<id>` |
| B | Main | `zsh $S B` | none | two wheels with sha256; `leaked: 0` |
| V | Main | `zsh $S V` | none | `SAME` ×3 plugin files; `source diff: empty`; `plugin unchanged: no plugin/hooks trust dialog is expected`; `markers expected present: PASS` and `absent: PASS`; no STOP; ✘ candidate ≤ baseline; `read_session … failures=0` |
| S | Main (queued: refuses while another run_test_shards runs) | `zsh $S S` (returns at once) | none | `Worktree HEAD … equal 4e3aafce… and clean`; `click 8.5.0`; `graphtraj.__file__` under this Worktree; poll `tail -n 25 …/raw/S-suite.txt` until `== DONE`; no `NEW` failure; every failure and both 456 baseline ids have an `… alone: <id> (…in the suite)` line |
| S2 | Main, after `== DONE` | `zsh $S S2` | none | `leftover processes of the suite (never signalled): 0` (else the list goes to Main) |
| Vc | Main | `zsh $S Vc` | none | `graphtraj-claude-host loaded: YES`; `PASS mcp__agents__tasks`, `PASS mcp__agents__agents` |
| Vu | **USER**, only if Vc says `loaded: NO` | `cd ~/graphtraj-adoption-458/vproject && claude`, then 'Yes, proceed', then `/exit` | folder trust | Main reruns Vc |
| — | **USER** | `/exit` in Claude Main | none | |
| I | **USER** (Main exited) | `zsh $S I` (Enter to confirm) | none | waits while BLOCKING processes (e.g. 457's) run, never kills; `-rw-------` ×3; `Successfully installed`; `PASS n FAIL 0`; `markers expected present: PASS (8/8)`; `SAME-AS-VALIDATED`; `plugin bytes as before the install: no trust dialog expected`; install-window BLOCKING list (information). On failure it prints R |
| — | **USER** | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | none expected (plugin bytes unchanged); any dialog: decline and tell Main | |
| M | Main | `zsh $S M`, then paste its prompts | none | criterion 4: notices display normally, none seen before the install appears again (457 ends during the exit may arrive once) |
| Mps | Main | `zsh $S Mps` | none | host uses `.venv-runtime`; `parent is claude --continue or --resume <id>: yes`; `outcome=ok` |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` |
| N | Main | `zsh $S N`, paste the swarm prompt; save the swarm result to `raw/N.txt`, the member's completion notice to `raw/N-main-notice.txt`, its reply to `raw/N-reply.txt` | none | an `opus_coding_team.advisor` member of Task 458 creates `n458` (configuration `opus_coding_team.advisor`), waits, sends once, waits, quotes status, reports source-graphtraj inputs, retires the child; no submit_result/submit_report |
| Nr | Main | `zsh $S Nr` | none | CHECK lines all PASS (see below); then the printed session_read, task_sessions and **retire-by-agent** prompts |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`; `markers expected present: PASS`; `raw files containing an exported key value: 0`; S `== DONE`; S2 leftover line |
| R | **USER** (Main exited), only on failure | `zsh ~/graphtraj-adoption-458/backup/tools/steps.zsh R` | none | waits like I; venv and plugin `SAME differences=0`; entries OK; pip check; then `claude --continue` |

Nr's CHECK lines (criterion 3):

- **455:**
  - `CHECK 455 stored record: configuration and model not null` (`control/agents/<child>.json` `selection`);
  - `CHECK 455 create/status result quoted by the member …` (from `raw/N-reply.txt`).
- **452:**
  - `CHECK 452 child execution <id> ended completed, not owner-exited` ×2;
  - `CHECK 452 member execution ended and recorded` (`sessions/<alias>/execution.yml`);
  - `CHECK 452 member reported its end to Main`;
  - `CHECK 452 no runner_worker of the member alive after its end` (read-only `ps`; if one is still there, rerun Nr a minute later and never kill it).
- **449/451:**
  - `CHECK execution <id> notification delivered` ×2;
  - `CHECK 449/451 one parent input for execution <id>` ×2. This counts archive events of type `user/message` naming the execution with source graphtraj. Anything else is `CHECK BY HAND`: Main pastes the printed session_read prompt and counts by event type, as 453 did.
- `CHECK swarm result has agent`.

The user does only these:

- Vu, only if needed;
- `/exit` Main;
- run I, which may wait for Task 457 members to end (do not kill them);
- `claude --continue`;
- R, only on failure.

If I is abandoned with Ctrl-C after the backup (during the second wait), production is
unchanged, but `backup/` exists without `INSTALL-STARTED`. Main renames it aside before I is
run again.

## What was rehearsed

`rehearse.zsh` ran in the sandbox on a fake production in `$TMPDIR`. The fake production had:

- old wheels from cfd5e432;
- click and yaml from Conda, and an import-only websockets stub;
- `claude` and `ps` stubs. The ps stub lists Main's host (whose parent is `claude --continue`), a budget timer, and a Task 457 member Worker that goes away after about 3 s.

Result: **ALL PASS (38 checks)**. Output: `rehearsal-output.txt`. These passed:

- 3(a) timer probe: the lazy import works after the install, and only `budget_idle_timer` was old in memory.
- 00: Main found through `--continue`; timer NON-BLOCKING; the 418 variable reported; markers absent.
- B.
- V: plugin SAME ×3 and the no-dialog prediction; source diff empty; markers present in the candidate and absent in production; no entry-file writes.
- S: refusal while another run_test_shards runs; Worktree equality with 4e3aafce.
- S2 on a synthetic finished suite: 2 leftovers counted (run marker, suite venv); an older basetemp ignored.
- I: waited with the Task 457 line (no kill, Ctrl-C safe); the Worker shown with its Task; the timer never BLOCKING. Then `-rw-------` ×3, `PASS n FAIL 0`, markers present 8/8, plugin bytes as before, `claude --continue` printed.
- R from the backup's tools; markers absent again after R.
- Mps with a `claude --continue` parent.
- Nr on synthetic records, all CHECK lines PASS. A negative case (null configuration, an owner-exited end, a live member Worker) gives FAIL lines.
- The M and N prints: task 458, preset role, no submit_result or submit_report, source-graphtraj inputs.

Not rehearsed:

- real `claude -p` (00, Vc) and `claude plugin validate`;
- the full suite (S beyond its refusal) and S2 against real processes;
- real `ps` and `ps -E` against production;
- the real N dispatch;
- the waiting loop's Ctrl-C path.
