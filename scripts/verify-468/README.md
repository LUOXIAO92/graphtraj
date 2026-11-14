# 468 real-host check: the Runner Worker of an actively working Claude member, before and after

Main runs every step. 00u is the user's, only if 01 or 02 reports a folder-trust or login refusal. Each Main command
returns within 10 minutes or starts its work in the background. Every step prints `claude --version`. No step
signals a process it did not start, no step runs `rm` inside `zsh -c`, and no step leaves a process running except
03's suite, which stops itself after 25 minutes. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/468/verify/out/` (`…/out` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/468-runner-worker-busy-cpu/scripts/verify-468/steps.zsh`.
Paste only `S NN` (the plain command each step prints); zsh-only syntax stays inside the script.

Base: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/468/verify/` (`src-before`, `venv-before`,
`project-before`, the same three for `after`, `suite-venv`, `out`). Nothing is created in the user's home.
BEFORE is `cfd7f688` (dev base of 468); AFTER is the Worktree HEAD when 00 runs (or `VERIFY468_COMMIT`).

| Step | Who | Command | Success | Native dialog |
|---|---|---|---|---|
| 00 | Main | `S 00` | `expected 2.1.325: yes`, `launched via zsh: yes`, `468 fix loaded: NO` (BEFORE) and `YES` (AFTER), `deps: click 8.5.0` twice, `roles OK` and `probe Task ready: YES` twice, `isolation: OK` twice, `init: … model claude-opus-5-5 \| apiKeySource <name>`, `cc-plugin-agents-md loaded: NO`, `Harness instruction files loaded: none`, `result: MODEL OK \| MEMORY: NONE`. Prints the 01 command. | none |
| 00u | USER, only if 01 or 02 reports a trust or login refusal | `cd …/tmp/468/verify/project-before && claude` (or `project-after`), 'Yes, proceed', `/exit` | Main reruns the refused step. | folder trust for the new path: choose 'Yes, proceed' |
| 01 | Main | `S 01 2>&1 \| tee …/out/01.txt` | < 10 min. Raw `ps` lines of the BEFORE Worker every ~10 s, `per-interval CPU-s per wall-s: […]`, `Worker CPU while the member worked: … = <r> CPU-s per wall-s`, `== BEFORE: <r>`. Prints the 02 command. | none (00u if refused) |
| 02 | Main | `S 02 2>&1 \| tee …/out/02.txt` | As 01 for AFTER, then `BEFORE:` / `AFTER :` lines and `== verdict: PASS` (AFTER < 0.25 CPU-s per wall-s and below BEFORE). | none (00u if refused) |
| 03 | Main | `S 03` | Full suite at HEAD in the background, six shards, stops itself after 25 min. `tail -n 25 …/out/03-suite.txt`; done at `== totals:`. | none |

If 01 or 02 says the Task already has a member (a rerun), rerun 00 first: it rebuilds both projects.

## Acceptance and the observable that proves it

| Criterion | Observable |
|---|---|
| a real Claude Task member, Runner-dispatched, `claude-opus-5-5`, `permission_mode: auto` | 00 `roles OK`; 01/02 `member Claude Code …` and `agent-runner returned: alias=…` |
| the member works actively for several minutes | the instruction: 60 steps, each a sentence and one Bash `seq -f '468-NN-%g' 1 400` call (400 output lines, ~4.3 KB; ~265 KB in all), one at a time; 01/02 print the samples while `activity` is `running`, and `collection_progress: batches …` (archive collection batches during the run) |
| Worker CPU sampled with ps cumulative time deltas and pcpu, raw lines kept | each sample prints `ps -o pid,ppid,pcpu,time,etime,command -p <Worker pid>`; also in `…/out/before.ps.txt`, `…/out/after.ps.txt` |
| before/after CPU-s per wall-s and a verdict | 01 `== BEFORE: <r>`, 02 `== AFTER: <r>`, `== verdict: PASS/FAIL` |
| the members ran without the Harness instruction files | 00: the projects' own `.claude/settings.local.json` and committed `.claude/settings.json` (claudeMdExcludes for the Harness `CLAUDE.md`/`AGENTS.md`, `cc-plugin-agents-md@builtin: false`); the host's init record `cc-plugin-agents-md loaded: NO` and `Harness instruction files loaded: none` |
| no new failures | 03 `== totals:` compared with Main's last dev baseline |

## What each step does

### 00 preflight

For BEFORE and AFTER: `git archive` of the commit, an editable install into a scratch venv (`--system-site-packages`,
no network), click/yaml/websockets copied read-only from production `.venv-runtime`. `probe.py fix` prints where
`graftling.sessions.archive` and `graphtraj.execution.runner_worker` are imported from (must be that source) and
whether it has the 468 change. Then an isolated project per commit (own `git init`, own `.graphtraj` from
`graphtraj setup`), Claude settings as verify-462/466, one `team_leader` role (`claude`, `claude-opus-5-5`,
`permission_mode: auto`) and probe Task 1 set ready. One `claude -p` line (no tool, no MCP) in the AFTER project gives
the model, login source name and plugins from its init record.

### 01 / 02 the member and its Worker

`agent-runner --swarm-input` dispatches Task 1's member with the scripted instruction. It returns only when the
member's turn ends, so the probe starts it in the background (output in `…/out/<label>-facts.agent-runner.txt`) and
samples meanwhile. (The first run at 922d1083 sampled only after it returned, when the Worker had already exited:
`samples 0`.) The probe finds the member's Session directory under the project's `runner/sessions` and its Worker pid
in `heartbeat.yml` or `mapping.yml`, then every ~10 s prints one raw `ps` line for that pid, until the Worker exits or
the member's `activity` is no longer `running` (≤ 520 s). It then waits ≤ 30 s for agent-runner to return and never
signals it. The ratio is (last − first cumulative CPU time) / (wall time between them). The member's
`claude-diagnostics-<execution>.yml` `collection_progress` is printed at the end. Nothing is signalled; if the member
still runs at the limit, the samples so far are used and the step says so.

Rerun 00 before 01/02 after an earlier run: 01 and 02 refuse a project whose Task already has a member, and 00
rebuilds both projects. AFTER is the Worktree HEAD, whose product code equals 922d1083 (this commit changes only
`scripts/verify-468`).

### 03 full suite

As verify-466 step 03, against the Worktree HEAD, six shards, stopped at 25 minutes.

## Rehearsal without a model (sandbox)

`zsh -n steps.zsh`, `python -m py_compile probe.py`; `probe.py fix` against a dev venv of the Worktree (`YES`) and of
`cfd7f688` (`NO`); project setup + `prepare` + `isolation` in a scratch directory (`roles OK`, `probe Task ready: YES`,
`isolation: OK`); `seconds()` on `0:07.39`, `1:02:03`, `2-01:00:00`, `12:00.50`; `compare` on synthetic results (PASS
for 0.06 vs 0.91, FAIL for 0.4). `ps` and real Claude are not available in the Engineer sandbox, so `run` was not
rehearsed.
