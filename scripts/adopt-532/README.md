# Task 532 — production adoption of GraphTraj a7b20447 (531's CPU fixes); graftling stays 0.6.2

`steps.zsh` installs a GraphTraj wheel built from `git archive a7b20447` into production `<Harness>/.venv-runtime`.
Production now holds graphtraj 8267f9e5 (525) and graftling 0.6.2 (528, v0.6.2 = 4a002129).

- **graphtraj**: 8267f9e5 → a7b20447. The product diff in `src`, `plugins` and `pyproject.toml` is exactly three files:
  - `execution/runner_heartbeat.py` and `execution/runner_status.py` (531, 805ec01b): when the caller lookup confirms
    the caller's identity, it skips Sessions whose owner lock is not held;
  - `runtimes/claude/adapter.py` (531, 496cec58): a Claude child's preflight reads the history only when a grant
    overlaps a protected path.

  B checks this diff. V checks that the wheel differs from production in exactly these files. I installs only this
  wheel, with `pip install --no-deps --no-index --force-reinstall`; the version stays 0.1.0.
- **graftling**: never reinstalled or changed. B builds a graftling wheel from `git -C <Harness>/graftling archive
  v0.6.2`, but only for the scratch venv and V's proof. That wheel is never installed. The proof is in three places:
  - V: production's graftling equals that wheel file by file, and the wheel equals the archive;
  - I and done: the installed graftling (package and dist-info) equals the backup's copy;
  - R: the same check before and after the restore.

  The new graphtraj requires `graftling<0.7,>=0.6.0`, which production's 0.6.2 satisfies (checked by B).

The scripts are `scripts/adopt-528/` copied and adapted; adopt-528 and adopt-525 are unchanged. Every
503/515/525/528 protection is kept:

- the isolated real-host project `/private/tmp/vproject-532`;
- proddiff file by file, and markers checked both ways;
- the backup `<Harness>/tmp/532/backup`, and rollback R from the backup's own tool copy;
- the guard that waits, never signals, and runs again right before pip;
- the Claude Code version recorded at 00;
- no exported key value in raw output;
- timers listed and never signalled;
- `.mcp.json` server keys only `graphtraj`;
- plugin bytes compared against production.

Run each step as `zsh <Worktree>/scripts/adopt-532/steps.zsh <step>`. Raw output goes to
`.graphtraj/core/state/tasks/532-production-adoption-graphtraj-531/adoption/raw-a7b20447/`. Each step prints who runs
it, the single native dialog it may show (or `none`), how to judge it, and the next command with real paths.

## Full suite: reused from 531 (Leader decision), no pytest step

- `git diff 83e84fba a7b20447 -- src tests plugins pyproject.toml` is empty.
- 531's G at 83e84fba with the graftling wheel from `git archive 4a002129` (= production 0.6.2) ended with
  3608 passed, 48 skipped, exit=0, and no FAILED or ERROR line. The record is
  `531-child-create-runner-record-walk/realhost/G-83e84fba-20261120T204653/`.

**GR** is read only. It runs:

1. the product guard: the Worktree's `src`, `tests`, `plugins` and `pyproject.toml` equal a7b20447 (only `scripts/`
   may differ), nothing in them is uncommitted, and the 83e84fba..a7b20447 diff is empty;
2. `greuse532.py` on 531's G record: `run.txt` must name candidate 83e84fba and graftling 4a002129; `suite.txt` gives
   the totals and the exit code; FAILED and ERROR lines are counted in `suite.txt`, `shards/*.log` and
   `shards/failures.txt`.

GR prints `CHECK 532 reused G (531 83e84fba) no failure: PASS|FAIL`. A new GR truncates `GR.txt` and keeps the old one
as `GR-<time>.txt`, so an earlier PASS never survives a later FAIL. **I** refuses without that PASS line in `GR.txt` or
when the guard STOPs. There is no pytest step, so the TMPDIR rehearsal rule does not apply.

## Restart of Main: needed

Main's host `graphtraj.runtimes.claude.host serve` loads the changed modules once:

- `runtimes/claude/host.py:115` and `interfaces/agents.py:825` import `graphtraj.execution.runner_status`;
- `runner_status.py:18` imports `runner_heartbeat`;
- `runtimes/runtime_adapter.py:309` imports `graphtraj.runtimes.claude.adapter`.

A running host keeps 8267f9e5's code, and the 503 guard needs Main exited during I. So the USER does `/exit` before
I, runs I in Terminal, and then runs `cd <Harness> && claude --continue`. Member Workers started after I load the new
code.

## Step order

