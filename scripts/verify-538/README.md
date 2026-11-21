# verify-538: the GraphTraj notice block in DSH, captured headless

Main runs, from this Worktree in Main's Bash: `zsh scripts/verify-538/steps.zsh 00|B|A|T|TR|C`. No step needs user action.

- BEFORE = GraphTraj 9ae7a149 + graftling fc081a3f.
- AFTER = Worktree HEAD + graftling 70542bc5. That graftling commit is in the untracked clone `.scratch/graftling` (git dir `.scratch/graftling-git`), branch `agent/538-dsh-graphtraj-notice-block-display`.
- Real-host files live under `/private/tmp/dsh-ui-538/<before|after>`: DSH_HOME, the projects and the venvs.

| step | dialog | proves (observable) |
|---|---|---|
| 00 | none | Each of these lines appears: `headless browser:`, the venv line, `roles OK` and `probe Task 1 ready`, `graftling-dsh: in web538`, the S/G rows, one `READY-538-DSH` line (deepseek-flash + login) and one `READY-538-CLAUDE` line (claude-opus-5-5 + login) |
| B | none | BEFORE pictures, as before-run1-{G,S}-*.png; the table printed at the end |
| A | none | AFTER pictures for run1 and run2 on the same commits; the table puts run1 and run2 side by side ("same result" = same reached phases and the same (a)/(b) observables) |
| T | none | full GraphTraj suite of the AFTER build, in the background, TMPDIR outside the Harness (it prints that) |
| TR | none | `exit=0`, or only `known (516)` lines; any `NEW` line goes to the Leader |
| C | none | copies the PNG and redacted text to `.state/realhost/<phase>-<run>-<case>-*` and prints the tables |

## Criterion → observable

| criterion | observable |
|---|---|
| (a) send card with IN visible | `a-send-card.png`. In `observed.json` it is `tools[].send=true` with `inShown=true` |
| (b) member-end notice | G: `b-notice*.png`, one per `section[data-agent-incoming]`/`[data-turn-trigger]`. S with an in-turn notice: `b-notice-region.png` (the GOT line up to the text that mentions the notice) |
| sender is the member, not `graphtraj` | `b-notice*.png` header `<alias> · <event>`. `observed.json notices[].showsGraphtrajAsSender=false` |
| no repeated values | `notices[].adjacentRepeatedLines=[]`. The picture shows no doubled id |
| Markdown readable | the picture shows a heading, a list and a code block rendered. `markdownSource=false` means no raw `##`/`- `/```` ``` ```` lines are left in our block (DSH's native card under it still holds the model text when it is expanded) |
| ids the model needs | DSH's native `Task message received` card (expand it) holds the title with the execution id and the `Facts:` line |
| in-turn notice (S) | `observed.json dom`: elements whose own text starts with a notice title or `From session`, and whether they are visible |
| rerun on the same commit | A's table, run1 vs run2 |

## Rehearsal (`rehearsal/`)

- `00.txt`: step 00 from an empty directory in the Engineer sandbox, with VERIFY538_NOMODEL/ASSUME_PLUGIN/NOBROWSER. The sandbox has no browser cache, no `claude`, and no pnpm store lock.
- `T-TR.txt`: T and TR from an empty directory, with VERIFY538_TESTS set to real repository tests (conftest + `project` fixture), through the same venv and entry as the full suite.
- `old-vs-new.txt`: the 538 GraphTraj test fails on 9ae7a149 and passes on the candidate; the graftling client fixture fails on fc081a3f and passes on 70542bc5 (stand-in SlotCore).
