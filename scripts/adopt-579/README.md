# Task 579 — graftling 0.8.0 release and production adoption of the paired GraphTraj candidate

Production now: graphtraj 98125982 + graftling 0.7.0 (571, v0.7.0 = 6a1f18be).
After 579: graphtraj eb009725 (GraphTraj dev 4b20eed7 + `graftling>=0.8.0,<0.9` + the correction 1 test fix) +
graftling 0.8.0 (v0.8.0 = 542a81df). The user confirmed 0.8.0. No Task-state migration.

## Correction 1 (user decision Option A)

Main's G on 6aa25a80 found one NEW failure:
`tests/test_pi_attachment_private_paths.py::test_extension_still_hands_an_explicit_agents_session_to_graftling[agents-config]`.

Cause: the test's fake Pi context gave every Session `getSessionFile() == ''`. Since graftling 585, a Session without a persistent Session file is a subagent child, which starts no host.

Fix (`eb009725`, test only):
- `extension_session_start(session_file=True)` gives only that case a persistent Session file, as a real Pi Main has.
- Every other user keeps `''`.
- src, plugins and pyproject.toml equal 6aa25a80's, and product_guard prints and enforces that.

The candidate is now `eb009725`, so the raw directory is `raw-eb009725/` and the wheels, G records and V copies are named after it.

rel, rp and gh are done; do not rerun them. If they were rerun:
- rel only verifies (`already released`) and changes nothing.
- rp pushes local graftling dev, main and v0.8.0 again, fast-forward only. main and the tag are unchanged; dev would move only if local dev has moved since.
- gh only reads GitHub.

Main reruns from B: B → G → GR (→ SR / suite-base only if NEW) → V → Vc → Mpre → I → …

## The two commits

**graftling 0.8.0** is `542a81df0c941f5b1a425d9807681b2a38daa87c` `graftling 0.8.0 (579)`.
- It is carried as `graftling-0.8.0.bundle`, branch `agent/579-graftling-0.8.0`.
- It is one commit on graftling dev fb9db6a, which already holds 570, 572, 574, 576, 577, 578, 581 and 585.
- Author and committer are `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`.

What the commit changes:
- Version 0.8.0 in `__init__.py`, the Claude plugin manifest, and `dsh/package.json` and `pi/package.json`.
  - The in-package marketplace carries no version.
  - The tests derive the version from `graftling.__version__`.
- CHANGELOG `## 0.8.0 (incompatible)`, with a lead that names the three incompatible changes:
  - 581 removes 0.7.0's released install route;
  - 576 changes the default tool set;
  - 585 leaves `pi --no-session` without `agents`.
- The CHANGELOG sections Added, Changed, Removed and Fixed each appear once. The 570 and 572 (Pi) entries were missing from Unreleased and are added.
- PUBLIC_API section 7 records the classifications:
  - compatible: 570, 572, 574, 577 and 578;
  - incompatible: 576, 581 and 585.
- The `Unreleased (5xx)` markers now read `0.8.0 (5xx)`. `src/graftling/PUBLIC_API.md` is a link to the root copy, so the two are byte-identical.
- graftling's full suite on the commit: **862 passed, 21 skipped, exit 0**. The pytest temp root was under TMPDIR.

**graphtraj** is `6aa25a80`.
- It sets `graftling>=0.8.0,<0.9` in pyproject.toml and the README's range, and updates the README DSH note's 0.8.0 markers.
- No check under src/tests/plugins pins the range: `tests/test_runtime_distribution.py` derives it from the installed graftling.
- B checks that `Requires-Dist` is satisfied by 0.8.0 and NOT by 0.7.0 or 0.9.0.

## Layout

- Run each step as `zsh <Worktree>/scripts/adopt-579/steps.zsh <step>`.
- Raw output goes to `.graphtraj/core/state/tasks/579-graftling-next-release-and-production-adoption/adoption/raw-6aa25a80/`.
- Backups and scratch go under `<Harness>/tmp/579` (Main creates it).
- The isolated real-host project is `/private/tmp/vproject-579`.
- 571's backup `<Harness>/tmp/571/backup` is only listed, never touched.

Each step prints:
- who runs it;
- the single native dialog it may show, and the choice, or that none should show;
- its PASS lines;
- the next command with real values filled in.

The steps are copied from `scripts/adopt-571/` (unchanged there) with every 503/515/525/528/532/560/571 protection.

Changed from 571:
- **gh (result 4).**
  - 581 removed the bare-URL `dsh plugin add` route that 571's gh used.
  - gh now only reads GitHub with `git ls-remote`: main = 542a81df, `v0.8.0^{}` = 542a81df, and the remote tag object equals the local annotated tag.
  - It installs nothing, and touches no host, dotfile or `~/.dsh`.
