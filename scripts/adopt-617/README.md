# Task 617: release graftling 0.10.1 and adopt it into production; GraphTraj stays 4ef36426

User decision (Worldline): 20261125T120212.212097+0900, "发布 0.10.1 并换到生产". This decision covers the release (graftling dev and main, the tag, the push) and the production adoption. There is no PyPI release.

**What 0.10.1 is.** graftling dev `3a35334e` contains two commits since v0.10.0. 2fdc0d3 adds the PUBLIC_API section 7 note that records 0.10.0's classification. 3a35334 is 615: the `models` description now ends "read only." instead of "read only, starts no Agent.", so `discover` with an intent query such as `start an agent` lists only `create` again. **Compatible by PUBLIC_API section 7:** no feature, argument, result field, error code, name or result shape changes, and the fix makes `discover` behave as documented (section 7's last compatible kind). A description's text is not among the names, fields or codes that section 7 lists as incompatible to change. So the version is 0.10.1.

**Release commit** `82e9d12b7c4a76e4074d405fbd135f3c38f1103a` "graftling 0.10.1 (617)":
- one commit on `3a35334e`, made in a sandbox clone;
- author and committer `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`;
- exactly 5 files: `src/graftling/__init__.py`, `src/graftling/claude-plugin/.claude-plugin/plugin.json`, `src/graftling/dsh/package.json`, `src/graftling/pi/package.json` (0.10.0 → 0.10.1), and `CHANGELOG.md` (`## Unreleased` → `## 0.10.1 (compatible)` with a short compatible lead, as 0.9.1 has);
- no PUBLIC_API change.

It is in `graftling-0.10.1.bundle` (`3a35334e..agent/617-graftling-0.10.1`; sha256 `73465bb69a725603e64015c32d8b2e1132cc144bdb5bd10ec541ac0c2c0b85a8`). Other `0.10.0` strings in the tree are historical text only: CHANGELOG's `## 0.10.0 (incompatible)` section and the 615 entry, and PUBLIC_API section 7's 0.10.0 classification. They stay.

