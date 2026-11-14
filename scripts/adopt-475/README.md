# 475 production adoption: dev 4ca57419 (465, 469) and the production check of a Bash tool that really starts

`steps.zsh` installs the wheels built from `git archive 4ca57419137a7593f9275da210cd4c9ed54a8b99` (dev bf6cf300 plus
464's scripts; `git diff --quiet bf6cf300 4ca57419 -- src tests pyproject.toml` holds) into production
`.venv-runtime`. Production holds 464's 44729d5b now. Steps and protections are 464's (`scripts/adopt-464/`):
isolated real-Claude rehearsal (Vc), file-by-file equality (`proddiff.py`), backup with rollback (R), and a guard
that waits, never kills, and is rerun right before `pip install`. Versions do not change (graphtraj 0.1.0,
graftling 0.5.0); install claims come from `proddiff.py` and `markers.py`.

- Script: `S=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/475-production-adoption-465-469/scripts/adopt-475/steps.zsh`
- Raw output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/475-production-adoption-465-469/adoption/raw-4ca57419/`
- Base (AGENTS.md rule, user 2026-11-14): `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/475/`
  (`backup/`, `vproject/`, `vvenv-4ca57419/`, `svenv-4ca57419/`, `sprobe-4ca57419/`, `scratch/`, `main.session`).
  `~/graphtraj-adoption-*` is never used. 00 lists `~/graphtraj-adoption-464/backup` (and its `COMPLETE` marker)
  and never modifies it; it is kept until 475 is accepted.
- Only `rehearse.zsh` sets `ADOPT475_*`.

## Changes from adopt-464

1. **Target.** `TARGET=4ca57419…`, `OLD=44729d5b…` (production now), `TASK=475-production-adoption-465-469`,
   child `n475`, every output under `raw-4ca57419/` and `*-4ca57419` names.
2. **Isolated project under the Harness.** `tmp/475/vproject` has its own git and its own `.graphtraj` (00 runs
   `git init` and `graphtraj setup` there with production graphtraj; Vc regenerates its entries from the candidate
   venv). 00 and Vc run 465's isolation check (graphtraj root = vproject, git top level = vproject, no
   `CLAUDE.md`/`CLAUDE.local.md` at or above it; the Harness `AGENTS.md` is listed, Claude Code does not load it)
   and print `isolation: OK`; Vc refuses without it. It is a new path, so **Vu (USER: trust dialog once, 'Yes,
   proceed', `/exit`) is expected before Vc.**
3. **Claude version.** Every real-host step prints `claude: <path> -> <resolved> | version: …` of the default
   `claude` (2.1.323 now). `~/.local/bin/claude` is never repointed; no 2.1.325 step.
4. **Markers** (`markers.py`, 15, from the diff 44729d5b..4ca57419; `add` = line added, `removed` = line removed).
   Checked on `git archive` trees: `present: PASS (15/15)` for 4ca57419, `absent: PASS (15/15)` for 44729d5b.

   | Task | File | Line | Kind |
   |---|---|---|---|
   | 465 | `graphtraj/runtimes/claude/execution.py` | `from graphtraj.runtimes.codex.access import project_history_files` | removed |
   | 465 | same | `explicit = [Path(path).resolve() for path in request['resources']]` | add |
   | 465 | same | `if not any(path.is_relative_to(protected) for path in explicit):` | add |
   | 465 | `graphtraj/runtimes/codex/access.py` | `def project_development_reads(root: Path, *, history: bool = True) -> dict[str, str]:` | add |
   | 465 | same | `filesystem.update(project_development_reads(root, history=False))` | add |
   | 465 | `graphtraj/runtimes/codex/codex_adapter.py` | `filesystem.update(private_filesystem(runtime_store, self.runtime_home, history=False))` | add |
   | 469 | `graphtraj/graph/task_graph.py` | `def _load_task_state(tasks: Path, task_id: str) -> …` | add |
   | 469 | same | `class UnknownTask(KeyError, ValueError):` | add |
   | 469 | same | `def _create_task_directory(` | add |
   | 469 | `graphtraj/execution/runner_launch.py` | `class _RegisteredTaskNames:` | add |
   | 469 | same | `from graphtraj.graph.task_graph import read_graph` | removed |
   | 469 | `graphtraj/execution/runner_worker.py` | `task_directory, task = _load_task_state(project.state_directory / "tasks", mapping["task_id"])` | add |
   | 469 | `graphtraj/execution/runner_control.py` | `task_directory, task = _load_task_state(configuration.state / "tasks", mapping["task_id"])` | add |
   | 469 | `graphtraj/execution/runner_status.py` | `from graphtraj.graph.task_graph import UnknownTask, _load_task_state` | add |
   | 469 | `graphtraj/execution/runner_results.py` | `from graphtraj.graph.task_graph import _load_task_state` | add |

   I keeps 464's two import lines and adds
   `465 Claude member settings call project_history_files: False | Codex development reads history param: True` and
   `469 UnknownTask _load_task_state _RegisteredTaskNames`.
5. **Process kinds (44729d5b..4ca57419): no new process kind.** The diff changes `approved_recovery`,
   `runner_control`, `runner_launch`, `runner_results`, `runner_retirement`, `runner_status`, `runner_worker`,
   `delivery_state`, `task_graph`, `team_replacement`, `claude/execution`, `codex/access`, `codex_adapter`; it adds no
   `Popen`/`subprocess`/`spawn`/`fork`/`exec` line (`git diff … -- src | grep -cE '^\+.*(Popen|subprocess\.|spawn|os\.fork|os\.exec)'` = 0).
   469 replaces whole-graph reads with one-Task reads inside existing calls; 465 changes generated settings only.
   The guard's kinds table of 464 stands (timers NON-BLOCKING; Worker, swarm batch, hosts, anything under `$RT`
   BLOCKING; 450 marked processes information only).
   **Mixed version** (`timer_probe.py` old=44729d5b new=4ca57419, in the rehearsal): a timer loads 10 modules at
   start, none changed; at the threshold it loads the changed `runner_control`, `runner_status`, `runner_worker`,
   `task_graph` new from disk (`changed modules that were OLD in memory before the install: none`;
   `469 runner_control from new file (uses _load_task_state): True`; `469 _load_task_state after the install: OK
   UnknownTask`). Timers stay NON-BLOCKING.
6. **Plugin/hooks.** `git diff --stat 44729d5b 4ca57419 -- '*.mjs' '*hooks*' '*plugin*' src/graftling/claude-plugin`
   lists only `scripts/adopt-464/adopt_plugin.py` (not installed). Prediction: **no trust dialog at resume.** V and I
   keep their byte checks.
7. **Guard I.** Unchanged behaviour (waits, never kills, Ctrl-C safe). The waiting line names the Tasks whose
   members may run now: every Task in the state whose `task.yml` status is not `integrated`, except 475 (today
   461, 462, 466–468, 470–474 and others), in Chinese and English.
8. **S.** Equality guard with 4ca57419; refuses while another `run_test_shards` runs; production click/yaml/websockets
   copied; suite venv `tmp/475/svenv-4ca57419`. Compared with 464 at 44729d5b (0 failed, 4041 passed, 71 skipped),
   465 (0 failed, 4045 passed), 469 (0 failed, 4045 passed). Every failure prints `NEW <id> [label]`, then
   `== new failures: n (of which ATTRIBUTED: m)`, then each alone with `-rA`; the 454 leftover line; S2 as before.
   ATTRIBUTED comes from 465/469 accepted records only: both had 0 failures, so the list is empty (464's 459-BASELINE
   and 460–463 attributions are not carried over).
9. **N / Nw / Nr.** N: an `opus_coding_team.advisor` member of Task 475 (a) creates `n475` (configuration
   `opus_coding_team.advisor`, message `Use the Bash tool once to run exactly: echo n475-tool && sleep 3 . Then reply
   DONE-475.`), waits, sends once, waits, quotes create/status; (b) calls tasks `session_read` on the child's Session
   and quotes only `SESSION-READ-475 session=<id> events=<n>`; (c) runs its own Bash `echo member-bash-ok`; retires the
   child; no submit_result/submit_report. Nw as 464. Nr keeps 464's CHECK lines and adds (`nr475.py`):
   - `CHECK 459 child Bash started (record lists the command)` — an Nw snapshot or the record lists `n475-tool` or `sleep 3`;
   - `CHECK 465 member claude-settings has no per-session-file grants` — `<runner>/sessions/<alias>/claude-settings.yml`
     (written by `graftling/claude/execution.py`; after retirement under `teams/*/traces/<alias>/runner/`); prints only
     byte size and counts (allow, deny, additionalDirectories, allowRead, denyRead, allowWrite, denyWrite) and the
     number of entries naming a `*.jsonl` under `~/.claude/projects` or `~/.codex/sessions`; never a value;
   - `CHECK 465 member session_read returned the child's Session (id match)` — the quoted session equals the child record's;
   - `CHECK member Bash started` — a `tool/result` in the member's archive contains `member-bash-ok`.

   **User's rule: an unobserved required check is NOT met.** When a Bash did not start, Nr prints
   `BLOCKED: <check> not observed - '<error text>' (emitted in <file>)` (child/member archive, native transcript if
   readable, or quoted in `N-reply.txt`) and the CHECK is FAIL. 464's vacuous case is closed:
   `CHECK 459 no recorded tool process alive after the end` is FAIL (`BLOCKED …`) when the command was never
   recorded, and `descendants record lists the Bash tool command` is FAIL (not NOT OBSERVED) without Nw. Nr exits
   non-zero on any FAIL.
10. **M, Mps, inbox, done** as 464. M: ends of other Tasks' members during the exit may arrive once and must not
    repeat (names the active Tasks). done counts raw files containing an exported key value.
11. **Main's rules.** Main runs each step as `zsh $S <step>`; no foreground `sleep`; no `rm` inside `zsh -c`; every
    command ends within 10 minutes or starts in the background (S, Nw); no step signals a process it did not start.
    Every step prints who runs it, the one dialog it may show (or none) and the choice, how to judge success, and the
    next command with real values.

## Steps

| Step | Who | Command | Dialog | Success |
|---|---|---|---|---|
| 00 | Main | `zsh $S 00` | none | `claude: … version: 2.1.323`; `answer:` with `claude-opus-5-5`, `is_error False`; 0.1.0/0.5.0; `pip check rc=0`; `markers expected absent: PASS (15/15)`; `isolation: OK`; `stopped: false`; Tasks that may run now; member list; advisor role lines; 464 backup listed (untouched); `tmp/475/backup` absent; `MAIN=<id>` |
| B | Main | `zsh $S B` | none | two wheels in `adoption/wheels-4ca57419/` with sha256; `leaked: 0` |
| V | Main | `zsh $S V` | none | `SAME` ×3; `source diff: empty`; `plugin unchanged: no plugin/hooks trust dialog is expected`; markers present/absent 15/15; ✘ candidate ≤ baseline; `read_session … failures=0`; no STOP |
| S | Main (queued) | `zsh $S S` (returns at once) | none | `equal 4ca57419… and clean`; `click 8.5.0`; `graphtraj.__file__` under this Worktree; poll `tail -n 25 …/raw-4ca57419/S-suite.txt` until `== DONE`; `== new failures: 0` |
| Vu | **USER** (expected, new path) | `cd …/tmp/475/vproject && claude`, 'Yes, proceed', `/exit` | folder trust (one) | Main runs Vc |
| Vc | Main | `zsh $S Vc` | none | `isolation: OK`; `graphtraj-claude-host loaded: YES`; `PASS mcp__agents__tasks`, `PASS mcp__agents__agents` (`loaded: NO` → Vu, then Vc again) |
| S2 | Main, after `== DONE` | `zsh $S S2` | none | `leftover processes of the suite (never signalled): 0` |
| — | **USER** | `/exit` in Claude Main | none | |
| I | **USER** (Main exited) | `zsh $S I` (Enter) | none | waits while BLOCKING processes run (names active Tasks; never kills); `-rw-------` ×3; `Successfully installed`; `PASS n FAIL 0`; `markers expected present: PASS (15/15)`; 464 import lines plus the 465 and 469 lines; `SAME-AS-VALIDATED`; `plugin bytes as before the install: no trust dialog expected` |
| — | **USER** | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery && claude --continue` | none expected; any: decline, tell Main | |
| M | Main | `zsh $S M`, paste its prompts | none | criterion 4: notices display normally and do not repeat |
| Mps | Main | `zsh $S Mps` | none | host uses `.venv-runtime`; parent `claude --continue`/`--resume <id>`; `outcome=ok` |
| inbox | Main | `zsh $S inbox` | none | `duplicate ids: 0` |
| Nw | Main, right before N | `zsh $S Nw` (returns at once) | none | `tail -n 3 …/raw-4ca57419/Nw.txt` shows `start: watching` |
| N | Main | `zsh $S N`, paste the swarm prompt; save swarm result `N.txt`, member notice `N-main-notice.txt`, reply `N-reply.txt` | none (child's Bash approval, if any, goes to the member) | member does (a)–(c), retires the child |
| Nr | Main, after the member's end | `zsh $S Nr` | none | every CHECK PASS, no `BLOCKED` line (else FAIL, Main registers it); then the printed session_read, task_sessions and retire-by-agent prompts |
| done | Main | `zsh $S done` | none | `PASS n FAIL 0`; markers present; `raw files containing an exported key value: 0`; S `== DONE`; S2 line; Nw `== END` |
| R | **USER** (Main exited), only on failure | `zsh …/tmp/475/backup/tools/steps.zsh R` | none | venv and plugin `SAME differences=0`; entries OK; pip check; then `claude --continue` |

The user does only: Vu (trust once), `/exit` Main, I, `claude --continue`, and R only on failure.

## Rehearsal

`zsh scripts/adopt-475/rehearse.zsh` in `$TMPDIR` (fake Harness with old 44729d5b wheels, Conda click/yaml, a
websockets import stub, `claude` and `ps` stubs; test base `$FH/tmp/475`; a fake `~/graphtraj-adoption-464/backup`
outside it). **Result: ALL PASS (86 checks)**, output in `rehearsal-output.txt`. Covered: timer probe; markers on
archive trees; 00 (Main via `--continue`, timer NON-BLOCKING, 418 variable, markers absent, claude version line,
`isolation: OK`, `stopped: false`, 464 backup listed, active Tasks 466/470 named, 465 not); B; V; Vu text; Vc's
isolation with the candidate venv and its Vu fallback; S refusal and equality; S label/count lines (synthetic ids);
S2; I (waiting line in both languages naming 466/470, Worker of Task 466 BLOCKING, timer never, proddiff, markers,
464/465/469 import lines, backup under tmp/475 with tools); R; Mps; Nw; Nr positive (all CHECK PASS, no BLOCKED) and
two negatives — A (alive recorded entry, 455 null, owner-exited, live Worker) and B (464's production case: E2BIG in
the child and member archives, settings granting two history files, no session_read line → `BLOCKED … E2BIG …
(emitted in <file>)` and FAIL, never PASS, values never printed); M; N; done's key-value count (0, then 1 with a
planted value); 464 backup unchanged.

Not rehearsed: real `claude -p` (00, Vc) and `claude plugin validate`; the real Vu dialog; the full suite and S2
against real processes; real `ps`/`ps -E` and libproc visibility from Main's shell; the real N dispatch, the child's
possible Bash approval, Nw against a real sampler, real archive event shapes for `tool/result` errors (Nr also
searches the native transcript and the member's quoted error text); `graphtraj setup` of vproject with production
graphtraj inside the real Harness (465's verify did the same under `tmp/465`); the Ctrl-C path of the wait. `ps` is
not permitted in this sandbox, so the absence of leftover rehearsal processes was judged from the rehearsal's own
checks (Nw `== END`, the live `sleep` killed and waited).