- **00 preflight.**
  - Claude and Codex each answer a one-line prompt with their configured model and login.
  - Each prints its provider line.
  - The step checks that it runs through zsh and that TMPDIR is outside the Harness.
  - It checks that the probe Task 579 has a current definition, and that Ma's arguments-file path is inside the project and outside `.graphtraj`.
- **G.**
  - The suite starts through `clean()`: only HOME, USER, PATH, TERM, TMPDIR and LANG, so no provider credential reaches it.
  - `run.txt` records the launch environment and the pytest temp root under `TMPDIR=${TMPDIR:-/tmp}`, outside the Harness.
  - A `ps` that cannot list processes STOPs G before anything is built. It is never read as "no other suite".
- **GR, SR and suite-base** (as verify-586).
  - Whole node ids are read from the shard logs with `scripts/verify-581/suiteids.py`, because suite.txt's summary cuts an id at its first space.
  - An id is known only when Task 516's current definition (through its `task.yml` `current_definition`) names it.
  - Any other id, or an ABNORMAL shard other than test failures, is NEW.
  - SR prints `suite-base` with each NEW id as a separate quoted argument, and the `--from` form.
  - suite-base reruns those ids on GraphTraj 4b20eed7 + graftling fb9db6a (wheel) and on the candidate.
- **Plugin.**
  - graftling 0.7.0..0.8.0 changes `claude/host_context.mjs` (577: `--data-root` from `GRAFTLING_DATA_ROOT`). Production's `graphtraj-claude-host` plugin is written from it.
  - V regenerates the plugin with the candidate. It requires `plugin.json` and `hooks.json` SAME, and `hooks/host_context.mjs` changed by exactly 577's lines (`plugin579.py`). It STOPS on anything else.
  - I checks the same after `configuration --write`.
  - **Prediction: the plugin/hooks trust dialog for graphtraj-claude-host shows at `claude --continue`. The USER chooses trust.**
- **575.**
  - Ma writes `<Harness>/tmp/579/args-575.json` = `{"view":"current","details":["579"]}`.
  - Ma reads the file with the installed graphtraj's `read_arguments_file` against the project root, as Main's host does.
  - Ma prints M[d]'s exact call: `{"action":"execute","feature":"task_graph","arguments_file":"<Harness>/tmp/579/args-575.json"}`, with no `arguments`.
  - Observable: no error, and the result gives Task 579's current definition path. Only the file holds that detail.
- **576 (571 F1).**
  - N's member creates the Claude child `n579` WITHOUT `tools`. The child must run `echo n579-tool && sleep 20` with Bash and reply DONE-579.
  - Nr checks that `selection.tools` is null, that the member quotes DONE-579, and that a Bash tool_use with that command is archived.
- **571 F2.** rec515.py reports graftling's `not-running` answer as `info: not-running` and does not count it as an error.
- **571 F3.** V's package comparisons print `INFO … differs (expected; information, not a check)`, never `FAIL (STOP)`.
- **Asking the user.** rp, I and R say in their header, and in the next-command line before them, that Main asks the USER first.

## Step order

