# verify-545: a notice that reaches a DSH Main during its turn, captured headless

Main runs, from this Worktree in Main's Bash: `zsh scripts/verify-545/steps.zsh 00|B|A|T|TR|C`. No step needs user action.

- BEFORE = GraphTraj f754d3a9 + graftling 6794ce0 (both send notices to DSH's `next-step` inbox).
- AFTER = Worktree HEAD + graftling `GLC` (untracked clone `.scratch/graftling`, git dir `.scratch/graftling-git`, branch `agent/545-dsh-in-turn-notice-invisible`), both sending to `next-turn`.
- Real-host files live under `/private/tmp/dsh-ui-545/<before|after>`: DSH_HOME, the projects and the venvs. Web profile `web545`.
- BUSY prompt (G, S): create one member, then one shell `sleep 90` (`VERIFY545_BUSY_S`), then the SENT line. The member's end notice arrives while that turn runs. IDLE prompt (GI, AFTER only): create, then SENT, then the turn ends, so the notice arrives after the turn has ended.

| step | dialog | observable |
|---|---|---|
| 00 | none | `headless browser:`, the venv line, `send target: ... 'next-step', true \| ... 'next-step', true`, `roles OK` + `probe Task 1 ready`, `graftling-dsh: in web545`, S/G rows, one `READY-545-DSH` line (deepseek-flash + login), one `READY-545-CLAUDE` line (claude-opus-5-5 + login) |
| B | none | per case (G, S): `notice form in-turn`, `turnTrigger 0`, page order without BLOCK, and the session record line `relay ... turn 1 step N>1 -> inside a running turn`. Pictures: `b-notice-region.png`, `04-expanded-full.png` |
| A | none | `send target` line names `next-turn` twice. G and S busy: `notice form block`, page order `SENT BLOCK GOT`, `GOT lines` = number of blocks, `user inputs 1`, the record line `relay ... turn 2 step 1 -> opened its turn` and `inside a running turn 0`, `duplicate ids []`. GI: the same, for a notice that came after the turn ended. Pictures: `b-notice*.png` (`<member> · <event>` over rendered Markdown), `04-expanded-full.png` |
| T | none | full GraphTraj suite of the AFTER build, in the background; TMPDIR outside the Harness (it prints that) |
| TR | none | `exit=0`, or only `known (516)` lines; any `NEW` line goes to the Leader |
| C | none | copies PNG and redacted text to `.state/realhost/<phase>-run1-<case>-*` and prints the tables |

## Criterion → observable

| criterion | observable |
|---|---|
| required result 1: a notice that reached a running turn opens its own turn afterwards, with no user input | AFTER G/S: session record `turn 2 step 1 -> opened its turn`; `user inputs 1` (the driver types once); page order `SENT BLOCK GOT` |
| the notice block shows who, event and Markdown | `b-notice*.png` (538's format, unchanged) |
| the model handles it, once | `GOT lines` = blocks; each notice has one relay id; `duplicate ids []` |
| no duplicate context node | record: `inside a running turn 0` for that relay id; `dom.relaySender`/`contextText` in the table |
| idle Main still woken | GI: same as above with an idle prompt |

`sessions545.mjs` reads DSH's own session log (zstd JSONL) under the case's DSH_HOME, read only. DSH appends each claimed user/message after `step/start`, so step 1 = the message opened that turn, step > 1 = claimed inside a running turn.

## Rehearsal (`rehearsal/`)

See `rehearsal/*.txt`: step 00 and T/TR from an empty directory through this entry (flags named in each file).
