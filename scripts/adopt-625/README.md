# Task 625: release graftling 0.10.2 and adopt it into production; GraphTraj stays 4ef36426

User decision (Worldline): 20261125T154402.789038+0900, "发布 0.10.2 并换到生产". This decision covers the release (graftling dev and main, the tag, the push) and the production adoption. There is no PyPI release.

**What 0.10.2 is.** graftling dev `6166718` is the only commit since v0.10.1. It is 619:
- `import graftling` works on Windows: the Session archive now uses graftling's shared lock `locks.exclusive` instead of `import fcntl`;
- on Windows, process listing raises a clear `OSError`, and `CodexHost.run` refuses with the existing code `authority-denied`. Both used to fail at import;
- on POSIX, `exclusive` takes the same `flock` on the same lock file, so behaviour is unchanged.

**Compatible by PUBLIC_API section 7.** No command, flag, feature, argument, result field, error code, config field, entry point or public name changes. Nothing that used to succeed is refused. So the version is 0.10.2. The Engineer checked this independently and agrees with the Leader.

**Release commit** `57bca73657d3135a4504904fcc3f1898c2419766` "graftling 0.10.2 (625)":
- one commit on `6166718`, made in a sandbox clone;
- author and committer `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`;
- exactly 5 files: `src/graftling/__init__.py`, `src/graftling/claude-plugin/.claude-plugin/plugin.json`, `src/graftling/dsh/package.json` and `src/graftling/pi/package.json` (0.10.1 → 0.10.2), plus `CHANGELOG.md` (`## Unreleased` → `## 0.10.2 (compatible)` with a short compatible lead, as 0.10.1 has);
- no PUBLIC_API change.

It is in `graftling-0.10.2.bundle` (`6166718..agent/625-graftling-0.10.2`; sha256 `3253fbfabea6775caa7293bdf3d3347b883cdb52bf7bbefc1ba67b625f5ea9a8`). graftling's full suite on the release commit: **926 passed, 21 skipped, exit 0** (`rehearsal/graftling-full-suite.txt`). There is no failure at all, so no comparison with GBASE was needed.

**What changes in production.** Today `.venv-runtime` has:
- graphtraj 0.1.0 from 616's `wheels-4ef36426`;
- graftling 0.10.1 from 617's `wheels-0.10.1`.

**I installs ONLY the graftling 0.10.2 wheel**, built from git archive v0.10.2, with `pip install --force-reinstall --no-deps --no-index`. graphtraj is not reinstalled. I checks that graphtraj's package and dist-info equal the backup's and that its direct_url is still 616's wheel.

graftling's `claude/plugin.py` and `host_context.mjs` are unchanged since v0.10.1, so the hook copy stays byte-identical. V proves this through the product and STOPs on any difference.

**GraphTraj.** This Worktree is GraphTraj dev `4b71012c` plus `scripts/adopt-625/` only. Its product (`src desktop/src pyproject.toml manuals skills plugins`) equals production's `4ef36426`. Since then only tests, workflows and `.gitignore` changed (618, 620, 622, 619). G runs these newer tests against production's product with the 0.10.2 wheel.

**No 0.10.2 observable on macOS.** 619 changes Windows only, so 617's Q/Qr (Main's discover call) are dropped. Instead, the code itself is checked: marker619 looks at `sessions/archive.py` (no `import fcntl`; `from graftling.locks import exclusive, ignore_in_git`; `with exclusive(` twice), the Windows `OSError` line in `member_processes.py`, and the Windows `authority-denied` line in `codex/host.py`. It runs on:
- the wheel (B);
- the test interpreter's graftling (GR);
- the GitHub install (C5);
- the scratch venv (V);
- production after the install (I).

