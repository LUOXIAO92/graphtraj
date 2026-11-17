# Task 503 — production adoption of the split layout (graftling 0.5.2 + GraphTraj dev 6115c724)

`steps.zsh` installs graftling 0.5.2 (a wheel built from `git -C <Harness>/graftling archive v0.5.2`, never the
working tree; v0.5.2 peels to main f796a5d1) and graphtraj (a wheel from `git archive 6115c724`) into production
`<Harness>/.venv-runtime`. Production holds 499's 871aaaa9 (graftling 0.5.0, built from graphtraj's src/graftling).
It is `scripts/adopt-499/` copied and adapted; adopt-499 is unchanged. Every 499 protection is kept: the isolated
project `tmp/503/vproject` (`scripts/verify-common/claude_isolation.py`), proddiff file by file, markers both ways,
backup `tmp/503/backup` and rollback R from the backup's own copy of the tools, the guard that waits (never signals)
and runs again right before pip, the Claude Code version recorded at 00, no exported key value in raw output, timers
listed and never signalled. 499's backup `tmp/499/backup` and its COMPLETE marker are listed by 00, never modified.

Run: `zsh <absolute path>/scripts/adopt-503/steps.zsh <step>`. Raw output:
`.graphtraj/core/state/tasks/503-production-adoption-graftling-split/adoption/raw-6115c724/`. Base: `<Harness>/tmp/503/`.
Each step prints who runs it, its dialog, how to judge it and the next command with real values.

## Step order, who runs it, dialog, wait limit

| Step | Who | Dialog | Time / wait limit |
|---|---|---|---|
| 00 preflight | Main | none | ~2 min (one `claude -p`, 120 s cap) |
| B two wheels (two repositories) | Main | none | < 2 min |
| V pre-install checks | Main | none | ~2 min |
| Vu | **USER** (Terminal) | one: folder trust for `tmp/503/vproject` → **Yes, proceed**; then `/exit` | < 1 min |
| Vc | Main | none | ~2 min |
| Mpre | Main | none | < 1 min |
| `/exit` Main | **USER** | — | — |
| I backup + install | **USER** (Terminal) | none | ~3 min + waiting for other Tasks' members (no limit; Ctrl-C is safe, says what it leaves) |
| `cd <Harness> && claude --continue` | **USER** | none expected (plugin bytes unchanged) | — |
| M, Mps, inbox | Main | none | < 1 min each |
| Nw (background), N, Nt, Nr, N484 | Main | none | member + child 5-10 min; Nw ends itself ≤ 15/25 min |
| P (Pi child, DSH child of Main) | Main | none expected | 1-3 min per child |
| Pr | Main | none | < 1 min (read only) |
| S full suite (background) | Main | none | quiet wait ≤ 20 min, suite ~20-30 min |
| S2, done | Main | none | < 1 min |
| T (after the Leader accepts 503) | Main | none | < 30 s |
| R rollback (only on failure) | **USER** (Terminal, Main exited) | none | waits like I |

The user only does Vu, `/exit`, I, `claude --continue` (and R on failure).

**499 lessons applied.** S (full suite) runs only after Pr, or when Main states the host is idle
(`ADOPT503_S_IDLE=1`); it refuses while the install, N's member Worker, Nw, or P's children run, and P refuses while
S runs. N tells Main to save each notice with its header and body on one line.

## Criterion → observable

