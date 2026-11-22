# Task 571 — graftling 0.6.4 release and production adoption of the paired GraphTraj candidate

Production now: graphtraj 8949caff + graftling 0.6.3 (560, v0.6.3 = ef7c37db); Task state already migrated (563, by 560).
After 571: graphtraj 956c6ff9 (GraphTraj dev 11f84ed6 + `graftling>=0.6.4,<0.7`) + graftling 0.6.4 (v0.6.4 = d5b33498).
No Task-state migration.

- **graftling 0.6.4** (`graftling-0.6.4.bundle`, branch `agent/571-graftling-0.6.4`, one commit on graftling dev
  00778d1 = v0.6.3 + 551 + 569): `d5b33498` `graftling 0.6.4 (571)`, author and committer
  `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`. Version 0.6.4 in `__init__.py`, the Claude plugin manifest,
  the root `package.json` (569), `dsh/package.json` and `pi/package.json`; the two DSH plugin-Python tests that named
  `0.6.3-` environments; CHANGELOG `## 0.6.4 (incompatible)` with 551's and 569's entries; the classification recorded
  in PUBLIC_API section 7. Incompatible by section 7 only because a Claude child created without `tools` no longer gets
  the fixed `--tools Bash,Read,Write,Edit,Glob,Grep` (a default with observable behaviour); released as a patch by the
  user's decision of 2026-11-23, as 477 was in 0.5.2. Everything else adds names, optional arguments or fields.
- **graphtraj** `956c6ff9`: `graftling>=0.6.4,<0.7` (pyproject) and the README's range. GraphTraj dev imports names
  0.6.3 lacks: `graftling.codex/pi/dsh.apply_tools` and `extra_tool_table` (`src/graphtraj/execution/agent_driver.py`
  58/69/75/355), `CodexDriver(extra_tools=)` (151) and Pi's `childServer` (`src/graphtraj/runtimes/pi/extension.mjs:9`).
  B checks `Requires-Dist` is satisfied by 0.6.4 and NOT by 0.6.3; I installs both wheels together.

Run each step as `zsh <Worktree>/scripts/adopt-571/steps.zsh <step>`. Raw output goes to
`.graphtraj/core/state/tasks/571-graftling-0-6-4-release-and-production-adoption/adoption/raw-956c6ff9/`; backups and
scratch under `<Harness>/tmp/571` (Main creates it); isolated real-host projects `/private/tmp/vproject-571` and
`/private/tmp/graftling-571`. Each step prints who runs it, the single native dialog it may show (or none), the PASS
lines and the next command. Copied from `scripts/adopt-560/` (unchanged there) with every 503/515/525/528/532/560
protection, minus the layout proof and the 563 migration. Fixed from 560: done's counts (`print -l <glob>(N) | wc -l`
counted 1 for no match; now `count`), M's task_graph view (`current`, not the invalid `summary`), step order (GraphTraj
integration only after the Leader's acceptance; B does not need the candidate on dev).

## Step order