617's `q617.py mcp` (discover `start an agent` = `[create]`) still runs in V and I as a regression check.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| GBASE (graftling dev at dispatch) | `616671870fb2dd9679ea18fdfdbd2f094b1ae0a9` |
| GMAIN0 (graftling main = v0.10.1) | `82e9d12b7c4a76e4074d405fbd135f3c38f1103a` |
| GCOMMIT (release, tag v0.10.2) | `57bca73657d3135a4504904fcc3f1898c2419766`, branch `agent/625-graftling-0.10.2` |
| bundle | `graftling-0.10.2.bundle`, sha256 `3253fbfa…5ea9a8` |
| tag | annotated `v0.10.2`, tagger LUOXIAO92 noreply; message names 619 and compatible |
| TARGET (GraphTraj product, unchanged) | `4ef36426ab6fa5a4769a23557aecf2aa2e2b3759` |
| DEV0 (GraphTraj dev, this Worktree's base) | `4b71012cc36b15063576c86038cf36c383d5989b` |
| graphtraj wheel (reused, never rebuilt) | 616's `wheels-4ef36426` (sha256 `ac805ac9b3fb…`) |
| graftling wheel (B writes it) | `<state>/tasks/625-…/adoption/wheels-0.10.2/` with SHA256SUMS and COMMIT `v0.10.2 57bca736…` |
| R's graftling (production now) | 617's `wheels-0.10.1` (sha256 `764d010b822c…`) |
| G record | `<state>/tasks/625-…/adoption/G-<time>/` (run.txt, suite.txt, shards/*.log with `-rA`) |
| backup | `<Harness>/tmp/625/backup` (venv, hook copy, 3 entries, R's tools incl. a copy of steps.zsh, `main.session`, COMPLETE) |
| kept rollbacks (never written) | `<Harness>/tmp/{600,604,612,616,617}/backup`. 00 reports them; I fingerprints them before and after the install and requires them unchanged. |
| raw output | `<state>/tasks/625-…/realhost/main-raw/` |
| scratch | `<Harness>/tmp/625` (00 creates it), `/private/tmp/uvtool-625` (C5), `/private/tmp/vproject-625` (V, I) |
| child, done word, model | `n625`, `DONE-625`, `claude-opus-5-5` |
| known non-blocking ids | ONLY those in Task 516's CURRENT definition (via 516's task.yml `current_definition`) |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-625/steps.zsh <step>`, in this order:

00 → rel → B → G (background; ends with GR) → rp → gh → C5 → V → Mpre → USER `/exit` + I → USER `claude --continue` → M → Mr → N → Nr → done.

- rp STOPs until G/GR has passed: the definition requires the paired suite before the push.
- V needs only B, so it may run while G runs.
- SR and suite-base run only when GR reports NEW ids.

Each step prints:
- who runs it, the dialog it may raise and whether it needs a login;
- its `CHECK 625 …` lines (the reused helpers print `CHECK 593 …`/`CHECK 503 …` lines, which count the same);
- the exact next command, with real paths, last.

A step's own process waits for all of its work and prints its result last. Every started process gets the allowlist environment (`clean()`: HOME USER PATH TERM TMPDIR LANG). `cred_guard` STOPs if a credential-like name reaches it.

| step | who | dialog | login | what it checks or does |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/625`) | none | yes: one `claude -p` probe (Claude login, approved) | As 617, with these values. Also: production = graphtraj from 616's wheels-4ef36426 + graftling 0.10.1 from **617's wheels-0.10.1** (direct_url); 617's wheel verifies (sha256 `764d010b…`); `tmp/617/backup` and the kept rollbacks are reported; `tmp/625/backup` absent. **Product guard:** HEAD's product = 4ef36426; HEAD differs from 4b71012c only under `scripts/adopt-625/`; the tree is clean apart from `scripts/adopt-625/rehearsal`; range `>=0.10.0,<0.11`. |
| rel | Main | none | no (no network) | As 617. STOPs, changing nothing, if dev ≠ GBASE (or GCOMMIT), main ≠ GMAIN0, or a worktree is dirty. Otherwise it fetches the bundle, fast-forwards dev and main to GCOMMIT and makes the annotated v0.10.2. The message must name 619 and compatible. |
| B | Main | none | no | graftling wheel from git archive v0.10.2: the 4 version strings are 0.10.2; CHANGELOG starts `## 0.10.2 (compatible)` with no `## Unreleased`; METADATA; console scripts; wheel = archive; **619 marker in the wheel**; no build/ or `__pycache__`. 616's graphtraj wheel is reused, verified and compared with archive 4ef36426; its range includes 0.10.2. |
| G (→ GR) | Main starts it as a **Runtime background command**; its own process waits | none | no | The FULL GraphTraj suite through `scripts/run_test_shards.py`, 6 shards, `-rA`. It runs this Worktree's HEAD (editable; product = 4ef36426) with the 0.10.2 wheel. The pytest temp is under `TMPDIR=${TMPDIR:-/tmp}`, outside the Harness, and is printed. It waits behind another running suite. **GR:** the candidate's product = 4ef36426; the wheel is v0.10.2 = GCOMMIT; **the test interpreter imports graftling 0.10.2** (`graftling.__version__` and metadata) **with 619's marker**; the temp is outside the Harness; the launch environment is clean; every FAILED/ERROR id is known by 516's current definition only; no ABNORMAL or timed-out shard. **Last lines:** `RESULT 625 G/GR: PASS\|FAIL \| totals \| known \| NEW \| ABNORMAL \| test interpreter graftling: 0.10.2` and the next command (rp on PASS; SR on FAIL). |
| rp | Main, `ADOPT625_PUSH_CONFIRMED=yes` | none | git credentials (osxkeychain) | STOPs, pushing nothing, unless rel is done, G/GR passed and the push is confirmed. Then an atomic fast-forward push of dev, main and v0.10.2, never forced. |
| gh | Main, read only | none | no | GitHub main = GCOMMIT; v0.10.2^{} = GCOMMIT; the GitHub tag object = the local annotated tag |
| C5 | Main, **FOREGROUND** | none | no (github.com, PyPI, uv Python download) | README's tagless `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git"` in `/private/tmp/uvtool-625` only. Checks: rc 0; version 0.10.2; direct_url commit_id = GCOMMIT; uv-managed base interpreter; `subagents --help` rc 0; subagents-mcp; **619 marker in the installed tool**; USER directories and conda unchanged |
| V | Main (scratch only) | none | no | Scratch venv (616's graphtraj + the 0.10.2 wheel): pip check, one graftling 0.10.2, **619 marker**. **The product's regenerated hook copy is byte-identical to production's**; otherwise STOP and hand the diff to the Leader. graphtraj-mcp tools/list is exactly subagents and tasks, and `agents` is unknown. q617.py mcp. Codex hooks entry. The entries' sha256 are saved. |
| Mpre | Main | none | no | G/GR, V, rp, gh and C5 passed; no member Worker or swarm batch runs. Main then tells the USER to /exit Main and run I. |
| I | USER, in a Terminal after /exit | none (one Enter) | no | Members idle; backup `tmp/625/backup` COMPLETE; entries unchanged since V; ONE force-reinstall of the graftling wheel only. **graphtraj package and dist-info equal the backup's, and its direct_url is still 616's.** graftling direct_url = wheels-0.10.2; **the 0.10.1 dist-info is gone**; installed = wheel; production reports graphtraj 0.1.0 and graftling 0.10.2; **619 marker in production**; manuals; pip check; bin; one graftling; tools/list; q617.py mcp; Codex hooks entry; hook copy and the 3 entries byte-identical to the backup; guard; **the kept rollbacks are fingerprinted before and after and unchanged**. A failure after INSTALL-STARTED prints the R command. |
| claude --continue | USER | none expected. Any dialog: Esc and tell Main. | the running Main | |
| M | Main (resumed) | none expected | no | [a] tool list: only mcp__graphtraj__subagents and tasks; [b] one subagents status and one tasks task_graph, with arguments inline |
| Mr | Main, read only | none | no | Main's transcript after I holds subagents and tasks calls without error (rec593.py); ToolSearch `select:` is INFO |
| N | Main | none expected | yes: Claude login (approved) | swarm prompt: an advisor member on Task 625 creates the Claude child n625 without tools; the child runs Bash and replies DONE-625; the member retires it |
| Nr | Main, read only | none | no | 593's nr_read with DONE-625; one completed notice; the member's subagents calls; the reply quotes claude-opus-5-5; the swarm result's agent; then the prompt to retire the member |
| done | Main, read only | none | no | every CHECK of 00 rel B GR rp gh C5 V Mpre I Mr Nr passed (plus I0 when a run was set aside); production graphtraj from 616's wheels-4ef36426 and graftling 0.10.2 from wheels-0.10.2 |
| R | USER (Main asks first; the USER /exits Main) | none (one Enter) | no | `zsh <Harness>/tmp/625/backup/tools/steps.zsh R`. Restores the venv's pre-install bytes, so graftling is 0.10.1 from 617's wheel again (sha256 checked); restores the hook copy and entries; pip check |
| I0 | Main, before Mpre and a rerun of I | none | no | As 617. It only **moves** (never deletes) a rolled-back backup to `tmp/625/backup-run<N>-<time>` and that run's I/R records to `main-raw/run<N>/`. The kept rollbacks are not touched. |

## Changed from adopt-617, and why

- **Q/Qr and q617.py judge/calls:** dropped. There is no production-visible 0.10.2 observable on macOS. B, GR, C5, V and I check 619's marker in the code instead, and GR requires graftling 0.10.2 in the test interpreter.
- **The start-an-agent requirement in GR:** dropped. That id is ordinary again: its failure would be NEW, because it is not in 516.
- **Product guard:** HEAD now carries newer tests and workflows than 4ef36426. So the guard compares only the product paths with 4ef36426, and compares everything else with GraphTraj dev 4b71012c (only `scripts/adopt-625/` may differ).
- **R's and I0's graftling** are 617's wheels-0.10.1, not 612's 0.10.0.
- **Kept rollbacks** (600, 604, 612, 616, 617) are reported and, in I, checked unchanged.

## Rehearsal (`rehearse.zsh release`, then `rehearse.zsh adopt`; outputs in `rehearsal/`)

Everything runs through `zsh steps.zsh <step>` against scratch copies under `$TMPDIR/r625`. Real production, `<Harness>/graftling`, the Harness state and GitHub are only read.

- **Scratch graftling:** a clone of `<Harness>/graftling`. main = v0.10.1 is checked out; dev = 6166718 is in a second worktree. Its origin is a scratch bare repository (main = dev = v0.10.1).
- **Fake production (fixture, built by the real product):**
  - 616's REAL graphtraj wheel and 617's REAL graftling 0.10.1 wheel, copied into the same state paths;
  - production's click, PyYAML and websockets;
  - `graphtraj setup` and `configuration --write`;
  - copies of Tasks 625 and 516;
  - FIXTURE kept rollbacks `tmp/616/backup` and `tmp/617/backup`.
- **Stubs:** `claude` and `ps`.
- **Real:**
  - rel, rp, gh;
  - B, including the 619 marker in the wheel;
  - **G through `run_test_shards.py`**. It waited behind a fixture "other suite", ran 6 shards and ended with `RESULT 625 G/GR: PASS | 10 passed, 3767 deselected | … | test interpreter graftling: 0.10.2`. The 10 PASSED lines include the repository-fixture test `test_runtime_distribution.py::test_wheels_have_separate_owners` (the GraphTraj wheel's Requires-Dist against the installed graftling 0.10.2), `test_the_mcp_server_lists_subagents_and_tasks_only`, 615's `test_intent_queries_find_create` (4 queries) and `test_graphtraj_discovery_keeps_its_document` (4 Runtimes);
  - **C5 in the FOREGROUND** from tagless `git+file://`: 0.10.2, commit_id 57bca736, uv-managed CPython 3.14.7, `subagents --help` rc 0, 619 marker;
  - V: the hook copy is byte-identical;
  - I: the force-reinstall of only graftling, with graphtraj unchanged; the kept rollbacks are unchanged;
  - R, from the backup's own copy (graftling 0.10.1 from 617's wheel again);
  - I0 (moves), and I0 again with nothing to set aside.
- **Fixtures (labelled):** Main's transcript lines for Mr; Nr's records, notice, reply and swarm result; the GR NEW-failure record.
- **Rehearsed STOPs:**
  - rel with dev moved: nothing changed;
  - I before V/GR;
  - rp (confirmed) before G/GR passed: nothing pushed;
  - **GR with a NEW failure**: a copy of the record with `test_wheels_have_separate_owners` turned FAILED gives `RESULT 625 G/GR: FAIL | … NEW ids: 1`;
  - rp unconfirmed;
  - Mpre with a member Worker (fixture ps line);
  - I again with a backup present.
- **Results:** `done` reports **154 CHECK PASS, 0 not passed**, and the production line passes.

**Not rehearsed:**
- the real GitHub push, GitHub's tag and the GitHub tagless install;
- the FULL GraphTraj suite (Main's G runs it; the rehearsal ran a `-k` selection);
- real production `.venv-runtime`, its hook copy and entries, and the real kept rollbacks `tmp/600…617/backup`;
- the real `ps`;
- the real Claude: 00's probe, /exit, `claude --continue`, M, N and the child run;
- homesnap (`ADOPT625_NOSNAP`);
- `/private/tmp/uvtool-625` and `/private/tmp/vproject-625` (the rehearsal used `$TMPDIR/r625/…`).