| Step | Who | Dialog (choice) | Time |
|---|---|---|---|
| 00 preflight (one `claude -p` answer: model + login; Claude Code version recorded) | Main | none | ~2 min |
| B graphtraj wheel (installed by I) + graftling v0.6.2 wheel (scratch/proof only) | Main | none | < 2 min |
| GR guard + reused 531 G (read only) | Main | none | < 10 s |
| V pre-install checks | Main | none (if the plugin is CHANGED: STOP, it would bring the plugin/hooks trust dialog) | ~2 min |
| Vu (only if Vc asks) | **USER** (Terminal) | folder trust for `/private/tmp/vproject-532` → **Yes, proceed**; then `/exit` | < 1 min |
| Vc isolated real-host probe | Main | none | ~2 min |
| Mpre | Main | none | < 1 min |
| `/exit` Main | **USER** | — | — |
| I backup + graphtraj install + `configuration --write` | **USER** (Terminal) | none | ~3 min + waiting for members (Ctrl-C safe) |
| `cd <Harness> && claude --continue` | **USER** | none expected | — |
| M (prompts), Mp, Mps, inbox | Main | none | < 3 min |
| Nw (background sampler), N (an advisor member creates `n532`), Nr, Nt | Main | none | ~5 min |
| done | Main | none | < 1 min |
| T (after the Leader accepts 532) | Main | none | < 30 s |
| R rollback (only if needed) | **USER** | none | ~3 min |

## Checks by step

- **00**: production versions and both `direct_url.json` files (graphtraj from 525's `wheels-8267f9e5`, graftling from
  528's `wheels-8267f9e5`). It also checks `markers expected absent: PASS (5/5)`, `.mcp.json` graphtraj only,
  isolation, the answer check, and lists 528's backup without touching it.
- **B**:
  - product guard;
  - the product diff is exactly the three files;
  - v0.6.2 is an annotated tag peeling to 4a002129;
  - `wheels-a7b20447/` holds only `graphtraj-0.1.0-…whl`, and `glwheel-0.6.2/` holds the scratch graftling wheel;
  - `Requires-Dist: graftling<0.7,>=0.6.0`;
  - `CHECK 532 graphtraj wheel equals git archive a7b20447` (`pkgdiff532.py`);
  - both 531 fixes are in the wheel;
  - no `graftling/` in the graphtraj wheel, and leaked 0.
- **V**:
  - plugin bytes SAME (CHECK);
  - `CHECK 532 graftling wheel equals git archive v0.6.2` and `CHECK 532 graftling unchanged (production = v0.6.2 0.6.2)`;
  - `CHECK 532 graphtraj wheel a7b20447 differs from production 8267f9e5 in exactly the 531 files` (an expected file
    that does not differ is a FAIL too);
  - markers 5/5 present in the candidate and absent in production;
  - layout, node resolution, plugin validate, entry prediction and readcheck, as in 528.
- **I**:
  - only the graphtraj wheel is installed;
  - proddiff of the installed graphtraj against the wheel: PASS n FAIL 0;
  - `CHECK 532 graftling unchanged (installed vs backup)`;
  - both fixes by name in the installed code;
  - `CHECK 532 graphtraj direct_url names the wheels-a7b20447 wheel`, then
    `built from: graphtraj git archive a7b20447…`;
  - markers present 5/5, layout and node resolution;
  - `configuration --write`, then SAME-AS-VALIDATED, plugin bytes as before, `.mcp.json` CHECK, and the three entry
    files unchanged.
- **M, Mp, Mps, inbox**: as in 528. They check that `mcp__graphtraj__*` are present, each notice arrives once,
  `duplicate ids: 0`, and the host started after the install.
- **Nw, N, Nr, Nt**:
  - N dispatches one `opus_coding_team.advisor` member, which creates the claude child `n532`, waits for it, reads
    its status and retires it.
  - Nr prints `CHECK 532 Main got exactly one completed notice of the member` and the 455, 452 and 477 checks.
  - Nr also REPORTs the Worker CPU 30 s before and after child creation. The comparison line is
    `REPORT 532 Worker CPU comparison`: before 531's fix, production 528 measured 0.559 / 0.107, and 531 measured
    0.488 → 0.116 on a production-size copy. It is a report and does not block.
  - `REPORT 532 526 .gitignore …` is information only.
- **R**: restores the whole venv, the plugin and the entry files from the backup. It prints
  `CHECK 532 graftling identical to the backup before R` and `… unchanged (after R vs backup)`. It also lists how the
  graphtraj package differed (the three files).

Dropped from 528:

- G, Gt and `gr528.py` (the suite is reused);
- `graftcode.py` and the graftling patch (graftling does not change);
- `gtdiff528.py`, replaced by `pkgdiff532.py`;
- the 526/527 markers, replaced by 531's.

`cpu468.py` keeps its `REPORT 525 468` label.

## Rehearsal

`zsh scripts/adopt-532/rehearse.zsh` writes `rehearsal-output.txt`.

- It starts from an empty base under `$TMPDIR/adopt532-rehearsal`.
- The fake production is graphtraj 8267f9e5 plus graftling from the real v0.6.2.
- `claude` and `ps` are stubs.
- B reads the real annotated v0.6.2, and GR reads 531's real G record; both are read only.

The negative cases are:

- B with a wrong target commit (guard STOP);
- a graftling tag that does not peel to 4a002129;
- a Worktree `src` change, uncommitted and committed, on a scratch clone (guard STOP); a scripts-only commit passes;
- reused G with a FAILED line, with another candidate, with failed totals and exit=1, or with another graftling commit
  (CHECK FAIL); after a failing GR the old PASS no longer counts;
- a graphtraj wheel file that differs from the archive;
- a production graftling that differs from v0.6.2;
- an installed graftling that differs from the backup;
- an expected 531 file that does not differ;
- markers checked both ways;
- I refusing without GR PASS, and I refusing on a guard STOP with GR PASS (no backup made in either case).
