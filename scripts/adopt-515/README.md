# Task 515 — production adoption of the MCP server rename (graftling v0.6.0 + GraphTraj dev 4ad22e90)

`steps.zsh` installs graftling 0.6.0 (a wheel from `git -C <Harness>/graftling archive v0.6.0`; v0.6.0 must peel to
a51e1004a0fe77fe492681faa2f278d80b3d725e) and graphtraj (a wheel from `git archive 4ad22e90`, Requires-Dist
`graftling<0.7,>=0.6.0`, 0 graftling files) into production `<Harness>/.venv-runtime`, which holds 503's
graftling 0.5.2 + 6115c724. It is `scripts/adopt-503/` copied and adapted (adopt-503 unchanged). Every 503 protection is
kept: isolated real-host project, proddiff file by file, markers both ways, backup `<Harness>/tmp/515/backup` and
rollback R from the backup's own tool copy, the guard that waits (never signals) and runs again right before pip,
Claude Code version recorded at 00, no exported key value in raw output, timers listed and never signalled.

Run: `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/515-production-adoption-mcp-server-names/scripts/adopt-515/steps.zsh <step>`.
Raw output: `.graphtraj/core/state/tasks/515-production-adoption-mcp-server-names/adoption/raw-4ad22e90/`.
Base: `<Harness>/tmp/515/`. Isolated project: `/private/tmp/vproject-515` (user 2026-11-18; under the Harness it would
merge the Harness `.mcp.json`). Each step prints who runs it, its dialog, how to judge it and the next command.

## Step order

| Step | Who | Dialog | Time |
|---|---|---|---|
| 00 preflight | Main | none | ~2 min (one `claude -p`, 120 s cap) |
| B two wheels | Main | none | < 2 min |
| V pre-install checks | Main | none | ~2 min |
| S reused suite evidence (no pytest) | Main | none | < 10 s |
| Vu | **USER** (Terminal) | one: folder trust for `/private/tmp/vproject-515` → **Yes, proceed**; then `/exit` | < 1 min |
| Vc | Main | none | ~2 min |
| Mpre | Main | none | < 1 min |
| `/exit` Main | **USER** | — | — |
| I backup + install + `configuration --write` | **USER** (Terminal) | none | ~3 min + waiting for members (Ctrl-C safe) |
| `cd <Harness> && claude --continue` | **USER** | at most one plugin/hooks trust dialog (host_context.mjs bytes change) → **trust**; no MCP dialog expected (`graphtraj` is already in enabledMcpjsonServers; enableAllProjectMcpServers true) | — |
| M (prompts), Main edits settings.local.json | Main | none | < 1 min |
| Mp, Mps, inbox | Main | none | < 2 min each |
| Rs (Main resumes the Leader), Rsr | Main | none | Leader + Engineer a few min |
| Nw (background), N, Nt, Nr, N484 | Main | none | member + child 5-10 min |
| done | Main | none | < 1 min |
| T (after the Leader accepts 515) | Main | none | < 30 s |
| R rollback (only on failure) | **USER** (Terminal, Main exited) | none | waits like I |

## Criterion → observable