**What changes in production.** Today `.venv-runtime` has graphtraj 0.1.0 from 616's `wheels-4ef36426` and graftling 0.10.0 from 612's `wheels-0.10.0`. **I installs ONLY the graftling 0.10.1 wheel**, built from git archive v0.10.1, with `pip install --force-reinstall --no-deps --no-index`. graphtraj is not reinstalled. I checks that graphtraj's package and dist-info equal the backup's and that its direct_url is still 616's wheel. GraphTraj's range `graftling>=0.10.0,<0.11` includes 0.10.1. graftling's `claude/plugin.py` and `host_context.mjs` are unchanged since v0.10.0, so the hook copy stays byte-identical. V proves this through the product and STOPs on any difference.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| GBASE (graftling dev at dispatch) | `3a35334e977d5a9536a42d320e2a3243d3989f6d` |
| GMAIN0 (graftling main = v0.10.0) | `6f4aeb8fe9f47b71d81b9771486167b123308066` |
| GCOMMIT (release, tag v0.10.1) | `82e9d12b7c4a76e4074d405fbd135f3c38f1103a`, branch `agent/617-graftling-0.10.1` |
| bundle | `graftling-0.10.1.bundle`, sha256 `73465bb6…0b85a8` |
| tag | annotated `v0.10.1`, tagger LUOXIAO92 noreply; message names 615 and compatible |
| TARGET (GraphTraj, unchanged) | `4ef36426ab6fa5a4769a23557aecf2aa2e2b3759`: production's graphtraj and this Worktree's product |
| graphtraj wheel (reused, never rebuilt) | 616's `wheels-4ef36426` (sha256 `ac805ac9b3fb…`) |
| graftling wheel (B writes it) | `<state>/tasks/617-…/adoption/wheels-0.10.1/` with SHA256SUMS and COMMIT `v0.10.1 82e9d12b…` |
| R's graftling | 612's `wheels-0.10.0` (sha256 `6ae3e26e…`) |
| G record | `<state>/tasks/617-…/adoption/G-<time>/` (run.txt, suite.txt, shards/*.log with `-rA`) |
| backup | `<Harness>/tmp/617/backup` (venv, hook copy, 3 entries, R's tools incl. a copy of steps.zsh, `main.session`, COMPLETE). `tmp/616/backup` stays untouched as the older rollback. |
| raw output | `<state>/tasks/617-…/realhost/main-raw/` |
| scratch | `<Harness>/tmp/617` (00 creates it), `/private/tmp/uvtool-617` (C5), `/private/tmp/vproject-617` (V, I) |
| child, done word, model | `n617`, `DONE-617`, `claude-opus-5-5` |
| known non-blocking ids | ONLY those in Task 516's CURRENT definition (via 516's task.yml `current_definition`). `test_intent_queries_find_create[start an agent]` is **no longer known**: it must RUN and PASS. |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-617/steps.zsh <step>`, in this order:

00 → rel → B → G (background; ends with GR) → rp → gh → C5 → V → Mpre → USER `/exit` + I → USER `claude --continue` → M → Mr → N → Nr → Q → Qr → done.

- rp STOPs until G/GR has passed: the definition requires the paired suite before the push.
- V needs only B, so it may run while G runs.
- SR and suite-base run only when GR reports NEW ids.

Each step prints:
- who runs it, the dialog it may raise and whether it needs a login;
- its `CHECK 617 …` lines;
- the exact next command, with real paths.

A step's own process waits for all of its work and prints its result last. G waits for its shards in its own process; its last lines are the RESULT line and the next command. Every started process gets the allowlist environment (`clean()`: HOME USER PATH TERM TMPDIR LANG). `cred_guard` STOPs if a credential-like name reaches it.

| step | who | dialog | login | PASS lines (`CHECK 617 <step> …: PASS`) |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/617`) | none | yes: one `claude -p` probe (Claude login, approved) | zsh; uv lists `--managed-python`; TMPDIR outside the Harness; `/private/tmp/uvtool-617` absent; graftling dev = GBASE and main = GMAIN0, checked out in `graftling-dev` and `<Harness>/graftling`, both clean; v0.10.1 absent locally and on GitHub; GitHub main = GMAIN0; GitHub dev is GBASE or its ancestor; bundle sha256, verify and head; GCOMMIT is one noreply commit of the 5 files; README's tagless install line at GCOMMIT = C5's command; production = graphtraj from 616's wheels-4ef36426 + graftling 0.10.0 from 612's wheels-0.10.0 (direct_url); pip check; bin; `tmp/616/backup` COMPLETE (information); `tmp/617/backup` absent; product guard (HEAD's product = 4ef36426, HEAD differs only under `scripts/`, clean apart from `scripts/adopt-617/rehearsal`, range `>=0.10.0,<0.11`); Task 617 ready; the probe's init shows claude-opus-5-5 and `apiKeySource none` and the answer READY-617; Main's Session id saved |
| rel | Main | none | no (no network) | STOPs, changing nothing, if dev ≠ GBASE (or GCOMMIT) or main ≠ GMAIN0, or a worktree is dirty. Otherwise it fetches the bundle and fast-forwards dev and main to GCOMMIT. Checks: annotated v0.10.1 with the noreply tagger peels to GCOMMIT; main == dev == GCOMMIT; the message names 615 and compatible; `__version__` 0.10.1. A rerun says "already released" and re-verifies. |
| B | Main | none | no | **graftling** (wheel from git archive v0.10.1): the 4 version strings are 0.10.1; CHANGELOG's first heading is `## 0.10.1 (compatible)` and there is no `## Unreleased`; METADATA reports 0.10.1; console scripts are exactly subagents and subagents-mcp; wheel = archive; the 615 marker (`'read only.'` x1, `starts no Agent` x0); no build/ or `__pycache__`; SHA256SUMS and COMMIT. **graphtraj (reused):** 616's wheel verifies, sha256 `ac805ac9…`, COMMIT = TARGET, wheel = git archive TARGET; its graftling range includes 0.10.1 and excludes 0.11.0 |
| G (→ GR) | Main starts it as a **Runtime background command**; its own process waits | none | no | The full GraphTraj suite through `scripts/run_test_shards.py`, 6 shards, `-rA`. It runs this Worktree's HEAD (editable; product = 4ef36426) with the 0.10.1 wheel and production's click, PyYAML and websockets. The pytest temp is under TMPDIR, outside the Harness. It waits behind another running suite. **GR:** candidate product = 4ef36426; wheel = v0.10.1 GCOMMIT; graftling 0.10.1 in the test interpreter; temp outside the Harness; clean launch environment; every FAILED/ERROR id is known by 516's current definition only; no ABNORMAL or timed-out shard; **`test_intent_queries_find_create[start an agent]` RAN and PASSED**, read from its own `PASSED …` line in the shard logs, not from its absence among failures. **Last lines:** `RESULT 617 G/GR: PASS\|FAIL \| totals \| known \| NEW \| ABNORMAL \| start-an-agent: PASSED\|FAILED\|NOT-RUN` and the next command: rp on PASS; on FAIL, SR, then `suite-base <ids>` as in 612 (base = the same product + 612's 0.10.0 wheel) |
| rp | Main, `ADOPT617_PUSH_CONFIRMED=yes` | none | git credentials (osxkeychain) | STOPs, pushing nothing, unless rel is done, G/GR passed (`GR.ok` and the `RESULT … PASS` line) and the push is confirmed. Then an atomic fast-forward push of dev, main and v0.10.1, never forced. Checks: remote main == v0.10.1^{} == GCOMMIT; remote dev == local dev |
| gh | Main, read only | none | no | GitHub main = GCOMMIT; v0.10.1^{} = GCOMMIT; the GitHub tag object = the local annotated tag |
| C5 | Main, **FOREGROUND** | none | no (github.com, PyPI, uv Python download) | README's tagless `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git"` in `/private/tmp/uvtool-617` only: rc 0; tool dir; version 0.10.1 (`__version__` and metadata); `sys.prefix`; uv-managed base interpreter; direct_url commit_id = GCOMMIT; `subagents --help` rc 0; subagents-mcp exists; USER directories and conda unchanged (homesnap593, where readable) |
| V | Main (scratch only) | none | no | Scratch venv (616's graphtraj wheel + the 0.10.1 wheel + production's click, yaml and websockets): pip check; exactly one graftling 0.10.1 (onegraft.py); bin. **The hook copy regenerated by the product is byte-identical to production's**; otherwise STOP and hand the diff to the Leader. graphtraj-mcp tools/list is exactly subagents and tasks, and `agents` is unknown. **q617.py mcp:** `discover` query `start an agent` = exactly `[create]`; `list models` still finds models. Codex hooks entry; the entries' sha256 are saved. |
| Mpre | Main | none | no | G/GR, V, rp, gh and C5 passed; no member Worker or swarm batch runs. Main then tells the USER to /exit Main and run I. |
| I | USER, in a Terminal after /exit | none (one Enter) | no | members idle; backup COMPLETE (with R's tools and main.session); entries unchanged since V; ONE `pip install --force-reinstall --no-deps --no-index` of the graftling wheel only. **graphtraj package and dist-info equal the backup's (pkgdiff532 tree vs tree), and graphtraj's direct_url is still 616's wheels-4ef36426.** graftling direct_url = wheels-0.10.1; installed graftling = wheel; the 0.10.0 dist-info is gone; manuals = archive 4ef36426's (only `.claude/.cc-writes` tolerated, as in 612); pip check; bin; one graftling 0.10.1; production graphtraj-mcp tools/list and discover `start an agent` = `[create]`; Codex hooks entry; hook copy and the 3 entries byte-identical to the backup; guard. **A failure after INSTALL-STARTED prints the R command.** `tmp/616/backup` untouched. |
| claude --continue | USER | none expected. Any dialog: Esc and tell Main. | the running Main | |
| M | Main (resumed) | none expected | no | [a] tool list: only mcp__graphtraj__subagents and tasks; [b] one subagents status and one tasks task_graph, with arguments inline. ToolSearch `select:` is allowed. |
| Mr | Main, read only | none | no | Main's transcript after I holds subagents and tasks calls without error (rec593.py). ToolSearch `select:` is shown as INFO (p616.py). |
| N | Main | none expected | yes: Claude login (approved) | swarm prompt: an advisor member on Task 617 creates the Claude child n617 without tools; the child runs Bash and replies DONE-617; the member retires it |
| Nr | Main, read only | none | no | 593's nr_read with DONE-617; one completed notice; the member's subagents calls; the member's reply quotes claude-opus-5-5; the swarm result's agent; then the prompt to retire the member |
| Q | Main, read only (prints ONE prompt) | none | no | I passed; production = graftling 0.10.1 from wheels-0.10.1 + graphtraj from 616's wheels-4ef36426. Q records Q.epoch and prints ONE prompt: `mcp__graphtraj__subagents` with action `discover` and query `start an agent`, inline. Main saves the raw result to `Q.txt`. |
| Qr | Main, read only | none | no | q617.py judge: Q.txt is a JSON or YAML discover document (GraphTraj's MCP text is YAML), not an error, with features **exactly [create]**. q617.py calls: Main's transcript after Q holds that discover call, answered without error, with the same features. ToolSearch `select:` is allowed (INFO). |
| done | Main, read only | none | no | every CHECK of 00 rel B GR rp gh C5 V Mpre I Mr Nr Q-pre Qr passed (plus I0 when a run was set aside); production graphtraj from 616's wheels-4ef36426 and graftling 0.10.1 from wheels-0.10.1 |
| R | USER (Main asks first; the USER /exits Main) | none (one Enter) | no | `zsh <Harness>/tmp/617/backup/tools/steps.zsh R`. The venv equals the pre-install bytes, so graphtraj comes from wheels-4ef36426 and graftling 0.10.0 from 612's wheel; hook copy and entries are restored; pip check |
| I0 | Main, before Mpre and a rerun of I | none | no | As 612/616. It requires COMPLETE + INSTALL-STARTED, R's record all PASS, and production equal to the backup. It then **moves** (never deletes) the backup to `tmp/617/backup-run<N>-<time>` and that run's I/R records to `main-raw/run<N>/` with a SUPERSEDED note. `tmp/616/backup` is not touched. |

## Trimmed from 612/616, and why

- **graphtraj build (612 B) and GR614 (616):** GraphTraj does not change. 616's wheel is reused by sha256 and compared with git archive 4ef36426. G runs a NEW full suite, because the definition requires the paired suite with the 0.10.1 wheel before the push.
- **P/Pr (616's `models` call, p616.py, v616.py bound):** replaced by Q/Qr. 617's observable is the discover intent query: before, it returned create and models (the Leader's baseline on production 0.10.0); after, only create. Discover reads only the feature table: no login, no key, no file, nothing created.
- **KNOWN_EXTRA (611/614's start-an-agent id):** removed. 0.10.1 must make it pass, so GR treats any failure of it as NEW and also requires its own PASSED line.
- **scan, Vc, Mp, timers, X, markers.py:** trimmed as in 600/604/612/616. The guard still lists budget timers and never blocks on them or signals them.

## Rehearsal (`rehearse.zsh release`, then `rehearse.zsh adopt`; outputs in `rehearsal/`)

Everything runs through `zsh steps.zsh <step>` against scratch copies under `$TMPDIR/r617`. Real production, `<Harness>/graftling`, the Harness state and GitHub are only read.

**Scratch graftling:** a clone of `<Harness>/graftling`. main = v0.10.0 is checked out; dev = 3a35334e is in a second worktree. Its origin is a scratch bare repository standing in for GitHub (main = dev = v0.10.0, HEAD → main).

**Fake production (fixture, built by the real product):**
- 616's REAL graphtraj 4ef36426 wheel and 612's REAL graftling 0.10.0 wheel, copied into the same state paths;
- production's click, PyYAML and websockets, read-only copies from `<Harness>/.venv-runtime`;
- `graphtraj setup` and `configuration --write` write the entries and the hook copy;
- Task state: copies of Tasks 617 and 516.

**Stubs (fixtures):** `claude` (`--version`, and `-p` answering a stream-json init with apiKeySource none plus READY-617) and `ps`.

**Real:**
- rel, rp and gh git operations against the scratch clone and origin;
- B's wheel build and every comparison, including 616's real graphtraj wheel against git archive 4ef36426;
- **G through `run_test_shards.py`** with `-k` selecting real tests. It waited in its own process behind a fixture "other suite" line, ran 6 shards and ended with `RESULT 617 G/GR: PASS | 10 passed, 3764 deselected | … | start-an-agent: PASSED`. The 10 PASSED lines: 615's `test_intent_queries_find_create` for all four queries, **including `[start an agent]`**; the repository-fixture test `test_wheels_have_separate_owners` (`built_wheel`: the GraphTraj wheel's Requires-Dist against the installed graftling 0.10.1); `test_the_mcp_server_lists_subagents_and_tasks_only`; and `test_graphtraj_discovery_keeps_its_document[claude,codex,dsh,pi]`;
- **C5 in the FOREGROUND**: tagless `git+file://` origin, graftling 0.10.1, commit_id 82e9d12b, uv-managed CPython 3.14.7, `subagents --help` rc 0;
- V: the product's regeneration of the hook copy (byte-identical), graphtraj-mcp, and q617.py mcp (`start an agent` → `['create']`, `list models` → `['models']`);
- I: the backup, and the force-reinstall of only the graftling wheel, with graphtraj unchanged against the backup;
- R, run from the backup's own copy;
- I0 after R (moves), and I0 again with nothing to set aside.

**Stand-in for Main's MCP call (labelled):** the fake production's own `graphtraj-mcp` after I. It gets `tools/call subagents {action: discover, query: "start an agent"}`, and its text result is Q.txt. That text is **YAML**, which the first adopt run found; q617.py now reads YAML as well as JSON.

**Fixtures (labelled):**
- Main's transcript lines: for Mr, ToolSearch `select:` plus M[b]'s calls; for Qr, ToolSearch plus the discover call carrying Q.txt;
- Nr's child and member records, notice, reply and swarm result.

**Rehearsed STOPs** (`raw-stop/`, console):
- rel with dev moved: nothing changed;
- I before V/GR;
- rp (confirmed) before G/GR passed: nothing pushed;
- GR on a copy of the record whose start-an-agent line is replaced by a FAILED line (fixture): `RESULT 617 G/GR: FAIL | … NEW ids: 1 | start-an-agent: FAILED`;
- rp unconfirmed;
- Mpre with a member Worker (fixture ps line);
- I again with a backup present;
- Qr before Q.txt;
- Qr with a Q.txt listing create and models (fixture, YAML): FAIL.

**Results:**
- `done`: **154 CHECK PASS, 0 not passed**; production line PASS.
- graftling full suite on GCOMMIT: 922 passed, 21 skipped, exit 0 (`rehearsal/graftling-full-suite.txt`).

**Not rehearsed:**
- the real GitHub push, GitHub's tag and the GitHub tagless install (the scratch origin and `git+file://` stood in for them);
- the full GraphTraj suite (only the `-k` selection ran here; Main's G runs the full suite);
- real production `.venv-runtime`, its hook copy and entries;
- `tmp/616/backup`;
- the real `ps`;
- the real Claude: 00's probe, /exit, `claude --continue`, M, N, the child run and Main's real discover call;
- homesnap (`ADOPT617_NOSNAP`);
- `/private/tmp/uvtool-617` and `vproject-617` (the rehearsal used `$TMPDIR/r617/uvtool-617` and `$TMPDIR/r617/vproject`).