| Definition item | Observable (step: line) |
|---|---|
| 1 graftling 0.5.2 from the v0.5.2 wheel + graphtraj 6115c724 installed; one graftling | B: `v0.5.2 peels to f796a5d1…: yes`, `graftling wheel version: 0.5.2`, `graphtraj Requires-Dist: graftling<0.6,>=0.5.2`, `graphtraj wheel carries graftling/: 0`, `leaked: 0`. V: `graftling code vs production: SAME CODE` (only `VERSION` = `__init__.py` version line and package.json versions, `DOC` = markdown), markers 7/7 both ways, SAME ×3. I: `Successfully installed graftling-0.5.2 graphtraj-0.1.0`, `PASS n FAIL 0` (no LEFTOVER-DIST-INFO), `markers expected present: PASS (7/7)`, `395 layout graftling 0.5.2 | distributions 1 | …`, `503 layout: PASS` (onegraft.py), two `CHECK 503 node resolves … : PASS`. done: the same again. |
| 2 full suite, no new failures | S: `test venv graftling from the wheel: OK`, `== new failures: 0` (ATTRIBUTED keeps 499's list and adds Task 502's flakes, 499's run-1/2 survivors and 395's app-server timeout); baseline 395 0/3924/62, 499 run 2 3/4178/69. S2: leftover 0. |
| 3 new layout: Main host, MCP, members from the installed graftling | Mps: `host uses .venv-runtime: yes`, CHECK 486; I/done: onegraft (`no source link`, `imported here`, `graphtraj clean`); N/Nr: member and child run from production. |
| 3 Pi/DSH load the installed graftling | Pr: `503 pi: PASS` and `503 dsh: PASS` (child created, ended completed, tool call + result in the archive, reply `DONE-503-PI/DSH` with a field, no `cannot find the installed graftling distribution`, GraphTraj processes under `.venv-runtime`). `NOT OBSERVED (<reason>)` is reported, not a product failure. |
| 3 499's checks | Nr / Nt / N484 / T as in 499 (452, 455, 459, 465, 466, 477, 484, 486, 487, 490, 494, 495, 498). 468: `REPORT 468 (Task 501; not blocking)`. |
| 4 restart, notices once | M-a (Main's answer), inbox `duplicate ids: 0`, Nr `CHECK 494 Main got exactly one completed notice`. |

## New pieces (503)

- `markers.py`: 7 markers of 395 (graftling.mjs, Pi/DSH loading through it, the removed sibling imports, `__version__ = "0.5.2"`); `add`/`remove` kinds; a third argument names the directory holding graftling/ for git-archive trees.
- `graftcode.py`: every file the graftling wheel installs vs production's graftling; VERSION/DOC/CODE classes; CODE → STOP.
- `onegraft.py`: run with the venv's own python; one distribution, one package, wheel install, no source link, imported from the venv, graphtraj's RECORD without graftling/.
- `node_resolve` (steps.zsh): node loads the venv's `graphtraj/runtimes/graftling.mjs` in an empty environment (no GRAFTLING_PYTHON, no python3 on PATH) and must return `<site-packages>/graftling`.
- `pr503.py` + steps P/Pr: Pi child `p503` (configuration `pi_dsh_trial.team_leader`, connection pi/deepseek/deepseek-flash) and DSH child `d503` (`pi_dsh_trial.engineer`, dsh/deepseek-official/deepseek-flash). The create form `{"runtime", "configuration", "name", "instruction"}` follows 481's accepted Main prompt; if the tool rejects it, P tells Main to `describe create` and retry once.
- Helpers kept by name from 499 (nr499.py, notices499.py, busy499.py, ctl497.py, timers497.py, watch/nr 459/498) with the probe tokens renamed to 503 (n503, KW503-ORCHID, DONE-503, sk-probe503…). Nw/Nr read graftling's source from B's graftling archive (`gsrc-0.5.2/src`).

## README 3(a): timers across the install

The only Python file that differs between 871aaaa9 (+ its src/graftling) and 6115c724 + graftling v0.5.2 is
`graftling/__init__.py` (the version line; rehearsed on the stand-in). A budget timer started before the install
meets the same code after it; timers are listed (old/new by I's install window), never signalled.

## Rehearsal

`zsh scripts/adopt-503/rehearse.zsh` (set -u; stub claude/ps/sysctl; fake production venv from 871aaaa9 wheels;
stand-in graftling repository from `git archive 871aaaa9 src/graftling` with 395's version bump, an annotated v0.5.2
tag and a working-tree change after the tag). Output: `rehearsal-output.txt`.

Not rehearsable here: the real `<Harness>/graftling` (unreadable in the team sandbox; B checks its tag and commit),
real Claude Code (`claude -p`, plugin load in Vc, the trust dialog), real Pi/DSH hosts (P/Pr use fixture records),
the real full suite (S runs its setup and quiet wait only), and production `.venv-runtime` writes.
