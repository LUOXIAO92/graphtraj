# verify-481: a user-started headless DSH as GraphTraj Main

Main runs each step as `zsh scripts/verify-481/steps.zsh <step> 2>&1 | tee <OUT>/<step>.txt`
(each step prints the next ready-to-paste command). Base `<Harness>/tmp/481`: isolated project
`tmp/481/project` (own git and `.graphtraj`), candidate venv `tmp/481/venv` (editable from this
Worktree; production `.venv-runtime` is only read for dependency copies). Evidence:
`.graphtraj/core/state/tasks/481-dsh-user-started-main-docs/realhost`. The DSH turns use exactly
the README "DSH as Main" form: `dsh --profile headless --patch <file>` with the patch written by
`python -m graphtraj.runtimes.dsh.main_entry patch --write`; the candidate venv is not on `PATH`
and `GRAFTLING_DSH_CONFIG` is never set (graftling-dsh stays installed). The 398/373 judgements
reuse `scripts/verify-444/probe.py`.

| Step | Does | Dialog | Success lines | Wait limit |
| --- | --- | --- | --- | --- |
| 00 | production Main recorded; candidate venv; isolated project + probe Task 1 ready; `claude` and `dsh` each answer one line; patch written; ONE real `tasks` discover through the patched headless DSH | none | `PASS 00: the patched headless DSH claimed Main at agent/created and called its tasks tool` (from `continuity.jsonl` and stream records, not model text) | 120 + 120 + 300 s |
| D1 | DSH Main creates g398 (sleep 60) and exits; 100 s later its end is still queued | none | `PASS 398 part 1` | 300 + 100 + 60 s |
| D2 | resume (`--session-id`): g398 delivered once (queue cursor); dispatch the asker | none | `PASS 398 part 2`, `397 record delivered once: PASS` (probe label) | 300 s |
| D3 | wait 120 s, resume: the asker's two requests reach the DSH Main, each denied | none | probe `373[D3x] (a)-(d)` PASS lines, `PASS 373-DSH target absent` x2 | 120 + 300 s |
| SUITE | full suite, 8 shards, `TMPDIR=${TMPDIR:-/tmp}` (outside the Harness); new failures vs `verify-482/baseline-failures.txt` | none | `PASS SUITE: no new failures` | 1500 s |
| F | production Main unchanged; every pid this script started ended; PASS/FAIL summary | none | `F production Main: PASS`, `ended:` per pid | 0 |

Sum of wait limits: 3400 s (about 57 min) worst case; a normal run is far shorter (DSH turns
usually end within a minute or two, the suite in 12-20 min).
If 00 prints FAIL, skip to F: D1-D3 would not show anything about this entry.