| Definition item | Observable (step: line) |
|---|---|
| 1 install, `.mcp.json` only `graphtraj`, plugin matches | B: `v0.6.0 peels to a51e1004…: yes`, `graftling wheel version: 0.6.0`, `Requires-Dist: graftling<0.7,>=0.6.0`, `carries graftling/: 0`. V: `graftling wheel vs …: differing 0: SAME`, markers 7/7 both ways, `CHECK 515 candidate host_context.mjs const SERVER = "graphtraj": PASS`. I: `Successfully installed graftling-0.6.0 …`, `PASS n FAIL 0`, `configuration --write rc=0`, `CHECK 515 .mcp.json has graphtraj, no agents, no other graphtraj/graftling server: PASS`, `CHECK 515 host_context.mjs const SERVER = "graphtraj": PASS`, `CHECK 515 settings.local.json bytes unchanged …`. |
| 2 full suite | S: reused 514 F (142bdd8e, 3587 passed) + V (4ad22e90, 4 passed); `CHECK 515 no src change between 514's F commit and the adopted commit: PASS`. |
| 3 Main's names | M-a: Main's own answer (has mcp__graphtraj__agents/tasks, no mcp__agents__*); Mp: four `CHECK 515 init …: PASS` from a bounded `claude -p` in the Harness. |
| 3 dispatched member | Nr: `CHECK 515 [member …] mcp__graphtraj__agents called and answered without error or refusal: PASS`, `no mcp__agents__* call: PASS`, `CHECK 494 Main got exactly one completed notice`, the 503 checks. |
| 3 standby retained Session | Rsr: Engineer agents+tasks PASS, Leader agents PASS, `no mcp__agents__* call: PASS` for both (records after Rs only). |
| 3 468 CPU | Nr: `REPORT 515 468 Worker CPU 30 s before/after child creation: …` (not blocking). |
| 4 restart, notices once | M-a (Main's answer), inbox `duplicate ids: 0`, Nr `CHECK 494`. |

## What changed from 503

- B: v0.6.0 / 4ad22e90; Requires-Dist `<0.7,>=0.6.0`.
- V: graftling CODE differences vs production are expected and listed (`515 graftling CODE files 0.5.2 -> 0.6.0`);
  the gate is the wheel against the v0.6.0 git archive (`graftcode.py <wheel> <site> <archive src>`). The plugin is
  expected to change only in `const SERVER`/`PREFIX` (and `"version"`). `markers.py` holds 7 markers of 514/0.6.0.
- Vc: `.mcp.json` of the isolated project must have only `graphtraj`; the stream uses the new tool names and its
  init record is checked by `rec515.py init`.
- I: backs up (as 503) `.mcp.json`, `settings.local.json` (a copy only; never written by the script), config.json and
  the plugin; installs; runs `python -m graphtraj.runtimes.claude.host configuration --write --project <Harness>
  --claude <claude>` from the new installation; checks the keys and `const SERVER = "graphtraj";`. R restores all of them.
  It prints the exact settings edit for Main: `enabledMcpjsonServers` keeps only `"graphtraj"` (done by Main after the
  restart). Note: `configuration --write` merges GraphTraj's two `env` keys into settings.local.json; their values are
  the same `.venv-runtime` paths, so I expects unchanged bytes and prints `CHANGED` (information for Main) otherwise.
- M/Mp: paste-ready prompt naming the new tools; Mp is one bounded `claude -p` probe in the Harness (no tool call).
- Rs/Rsr (new): Rs finds the Leader alias (`graphtraj task members`), records the byte size of both Sessions' record
  files (graftling archive and Claude transcript), and prints Main's fixed resume message; Rsr reads only what was
  appended after Rs (`rec515.py calls --since`).
- Nr: `rec515.py calls` on the member's raw records. It judges a call by the result's own `is_error`, not by text in
  successful content (514's check514.py misjudged real success records that way). P/Pr (Pi/DSH) are dropped: 515's
  definition does not require them, and their checker (pr503.py) had the defects named by the Leader.
- 468: `cpu468.py window` reports Worker CPU 30 s before and after the child record first appears.
- S/S2 (full suite) replaced by S (evidence only, no pytest).

## README 3(a): timers across the install

Python modules that differ: graphtraj 6115c724..4ad22e90 — `graph/delivery_worldline.py`, `runtimes/claude/{execution,
host,mcp}.py`, `runtimes/dsh/{execution,session_entry}.py`; graftling 0.5.2..0.6.0 — `__init__.py`,
`claude/{display,execution,host,plugin}.py`, `dsh/execution.py`. None of them is loaded by
`graphtraj.execution.budget_idle_timer` at start (checked in the rehearsal's venv: intersection empty). A timer started
before the install keeps running its loaded modules; a delivery after the install starts a new parent Worker process,
which loads the installed 4ad22e90 + 0.6.0 code (so a Claude member it resumes is configured with mcpServer
`graphtraj`). Timers are listed (old/new by I's install window), never signalled.

## Rehearsal

`zsh scripts/adopt-515/rehearse.zsh` starts from an empty base (`$TMPDIR/adopt515-rehearsal` removed), stub
claude/ps, fake production from 6115c724 + the real repository's v0.5.2 (git archive, read only); B reads the real
v0.6.0. Output: `rehearsal-output.txt` (49 checks).

Not rehearsable here: real Claude Code (the plugin load in Vc, the trust dialogs, Main's tool list, the init record of
a real `claude -p`), the real member dispatch (N/Nr on a real archive), the real Leader/Engineer resume (Rs/Rsr run on
fixture records shaped like Claude transcripts and graftling archives), the real `graphtraj task members` alias lookup
(the fake venv lists none; the rehearsal writes the alias files), and production `.venv-runtime` writes. Steps
unchanged from 503 (Nw, N, Nt, N484, T, Mps, inbox) are covered by adopt-503's rehearsal and not rerun.
