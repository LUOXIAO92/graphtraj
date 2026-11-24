# Task 612: graftling 0.10.0 release and production adoption (with GraphTraj 610, 611)

The user made these decisions for this Task (Worldline user-decisions):
- **Release, push and adoption** ("全部做完后直接发布并换到生产"): 20261124T212818.736102+0900. The release decision is also the push decision.
- **613 included in this release:** 20261124T215350.017660+0900.
- **Version 0.10.0:** 20261124T224332.078396+0900.
- **Login and keys:** the definition's acceptance allows the Claude login the user approved for 603/604, plus OPENCODE_API_KEY and DEEPSEEK_API_KEY. Any other login or key needs Main to ask the user first.

**0.10.0 is incompatible** by PUBLIC_API section 7: 613 refuses a Claude `base_url` without `api_key_env`, which is a new rejection. Compatible in the same release:
- 609: the `subagents` feature `models`, `create`'s `provider`, `discover_models`' `groups`, and the error code `invalid-provider`;
- 608: DSH providers;
- 605: install without a tag;
- 601: CHANGELOG.

Nothing is published to PyPI or npm.

**What changes in production.** `.venv-runtime` now has graphtraj 0.1.0 from 604's wheel of 1fdbbca5, plus graftling 0.9.1 from 600's wheel. **I installs both new wheels**: graftling 0.10.0 built from the tag, and graphtraj built from git archive TARGET. It runs `pip install --force-reinstall --no-deps --no-index`. graphtraj's version is still 0.1.0, so without `--force-reinstall` pip would skip it.