| Step | Who | Dialog | PASS lines (all must hold) |
|---|---|---|---|
| 00 preflight | Main | none | `answer check (expect clean): OK` (model claude-opus-5-5, logged in); `CHECK 571 Codex answers CODEX-571-OK …: PASS`; `TMPDIR=… (outside the Harness)`; `markers expected absent: PASS (8/8)`; `isolation: OK`; MAIN=<id> |
| rel graftling release | Main | none | `CHECK 571 v0.6.4 peels to d5b33498…: PASS`; `CHECK 571 graftling main == v0.6.4: PASS`; `CHECK 571 graftling dev == v0.6.4 (fast-forward) or a noreply merge containing it: PASS`; `CHECK 571 v0.6.4 is annotated with the noreply tagger: PASS`. dev still 00778d1: fast-forward. dev moved (570): noreply merge; a conflict aborts the merge and STOPs with dev, main and the tag unchanged |
| rp push (only after the USER's explicit yes) | Main | none | `CHECK 571 remote main and v0.6.4 = d5b33498…, remote dev = local dev: PASS` |
| gh (result 4, after rp) | Main | none | in `DSH_HOME=/private/tmp/graftling-571/home`, `dsh plugin --profile gh571 add https://github.com/LUOXIAO92/graftling.git` (no commit, no path): `CHECK 571 gh: bare … registers graftling-dsh as a profile bundle: PASS`; `… package.json says 0.6.4: PASS`; `~/.dsh profiles unchanged: PASS` |
| B wheels | Main | none | `product guard: PASS`; `CHECK 571 v0.6.4 version strings all 0.6.4: PASS`; both Requires-Dist CHECKs; both `… wheel equals git archive …: PASS`; `markers expected present: PASS (8/8)`; `leaked: 0` |
| G full suite | Main | none | background, 6 shards, ~25-30 min once started; pytest temp under `TMPDIR=${TMPDIR:-/tmp}` (outside the Harness). Main's queue is serial: if another suite runs, G prints `WAITING: …` with the running processes and starts by itself when it ends (`<record>/wait.txt`). |
| GR (after G) | Main | none | `CHECK 571 G record (956c6ff9 + v0.6.4) no new failure: PASS`; `CHECK 571 GR (guard + G record): PASS` |
| V pre-install | Main | none | three `SAME` and `CHECK 571 candidate plugin unchanged (predicted): PASS`; MCP tools/list and two Codex hooks CHECKs; markers both ways; read check of production state |
| Vu (only if Vc asks) | **USER** | folder trust for `/private/tmp/vproject-571` → Yes, proceed | — |
| Vc isolated real host | Main | none | as 560 |
| Mpre | Main | none | `GR: PASS …` |
| `/exit` Main | **USER** | — | — |
| I backup + pair install + configuration --write + real entries | **USER** (Terminal) | none | see I's success line (`CHECK 571 graftling 0.6.3 dist-info gone`, direct_url, markers 8/8, `CHECK 571 installed plugin unchanged`, MCP tools/list = agents,tasks, Codex hooks) |
| `cd <Harness> && claude --continue` | **USER** | predicted none (plugin unchanged); if the graphtraj-claude-host plugin/hooks trust dialog still shows: trust, and tell Main | — |
| M, Mp, Mps, inbox | Main | none | M[b] uses task_graph view `current` |
| Nw, N, Nr, Nt | Main | none | as 560 (one advisor member creates `n571`) |
| done | Main | none | both versions and direct_urls; `graftling 0.6.3 dist-info left: 0`; `task.md 0`; real entries PASS |
| integrate this Task's branch into GraphTraj dev — after the Leader accepts 571 | Main | — | task_integrate succeeds |
| T (after acceptance and integration) | Main | none | as 560 |
| R rollback | **USER** | none | venv and plugin SAME; `CHECK 571 graftling restored …`, `graphtraj restored …`, `R: graftling is 0.6.3 again: PASS` |

## Dialog prediction

graftling 0.6.3..0.6.4 changes only `claude/driver.py` and `claude/execution.py` under `src/graftling/claude/` (the
child, not the plugin); `claude/plugin.py` writes plugin version `'1'` whatever graftling's version; GraphTraj
8949caff..956c6ff9 leaves `plugins/` and `src/graphtraj/runtimes/claude/host*.py` unchanged. So `configuration --write`
should leave graphtraj-claude-host byte-identical and no plugin/hooks trust dialog is expected at resume. V regenerates
the plugin with the candidate and stops if anything changed.

## Full suite

Known failures are only the tests (or helpers) named by Task 516's CURRENT definition (through its task.yml). 560's
other known lines are fixed on dev and count as NEW if they fail again (gr571.py names each source):
`test_native_gateway …` ×4 (551: `551…/realhost/main-raw/GR-v063.txt`), `test_child_env_own_key …` (566:
`566…/realhost/GR.txt`, Gt PASSED), `test_pi_attachment_private_paths …collection_entry…` (565:
`565…/realhost/main-raw/GR.txt`).

## Rehearsal

`zsh scripts/adopt-571/rehearse.zsh` (output kept in `rehearsal-output.txt`). Fake production under `$TMPDIR`
(graphtraj 8949caff + the real v0.6.3 wheel, production deps, an APFS-clone copy of production Task state), a scratch
graftling clone at the dispatch state with dev in a linked worktree and a scratch bare `origin`, a scratch GraphTraj
clone whose dev is 11f84ed6 without the candidate, stub `claude`/`codex`/`ps`/`dsh`; the MCP server and the Codex
hooks entry are real. rel cases: dev at the base, dev moved by 570 (clean noreply merge), conflicting dev (worktree and
no-worktree paths: STOP, nothing changed), dev without the base, a wrong existing tag. rp: refused without the yes;
confirmed, it pushes to the scratch bare. gh against the scratch bare. G runs real tests through its entry, queued first
behind a simulated running suite. GR negatives, proddiff leftover, markers both ways, guard BLOCKING, I without GR PASS,
then I, M, Mp, N, done, and R restores both packages.