| Step | Who | Dialog | PASS lines (all must hold) |
|---|---|---|---|
| 00 preflight | Main | none | `answer check (expect clean): OK` (model claude-opus-5-5, logged in); `CHECK 579 Codex answers CODEX-579-OK …: PASS`; two `provider used:` lines; `ZSH_VERSION=…`; `TMPDIR=… (outside the Harness)`; `markers expected absent: PASS (7/7)`; `CHECK 579 probe Task 579 ready …: PASS`; `CHECK 579 575 arguments file … inside the project, outside .graphtraj: PASS`; `isolation: OK`; MAIN=<id> |
| rel graftling release | Main | none | `CHECK 579 v0.8.0 peels to 542a81df…: PASS`; `CHECK 579 graftling main == v0.8.0: PASS`; `CHECK 579 graftling dev == v0.8.0 (fast-forward) or a noreply merge containing it: PASS`; `CHECK 579 v0.8.0 is annotated with the noreply tagger: PASS`. If dev moved, a noreply merge is made; a conflict aborts it and STOPs with dev, main and the tag unchanged |
| rp push (Main asks the USER first; only after an explicit yes) | Main | none | `CHECK 579 remote main and v0.8.0 = 542a81df…, remote dev = local dev: PASS` |
| gh (result 4, after rp) | Main | none | `CHECK 579 gh: GitHub graftling main = 542a81df…: PASS`; `CHECK 579 gh: GitHub v0.8.0 resolves to 542a81df…: PASS`; `CHECK 579 gh: GitHub v0.8.0 is the local annotated tag object (…): PASS`; `installed: nothing` |
| B wheels | Main | none | `product guard: PASS`; `CHECK 579 v0.8.0 version strings all 0.8.0: PASS`; `CHECK 579 v0.8.0 has no 0.7.0 install route …: PASS`; Requires-Dist satisfied by 0.8.0 and NOT by 0.7.0 or 0.9.0; two `… wheel equals git archive …: PASS`; `markers expected present: PASS (7/7)`; `leaked: 0` |
| G full suite | Main | none | Runs in the background, 6 shards, about 25-30 min once started. The pytest temp root is under `TMPDIR=${TMPDIR:-/tmp}`, outside the Harness (printed). The suite queue is serial: while another suite runs, G prints `WAITING: …` and starts by itself. A failing ps STOPs G |
| GR (after G) | Main | none | `node ids read from: 6 shard logs (whole ids)`; `CHECK 579 G record (6aa25a80 + v0.8.0) no new failure: PASS`; `CHECK 579 GR (guard + G record): PASS` |
| SR / suite-base (only if GR names NEW ids) | Main | none | SR prints `next (paste): zsh … suite-base '<id>' …`; suite-base prints per-id classification (a candidate-only id is a regression) |
| V pre-install | Main | none | `SAME .claude-plugin/plugin.json`, `SAME hooks/hooks.json`, `CHANGED hooks/host_context.mjs`; `CHECK 579 plugin hooks/host_context.mjs differs by exactly 577's --data-root change: PASS`; `CHECK 579 candidate plugin as predicted (only hooks/host_context.mjs, by 577): PASS`; MCP tools/list and two Codex hooks CHECKs; markers both ways (7/7); INFO lines `differs (expected; …)` |
| Vu (only if Vc asks) | **USER** | folder trust for `/private/tmp/vproject-579` → Yes, proceed | — |
| Vc isolated real host | Main | none | as 571 |
| Mpre | Main | none | `GR: PASS …`; next line: Main asks the USER before /exit and I |
| `/exit` Main (Main asks first) | **USER** | — | — |
| I: backup, pair install, `configuration --write`, real entries | **USER** (Terminal) | none | `Successfully installed graftling-0.8.0 graphtraj-0.1.0`; `CHECK 579 graftling 0.7.0 dist-info gone: PASS`; direct_url; markers 7/7; `SAME-AS-VALIDATED`; `CHECK 579 installed plugin changed as V predicted (only hooks/host_context.mjs): PASS`; `CHECK 515 .mcp.json …: PASS`; `CHECK 579 production-graphtraj-mcp MCP tools/list is exactly agents, tasks: PASS`; two Codex hooks CHECKs |
| `cd <Harness> && claude --continue` | **USER** | **expected: the plugin/hooks trust dialog for graphtraj-claude-host → trust** (any other dialog: Esc, and tell Main) | — |
| Ma (575) | Main | none | `CHECK 579 575 arguments file readable by the installed graphtraj (project root, not .graphtraj): PASS`; the exact M[d] call with the real path |
| M (a, b, d, then c: Mp, Mps, inbox) | Main | none | M[d]: no error, and Task 579's current definition path in the result |
| Nw, N, Nr, Nt | Main | none | N: the child is created without tools. Nr: `CHECK 576 child created without tools …: PASS`, `CHECK 576 child without tools ran Bash and replied DONE-579 …: PASS`, `CHECK 576 a Bash tool_use … in a Session archive: PASS` (or CHECK BY HAND), plus 571's CHECKs, with `not-running` not counted |
| done | Main | none | both versions and direct_urls; `graftling 0.7.0 dist-info left: 0`; real entries PASS; `raw files containing an exported key value: 0` |
| integrate this Task's branch into GraphTraj dev, after the Leader accepts 579 | Main | — | task_integrate succeeds |
| T (after acceptance and integration) | Main | none | as 571 |
| R rollback (Main asks the USER first) | **USER** (Terminal, Main exited) | none at R. At the next `claude --continue` the plugin is back to 0.7.0's, so the plugin/hooks trust dialog may show again → trust | venv and plugin SAME; `CHECK 579 graftling restored …`, `graphtraj restored …`, `CHECK 579 R: graftling is 0.7.0 again: PASS` (graphtraj 98125982 + graftling 0.7.0 from `<Harness>/tmp/579/backup`) |

## Rehearsal

`zsh scripts/adopt-579/rehearse.zsh` (output kept in `rehearsal-output.txt`) sets up:
- a fake production under `$TMPDIR`: graphtraj 98125982 + the real v0.7.0 wheel, with its plugin written by 0.7.0;
- a scratch graftling clone at the dispatch state, with a scratch bare `origin` that stands in for GitHub in rp and gh;
- a scratch GraphTraj clone whose dev is 4b20eed7;
- stub `claude`, `codex` and `ps`.

The MCP server, the Codex hooks entry and Ma's `read_arguments_file` are real. The rehearsal does not exercise a real Claude Main, real member dispatch, the real trust dialog or GitHub (see the Leader report).