**The hook copy** is written from graftling's `claude/plugin.py` and `claude/host_context.mjs` and GraphTraj's `runtimes/claude`. None of them changed since production, so the copy should stay byte-identical: no regeneration, and no trust dialog at `claude --continue`. V checks this through the product itself and STOPs on any difference.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| graftling dev at dispatch (GBASE) | `ddc506b0a7f87372baf8edc2347c26eebc2a251c` (619db60 601, 605, 608, 609, 613) |
| graftling main = v0.9.1 (GMAIN0) | `e8c2e80241dff1151f2122e8957fca5598ec987b` |
| release commit (GCOMMIT) | `6f4aeb8fe9f47b71d81b9771486167b123308066` "graftling 0.10.0 (612)": one commit on GBASE that changes 5 files. Author and committer: LUOXIAO92 &lt;89069722+LUOXIAO92@users.noreply.github.com&gt;. |
| bundle | `graftling-0.10.0.bundle` (`ddc506b0..agent/612-graftling-0.10.0`); sha256 `fec2ae72c19b6c1b9ecd27b4639f32476c292b7231cfe83cb71b4daabe9f3824` |
| tag | annotated `v0.10.0` at GCOMMIT, with the noreply tagger; the message names 613, 609, 608 and "incompatible" |
| GraphTraj TARGET | `78f929eed956714ba2d6e83fb2ace953f8a56bcb`: GraphTraj dev `6c0756c3` (610, 611) + `graftling>=0.10.0,<0.11`. Its product files (src, tests, plugins, manuals, pyproject.toml) equal 6c0756c3 except that one line. Main integrates it into dev after acceptance. |
| production now (R's target) | graphtraj `1fdbbca5` (604's `wheels-1fdbbca5`) + graftling 0.9.1 (600's `wheels-0.9.1`) |
| new wheels (B writes them; G, V and I install them) | `<state>/tasks/612-…/adoption/wheels-0.10.0/` and `wheels-78f929ee/`, each with SHA256SUMS and COMMIT |
| C5 install | the README's TAGLESS command `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git"` (605), with uv's tool, bin, cache and Python directories under `/private/tmp/uvtool-612` |
| backup | `<Harness>/tmp/612/backup`: venv, hook copy, `.mcp.json`, `settings.local.json`, `config.json`, R's tools (incl. a copy of steps.zsh), `main.session`, and a COMPLETE marker. `tmp/604/backup` stays untouched as the older rollback. |
| raw output | `<state>/tasks/612-…/realhost/main-raw/` |
| scratch | `<Harness>/tmp/612` (00 creates it), `/private/tmp/uvtool-612`, `/private/tmp/vproject-612` |
| child, done word, model | `n612`, `DONE-612`, `claude-opus-5-5` |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-612/steps.zsh <step>`. They form one ordered list. Each step prints:
- who runs it;
- the dialog it may raise;
- whether it needs a login;
- its PASS lines;
- the exact next command.

Every started process gets the allowlist environment (`clean()`: HOME USER PATH TERM TMPDIR LANG). `cred_guard` STOPs if a credential-like name reaches it. No step starts a process carrying OPENCODE_API_KEY or DEEPSEEK_API_KEY.

| step | who | dialog | login | PASS lines (`CHECK 612 <step> …: PASS`) |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/612`) | none | yes: one `claude -p` probe (Claude login, approved) | **Release:** zsh; uv has `--managed-python`; TMPDIR outside the Harness; `$UVT` absent; dev = GBASE and main = GMAIN0 in their worktrees, both clean; v0.10.0 absent locally and on GitHub; GitHub main = GMAIN0 and GitHub dev an ancestor of GBASE; bundle sha256, verify and head; GCOMMIT is one noreply commit that changes exactly 5 files; the README's first install line at GCOMMIT = C5's tagless command. **Adoption:** production = graphtraj from 604's wheels-1fdbbca5 + graftling 0.9.1 from 600's wheel; pip check; bin; `tmp/604/backup` COMPLETE (information); `tmp/612/backup` absent; product guard; Task 612 ready; `claude -p` answers READY-612; Main's Session id saved |
| rel | Main | none | no | v0.10.0 peels to GCOMMIT; main == dev == GCOMMIT; annotated tag with the noreply tagger; message; version 0.10.0. **STOPs, changing nothing, if dev ≠ GBASE or main ≠ GMAIN0.** A rerun prints "already released". |
| B | Main, before the push | none | no | **graftling wheel** (from git archive v0.10.0): version strings in the archive and the wheel; CHANGELOG heading `## 0.10.0 (incompatible)` and no Unreleased; console scripts exactly subagents, subagents-mcp; wheel = archive; 613/609/608 markers; no build/ or `__pycache__`. **graphtraj wheel** (from git archive TARGET): wheel = archive; the 7 data files = the archive's manuals; entry_points.txt and Requires-Dist equal 604's wheel apart from graftling; graftling range includes 0.10.0 and excludes 0.9.1 and 0.11.0; 611 markers; no build/ or `__pycache__`. Both directories hold SHA256SUMS and COMMIT. |
| G | Main, **started as a Runtime background command**; the Runtime notifies Main when it exits. ~25-30 min once the shards start, plus any wait behind another suite. | none | no | The GraphTraj full suite through `scripts/run_test_shards.py` (6 parallel shards): this Worktree's HEAD (editable; product = TARGET) + the 0.10.0 wheel, clean environment. The pytest temp is under TMPDIR, outside the Harness; the step says so and checks it. **G's own process waits**: first for the serial queue if another suite runs, then for the shards. It then runs GR's checks on the record. **Its last lines are** `RESULT 612 G/GR: PASS|FAIL \| <passed, failed, skipped> \| known non-blocking ids \| NEW ids \| ABNORMAL shards` **and the next command**: SR if anything is NEW, else V once rp, gh and C5 have passed. While G runs, Main continues with rp, gh and C5. |
| rp | Main; `ADOPT612_PUSH_CONFIRMED=yes` | none | no (the user's usual git credentials) | remote main == v0.10.0^{} == GCOMMIT; remote dev == local dev. The push is atomic and fast-forward only, never forced. STOPs before rel and when unconfirmed. |
| gh | Main, read only | none | no | GitHub main = GCOMMIT; v0.10.0^{} = GCOMMIT; GitHub's tag object = the local one |
| C5 | Main | none | no | README's tagless command from GitHub, in `/private/tmp/uvtool-612`: rc 0; version 0.10.0; sys.prefix; base interpreter uv-managed; commit_id = GCOMMIT (GitHub main); `subagents --help` rc 0; subagents-mcp exists; USER directories and conda unchanged |
| GR | G runs it at its end; Main may rerun it alone to re-judge an ended record | none | no | The record's product = TARGET and its wheel = v0.10.0; temp outside the Harness; clean launch environment; graftling 0.10.0 in the test interpreter; no new failure. Known ids: those named in Task 516's CURRENT definition (read through 516's task.yml) and `tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]` (611: fails on base too). **Any other id, and any ABNORMAL or timed-out shard, is NEW.** |
| SR, suite-base | Main, only if G/GR names NEW ids | none | no | SR prints the suite-base command. suite-base reruns the ids on production now (1fdbbca5 + 600's 0.9.1 wheel: base) and on G's venv (candidate). It runs in its own process to the end; its last lines are `RESULT 612 suite-base: PASS\|FAIL` and the next command. |
| V | Main (scratch only) | none | no | Scratch venv (both new wheels + production's click, yaml and websockets): pip check; one graftling 0.10.0; bin. **The hook copy regenerated by the product is byte-identical to production's**; on a difference V STOPs and hands the diff to the Leader. graphtraj-mcp tools/list is exactly subagents and tasks. **mcp612.py:** tasks discover lists `runtime_connections`; its describe schema has `provider` and the action `discover`, and P's arguments fit it; subagents `models` answers an error. REPORT lines record whether subagents discover lists `models` and whether the refusal names runtime_connections. Codex hooks entry; the entries' sha256 are saved. |
| Mpre | Main | none | no | GR and V passed; no member Worker or swarm batch runs. Main then tells the USER to /exit Main and run I. |
| I | USER, in a Terminal after /exit | none (one Enter) | no | members idle; backup COMPLETE (with R's tools); entries unchanged since V; one `pip install --force-reinstall --no-deps --no-index` of both wheels; both direct_urls; installed = wheel for each; 0.9.1 dist-info gone; manuals = the archive's; pip check; bin (this venv's python); one graftling 0.10.0; production graphtraj-mcp tools/list; Codex hooks entry; hook copy and the 3 entries byte-identical to the backup; guard. **A failure after INSTALL-STARTED prints the R command.** |
| claude --continue | USER | none expected. A plugin/hooks trust dialog would be unexpected: Esc and tell Main. | the running Main | |
| M | Main (resumed) | none expected | no | Prints [a] the tool list (only mcp__graphtraj__subagents and tasks) and [b] one subagents status call and one tasks task_graph call. Arguments are inline, never `arguments_file`. |
| Mr | Main, read only | none | no | Main's transcript after I holds subagents and tasks calls without error (rec593.py) |
| N | Main | none expected | yes: Claude login (approved) | Prints the swarm prompt: an advisor member on Task 612 creates the Claude child n612 without tools; the child runs Bash and replies DONE-612; the member retires it. Main saves each notice as ONE line, header and text together. |
| Nr | Main, read only | none | no | 593's nr_read with DONE-612; one completed notice; the member's subagents calls; the swarm result's agent; then the prompt to retire the member |
| P | Main (read only; prints a prompt) | none | no | Reads the user catalog `~/.graphtraj/connections.yml` with production's own graphtraj (`read_catalog`). It prints names only: entries, runtimes, providers, whether each has a base_url, api_key_env names and model counts. It then picks ONE entry and provider: (1) a Claude entry's provider with neither base_url nor api_key_env (Claude login only); otherwise (2) a provider whose api_key_env is exactly OPENCODE_API_KEY or DEEPSEEK_API_KEY. **STOPs if neither exists**: Main asks the user. It records the Agent-record, Session-archive and member-Session counts, and prints ONE prompt: `mcp__graphtraj__tasks` execute `runtime_connections` `{"action":"discover","runtime":…,"provider":…}`, inline; Main saves the raw result to `P.txt`. **The step itself starts no query.** |
| Pr | Main, read only | none | no | The raw result is a runtime_connections document with `discovery` for the chosen entry and provider; `discovery.groups` is `[{provider, models}]` with at least one model, all of the requested provider; every `api_key_env` is a variable NAME; no field holds a credential-like value; the counts of Agent records (`.graphtraj/swarm/control/agents/*.json`), Session archives (`.graphtraj/swarm/sessions/*`) and member Sessions (`.graphtraj/core/runner/sessions/*`) are unchanged since P (no Agent, no child, no turn) |
| done | Main, read only | none | no | Every step's CHECK passed (00 rel B G rp gh C5 GR V Mpre I Mr Nr P-pre Pr); production graphtraj from wheels-78f929ee and graftling 0.10.0 from wheels-0.10.0 |
| R | USER (Main asks first; the USER /exits Main) | none (one Enter) | no | Run from the backup's own copy: `zsh <Harness>/tmp/612/backup/tools/steps.zsh R`. The venv equals the pre-install bytes; hook copy and entries restored; graphtraj from wheels-1fdbbca5 and graftling 0.9.1 again; pip check. |

## Steps that run a suite wait for it (user rule, 2026-11-25)

This follows `docs/agents/roles/team-leader.md`, the paragraph after the Task 516 rule: a step may run its work in parallel shards, but its own process waits for that work and exits only when it has ended. Its last output is the verdict, the counts and the next command. Task 611's suite had finished unnoticed for an hour because its step returned at once.

- **G** therefore has no detached child and no "check later" command. Main starts G as a background command of its Runtime and is told when it exits.
- **suite-base** already ran in its own process; it now also ends with a RESULT line.
- **No step runs the graftling suite.** The release commit's graftling full suite is Engineer evidence (validation.md), not a Main step.

## Why P uses `tasks runtime_connections`, not graftling's `models` (Leader's decision)

- **The definition asks Main to list models grouped by provider through its MCP, once, in production.** graftling 0.10.0's own way is the `subagents` feature `models` (609). But Main's MCP entry is GraphTraj's, and GraphTraj 611 refuses that feature on purpose (`src/graphtraj/interfaces/agents.py:343-347`). graftling's `models` lists graftling's own `config.yml` connections, which GraphTraj does not use. GraphTraj chooses a child by project role and keeps connections in the user catalog.
- **GraphTraj's route is `runtime_connections` with `{action: discover, runtime, provider}`** (611: `configuration/runtime_connections.py`, `runtimes/model_discovery.py`). It passes graftling 0.10.0's `discover_models` `groups` through, so the result lists the models grouped by provider. Discovery is read only and has no review dialog; only `save` is reviewed.
- **Unlike `models`, discovery runs one native catalog query.** For Claude this is `claude --print` with an `initialize` control request, `--tools ''`, no user turn, no inference. So Pr's "started nothing" means: no Agent, no child Session and no member Session. P's counts make that observable.

## Trimmed from adopt-600/604 (and why)

- **S (604):** replaced by G/GR. No full suite has run on TARGET with the 0.10.0 wheel.
- **C601, C601r (604):** that close-out was 604's own scope.
- **scan, Vc, Mp, timers, X, markers.py:** trimmed as in 600 (see `scripts/adopt-600/README.md`). The guard still lists budget timers and never blocks on them or signals them.
- **C5's pinned form:** 605 made the README install without a tag, so C5 runs the tagless command. It then checks that the installed commit is the release commit, which is GitHub main after rp.

## Deviations and notes

- **README's pin example `@v0.9.1` is unchanged.** It names an existing tag, it is only an example, and the tagless command already installs 0.10.0 once main moves. Changing it would be a documentation change beyond the version strings.
- **PUBLIC_API section 7 has no recorded entry for 0.10.0.** The CHANGELOG lead carries the classification, as 0.9.1's did. A section 7 entry would be a documentation change beyond the brief.
- **The desktop workflows' `GRAFTLING_REF: v0.5.2`** was already outside the old range. Moving it also needs a source-path change, since the layout changed at 0.6.3, so it is left as it was (see the TARGET commit message).
- **Product guard:** HEAD contains TARGET and differs from it only under `scripts/adopt-612/`. TARGET's parent is 6c0756c3, and they differ only in `pyproject.toml`. The Worktree is clean apart from `scripts/adopt-612/rehearsal/`. GraphTraj dev is printed as information: Main integrates TARGET after acceptance.

## Rehearsal (`rehearse.zsh`; outputs in `rehearsal/`)

The rehearsal runs against scratch copies under `$TMPDIR/r612`. It only reads real production, `<Harness>/graftling`, the Harness state and this Worktree.

**What it uses:**
- **graftling scratch:** a clone of `<Harness>/graftling` (main = v0.9.1; dev = ddc506b0 in a second worktree). A scratch bare repository with HEAD -> main stands in for GitHub.
- **Fake production (fixture, built by the real product):** a venv of 604's real graphtraj wheel and 600's real graftling 0.9.1 wheel, plus production's click, yaml and websockets. `graphtraj setup` and the product's own `configuration --write` write the entries and the hook copy. Task state: copies of Tasks 612 and 516.
- **Stubs (fixtures):** `claude` (`--version`; `-p` answers READY-612; a stream-json `initialize` answers a model catalog) and `ps`.
- **User catalogs (fixtures):** one with a Claude entry and an OPENCODE_API_KEY entry; one with neither (P's STOP).
- **Fixtures, labelled in the files:** Main's transcript lines (Mr), and Nr's child and member records, notice, reply and swarm result.

**What runs for real:**
- rel, rp and gh as git operations;
- both wheel builds;
- C5's uv install from `git+file://` without a tag;
- **G through `run_test_shards.py`**, with `-k` selecting real tests. They include `test_wheels_have_separate_owners`, a repository-fixture test that checks the built wheel's graftling range against the installed 0.10.0, and 611's discovery tests on graftling 0.10.0;
- GR and SR;
- suite-base on one real id;
- V: the product's regeneration of the hook copy, graphtraj-mcp and mcp612.py;
- I: the backup and the force-reinstall of both wheels;
- P's catalog read;
- R: the restore, from the backup's own copy of steps.zsh.

**Stand-in for Main's MCP call:** P/Pr's discover call is made by the installed candidate's public CLI, `graphtraj connections --action discover --runtime … --provider …`, with the stub claude. It goes through the same `invoke_tool("runtime_connections")` as Main's tasks call. The console labels it.

**Results:**
- **Full run, after G was changed to wait:** `console-setup.txt`, `console-stops.txt`, `console-release.txt` and `console-adopt.txt`.
  - Every step passed except C5: the rehearsal ran as a background job, which could not use the sandbox network for uv's Python download ("tunnel error").
  - done counted 146 CHECK PASS and 1 not passed (that C5 line). Its production line passed, before R.
- **G in `console-release.txt` waits in its own process:**
  - A ps fixture line showed another suite, so G waited (00:47:19).
  - It then started the 6 shards (00:47:21) and waited for them to end (00:47:26, `exit=1`: rehearsal `-k` shards with nothing collected).
  - It then ran GR. Its last lines are `RESULT 612 G/GR: PASS | 9 passed, 3761 deselected | exit: 1 | known non-blocking ids: 0 | NEW ids: 0 | ABNORMAL shards: 0` and the next command.
  - The rehearsal prints the time G's process exited, after the `ended` line.
  - suite-base ends with `RESULT 612 suite-base: PASS`.
- **C5 rerun:** `console-c5-rerun.txt` reruns C5 in the foreground with a fresh uv directory, followed by done.
  - C5 passed, with version 0.10.0 at commit 6f4aeb8f and a uv-managed CPython 3.14.7.
  - done then counted 154 CHECK PASS and 0 not passed across every step's raw file.
  - Its production line fails only because the full run's R had already restored production to 1fdbbca5 + 0.9.1.
- **P's second choice:** `raw-stop/P-choice-key-entry.txt`. With no login-only Claude provider, P picks the OPENCODE_API_KEY entry and never the Claude gateway keyed by another variable.

**Rehearsed STOPs:**
- rel with dev moved;
- rp before rel;
- rp unconfirmed;
- I before V/GR;
- Mpre with a member Worker (fixture ps line);
- I again with a backup present;
- P with no usable catalog entry;
- Pr before P.txt exists.

**Not rehearsed:**
- the real `<Harness>/graftling` and graftling-dev Worktree;
- GitHub: `ls-remote`, the push with the user's credentials, and uv's GitHub fetch;
- the USER-directory and conda snapshots (the sandbox cannot read `$HOME`);
- the real `ps`, so the guard and members_idle ran on fixture listings;
- the real Claude: 00's probe, Main's /exit and `claude --continue`, M, N and the child run, and a real Claude catalog query (stub only);
- Main's MCP `runtime_connections` call itself (the CLI stood in), and the real user catalog `~/.graphtraj/connections.yml`;
- production's real hook copy and entries (the fake production's own, written by the same product).
