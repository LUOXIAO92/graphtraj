# verify-546: send right after create is refused with runtime-input-closed

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-546/steps.zsh <step>`. No step needs user action.
Main kind: Claude Code (headless `claude -p`, verified Main through the product's claude host configuration).
Child Runtime: claude. BEFORE = GraphTraj f754d3a9 + graftling 6794ce0; AFTER = this Worktree HEAD + graftling
branch `agent/546-send-after-create-runtime-input-closed` in `.scratch/graftling` (git dir `.scratch/graftling-git`).

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Version line; `BEFORE:`/`AFTER:` commits; two `venv:` lines and `claude host configuration written` per phase; `CHECK 546 READY-546-CLAUDE: PASS` with `init model` and `auth source`. |
| `B` | none | Each agents call with called/returned times and its error code/delivery; the child's record with every input receipt and `N s before this execution's recorded end`; `VERDICT 546: REPRODUCED` when a send got `runtime-input-closed` (receipt `delivery=rejected`) while the execution had not yet recorded its end. Repeat B (max 5) if `NOT-HIT`. |
| `A` | none | Same output on the candidate. Criterion: no send returns `runtime-input-closed`; a send landing in the window shows `delivery: next-execution` with `closed_execution` and the new `execution`, and the verdict `CLOSING WINDOW HIT, NOT REFUSED`. |
| `T` / `TS` | none | T starts the graftling suite (candidate tree) and the GraphTraj suite (this Worktree, candidate graftling) in the background with `TMPDIR` outside the Harness (printed). TS prints `exit=`, the summary line and every FAILED line. 516-listed failures do not block. |
| `C` | none | Copies `before/`, `after/` runs, `ready/` and `t/` to `<Worktree>/.state/realhost/`; counts the VERDICT lines. |

Trigger condition: Claude, Codex and DSH set "not accepting input" at the turn end and report the end to agents only
after archiving/closing (Claude `execution.py` run(): `accepting = False` before `done`; the record stays `running`).
A send in that window was refused. The window is short (archive and close), so B may need several runs.

Rehearsal: `zsh scripts/verify-546/rehearse.zsh <empty dir>`; output in `rehearsal/output.txt`.
- **The stub replaced:** `claude` (READY answer and the whole Main model; the stub makes no agents call, so B prints
  `NOT-HIT`). The real create → send path through a model was not exercised by the rehearsal.
- **Real:** steps.zsh, both venv builds from exact commits, `graphtraj setup`, the claude host configuration, drv546.py
  ready/summary, T with `VERIFY546_TESTS=tests/test_agent_control.py` (a real graftling test file with its fixtures,
  through the same T entry), TS and C. The sandbox could not run `ps`, so T's "another run" guard printed an error
  and continued.
