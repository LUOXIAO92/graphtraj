# Task 653: release graftling 0.11.0 (Windows support) and adopt it with GraphTraj's adoption commit

User decisions (Worldline):
- `20261128T030617.779906+0900`, "发版并采用到生产". It covers the release (graftling dev, main, the tag and their push) and the production adoption. There is no PyPI or npm release.
- `20261127T190418.319112+0900`, the long-term authority to push agent branches and run the Windows workflow. P, W and X rely on it.

## Correction 1 (Main's G/GR: 3 NEW ids, which suite-base classed as candidate-only)

**Cause.** Two GraphTraj **tests** read graftling internals that 0.11.0 moved. Neither is a product incompatibility:
- `tests/test_runtime_connections.py::test_host_operation_os_error_keeps_reply_and_logs_traceback` calls the private `_answer_request`. 636 moved it from `graftling.connection` to `graftling._channel_posix`, with the same signature.
- `tests/test_dsh_runtime.py::test_agents_control_dsh_without_task_or_archive[False/True]` replaces `DshService` with the stand-in `NativePeer`. 0.11.0's `dsh/binding.py` passes `service.tree` to `authenticate_process`; POSIX ignores it. GraphTraj's real `DshService` subclasses graftling's, which sets `tree`, so production is unaffected.

**Fix.** One commit changes only those two test files:
- the first test takes `_answer_request` from `graftling._channel_posix` when that module exists, else from `graftling.connection`, so it works with 0.10.x and 0.11.0;
- `NativePeer` gets `tree = None`.

TARGET stays `afaaca41`: the product and the graphtraj wheel are unchanged. steps.zsh's product guard (00, B, G, V, I) and GR's candidate check now allow HEAD to differ from TARGET under `scripts/adopt-653/` **plus exactly** `tests/test_dsh_runtime.py` and `tests/test_runtime_connections.py` (`TESTFIX`). Any other changed file STOPs; this is rehearsed.

**What Main reruns:** 00, then G in the background (it ends with GR), then the rest of the order from rp on. B and V keep their records: the wheels and the product are unchanged, and the old G record stays as it is (GR judges the newest).

## Correction 2 (Main's real 00 after rel, and the Windows judge after X)

**(1) 00 assumed the pre-rel state.**
- After Main's real `rel`, a rerun of 00 failed exactly 3 checks: dev = 9650361e, main = 57bca736, and v0.11.0 absent.
- 00 now accepts EITHER the **pre-rel** state (dev = GBASE, main = GMAIN0 = v0.10.2, tag absent) OR exactly the **post-rel** state that `rel_verify` establishes: dev = main = GCOMMIT, and v0.11.0 is an annotated tag with the noreply tagger that peels to GCOMMIT and carries rel's message and version (`rel_tag_ok`).
- It prints `graftling release state: pre-rel|post-rel|mixed`. Anything mixed or different FAILs.
- The GitHub-side checks are unchanged, because rp has not run.

**(2) After X, the judge picked the wrong artifact for carried-over jobs.**
- `gh run rerun --failed` re-ran only windows-tests. The attempt-2 jobs API labels all three jobs `run_attempt 2`, but claude-real-entry and dsh-windows-tests keep the `started_at` of attempt 1. So the judge asked for `graftling-claude-real-entry-<sha>-2`, which does not exist.
- The shared judge (P, W, X) now lists the run's artifacts (`actions/runs/<id>/artifacts`), and `evidence653.py` picks each job's evidence:
  - a job that started at or after the attempt's `run_started_at` ran in this attempt and needs **its own** artifact `<prefix><attempt>`;
  - a job that started before it was carried over, and only with conclusion success, takes the artifact of the highest earlier attempt that exists. An earlier result never stands in for a re-run job.
- The same rule covers the windows-tests JUnit artifact. dsh-windows-tests has no artifact and is judged from the jobs API.
- The judge prints `EVIDENCE <job>: ATTEMPT <n> <artifact> | <reason>` per job, and the VERDICT ends `evidence: windows-tests attempt N, claude-real-entry attempt N, dsh-windows-tests attempt N`.
- Downloads go to `junit-a<n>/` and `real-entry-a<n>/` under the run's evidence directory.

Only `scripts/adopt-653/` changes. TARGET, TESTFIX, both wheels, the release commit and the bundle stay.

**What Main reruns:**
1. `zsh <Worktree>/scripts/adopt-653/steps.zsh 00` (once, read only; expected `graftling release state: post-rel` and every CHECK PASS).
2. `zsh <Worktree>/scripts/adopt-653/steps.zsh W 46114515028` (observe and judge attempt 2; no re-run, no push). It writes WIN.ok; the expected verdict names attempt 2 for windows-tests and attempt 1 for claude-real-entry and dsh-windows-tests.
3. After the running G ends with GR PASS: `ADOPT653_PUSH_CONFIRMED=yes zsh … rp`, then gh, C5, Mpre, and so on.

B, V and rel are not rerun.

**Rehearsed** (through `zsh steps.zsh <step>`, from a scratch clone of the Worktree):
- 00 pre-rel PASS (`raw/00-pre-rel.txt`);
- 00 post-rel PASS (`raw/00.txt`);
- 00 mixed (dev = GCOMMIT, main = v0.10.2) FAIL (`raw-stop/00-mixed.txt`);
- W on Main's REAL retained run-46114515028 records, offline: `VERDICT 653 W: PASS`, windows-tests from attempt 2, claude-real-entry and dsh-windows-tests from attempt 1 (`raw-w2/W.txt`). The run object's `run_started_at` (06:21:58Z, just before the a2 jobs' created_at) is a fixture;
- the STOP where claude-real-entry re-ran but its own -2 artifact is missing: FAIL, with no attempt-1 stand-in (`raw-stop/w2-rerun-missing/W.txt`);
- `done` reran.

## What 0.11.0 is

0.11.0 is graftling dev `9650361e` (Tasks 632-652, native Windows support) plus one release commit.

**Classification: compatible by PUBLIC_API section 7.**
- On POSIX only two `authority-denied` messages of the Claude Code host change (652). The code stays the same, and section 1.2 says messages may change.
- On Windows, everything now refused never worked there: a Claude or Pi child, the marketplace plugin, and a Runtime whose Trace link cannot be created. Before 0.11.0, starting or controlling Runtimes was refused there anyway, and so were the Claude, Pi and DSH hosts.
- What failed on Windows before now works: the Codex parent host, `stop_marked_processes` (through the job), and the hosts.
- New: the recorded `runtime_job`. No public name, argument, result field, error code or config field is removed or narrowed.

Section 7 would make this a patch release. The minor version rises because the user decided so on 2026-11-28; the 0.5.2 precedent records a user decision on the version number the same way. GraphTraj's range `<0.11` excludes 0.11.0, so the adoption commit widens it.

**Release commit** `67b0fe9aacc868c9c6b5a2818adc8449514221c4`, "graftling 0.11.0 (653)":
- one commit on `9650361e`, made in a sandbox clone;
- author and committer `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`;
- exactly 6 files:
  - `src/graftling/__init__.py`, `claude-plugin/.claude-plugin/plugin.json`, `dsh/package.json` and `pi/package.json`: 0.10.2 → 0.11.0;
  - `CHANGELOG.md`: `## Unreleased` → `## 0.11.0 (compatible; minor release by the user's decision of 2026-11-28)`, with a lead that replaces "Not yet released …";
  - `PUBLIC_API.md`: a `Recorded classifications` entry for 0.11.0 that gives GraphTraj's range `graftling>=0.10.0,<0.12`.

The commit is in `graftling-0.11.0.bundle` (`9650361e..agent/653-graftling-0.11.0`, sha256 `660b394a384a1e645805bf4bc62f6411abcb46a0eb8ec59049e81ba51bcfb30e`).

graftling's full suite on the release commit: **1012 passed, 49 skipped, exit 0** (`rehearsal/graftling-full-suite.txt`). GBASE had the same counts in Task 652's record, and there is no failure to compare.

**GraphTraj adoption commit (TARGET)** `afaaca41e5c148048e0ce8bb0d1d7c352505a9f3`:
- it is GraphTraj dev `5a17543e` with only `pyproject.toml` changed: `graftling>=0.10.0,<0.11` → `graftling>=0.10.0,<0.12`;
- the lower bound stays, because GraphTraj does not rely on 0.11;
- no other version reference exists in `src`, `tests`, `manuals`, `docs`, `skills`, `plugins` or `README.md`;
- this Worktree's HEAD differs from TARGET only under `scripts/adopt-653/`;
- after the Leader accepts it, TARGET joins GraphTraj dev by the usual integration and push.

## What changes in production

Today `.venv-runtime` has:
- graphtraj 0.1.0 from 616's `wheels-4ef36426` (sha256 `ac805ac9…`);
- graftling 0.10.2 from 625's `wheels-0.10.2` (sha256 `300559ab…`).

**I installs BOTH wheels in ONE** `pip install --force-reinstall --no-deps --no-index`. graphtraj stays at version 0.1.0, hence `--force-reinstall`. The wheels are:
- graftling from git archive v0.11.0;
- graphtraj from git archive TARGET.

GraphTraj's product changes since production's `4ef36426`:
- `src/graphtraj/graph/github_backup.py` and `interfaces/tools.py` (641/642);
- `manuals/task-delivery/references/command-inputs.md`;
- `desktop/src` (626/627).

**The graphtraj wheel ships nothing from `desktop/src`.** Packages come only from `src/graphtraj*`, and the data files are only `manuals/` (B checks this: 0 entries).

**The hook copy changes.** `.claude/skills/graphtraj-claude-host` is written by graftling's `claude/plugin.py` from `claude/host_context.mjs`, with GraphTraj's `runtimes/claude` settings. Between v0.10.2 and v0.11.0, `host_context.mjs` gained 647's `BOOT`/`hostCommand` and 652's `WINDOWS_UNSUPPORTED`/`logUnsupported`/Windows branch. `plugin.py` and GraphTraj's side are unchanged. The expected difference, checked by `plugin653.py`, is:
- `.claude-plugin/plugin.json` and `hooks/hooks.json`: byte-identical;
- `hooks/host_context.mjs`: exactly the template's own change, **3 lines removed and 67 added** (seen in the rehearsal on a copy the real product wrote from 0.10.2);
- `.mcp.json`, `.claude/settings.local.json` and `.graphtraj/claude-host/config.json`: unchanged (V's product prediction shows 3× SAME; I checks the bytes).

The copy is regenerated only through the product:
- in V, by `adopt_plugin.py regen` into a scratch copy;
- in I, by `python -m graphtraj.runtimes.claude.host configuration --write`.

I requires the result to equal V's copy byte for byte. **At `claude --continue` the plugin/hooks trust dialog for graphtraj-claude-host is expected (one), and the USER chooses trust.** Any other dialog: Esc, and tell Main.

## Values (fixed in steps.zsh; paths are derived from the Worktree's location)

| name | value |
|---|---|
| GBASE (graftling dev at dispatch) | `9650361e13d6ef9981c753038469ff3b9e44cfa6` |
| GMAIN0 (graftling main = v0.10.2) | `57bca73657d3135a4504904fcc3f1898c2419766` |
| GCOMMIT (release, tag v0.11.0) | `67b0fe9aacc868c9c6b5a2818adc8449514221c4`, branch `agent/653-graftling-0.11.0` |
| bundle | `graftling-0.11.0.bundle`, sha256 `660b394a…bcfb30e` |
| tag | annotated `v0.11.0`, tagger LUOXIAO92 noreply; message names Windows, compatible and 2026-11-28 |
| TARGET / DEV0 | `afaaca41e5c148048e0ce8bb0d1d7c352505a9f3` / `5a17543e9cdaa927b136a2c14e6b8b82320a873e` |
| wheels (B writes them) | `<state>/tasks/653-…/adoption/wheels-0.11.0/` and `wheels-afaaca41/` with SHA256SUMS and COMMIT |
| R's wheels (production now) | 616's `wheels-4ef36426` (sha256 `ac805ac9…`), 625's `wheels-0.10.2` (sha256 `300559ab…`) |
| backup | `<Harness>/tmp/653/backup` (venv, hook copy, 3 entries, R's tools incl. a copy of steps.zsh and HARNESS/WORKTREE, `main.session`, COMPLETE). It stays until the user releases it. |
| other backups | whatever `<Harness>/tmp/*/backup` exists; none is required. 00 reports them, and I fingerprints them before and after the install and requires them unchanged. |
| raw output | `<state>/tasks/653-…/realhost/main-raw/` (Windows evidence under `windows/run-<id>-a<n>/`) |
| scratch | `<Harness>/tmp/653`, `/private/tmp/uvtool-653` (C5), `/private/tmp/vproject-653` (V, I) |
| child, done word, model | `n653`, `DONE-653`, `claude-opus-5-5` |
| known non-blocking ids | ONLY those in Task 516's CURRENT definition (through 516's task.yml `current_definition`) |
| Windows judgement | `scripts/verify-632/windows-expected.txt` (wincheck.py), 652's `new-tests.txt` and `wincheck652.py` (dsh-windows-tests, claude-real-entry) |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-653/steps.zsh <step>`, in this order:

00 → P → rel → B → G (background; ends with GR) → rp → gh → C5 → V → Mpre → USER `/exit` + I → USER `claude --continue` → M → Mr → N → Nr → done.

- rp STOPs until P/W/X (Windows) and G/GR have passed and `ADOPT653_PUSH_CONFIRMED=yes` is set.
- rel, B and V may run while P or G wait.
- SR and suite-base run only when GR reports NEW ids.

Each step prints the following, with the next command (real paths) last:
- who runs it, the dialog it may raise and whether it needs a login;
- its `CHECK 653 …` lines (the reused helpers print `CHECK 593 …`/`CHECK 503 …` lines, which count the same).

A step's own process waits for all of its work and prints its result last. Every started process gets the allowlist environment (`clean()`: HOME USER PATH TERM TMPDIR LANG). `cred_guard` STOPs if a credential-like name reaches it.

| step | who | dialog | login | what it checks or does |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/653`) | none | one `claude -p` probe (approved Claude login); gh's stored login (status only) | uv `--managed-python`; TMPDIR outside the Harness; `gh auth status`. graftling: dev = GBASE, main = GMAIN0, origin, worktrees clean, v0.11.0 absent, local branch absent or GCOMMIT. GitHub: main = GMAIN0, tag absent, dev an ancestor of GBASE, branch absent or GCOMMIT. Bundle: sha256, verify, head; the release commit read in a scratch bare clone: one commit on GBASE, noreply, exactly the 6 files, CHANGELOG heading, README's tagless install line. windows-expected.txt parses. Production: graphtraj from 616's wheel + graftling 0.10.2 from 625's wheel, and both R wheels verify by sha256; pip check; bin. Backups reported; `tmp/653/backup` absent. Product guard: TARGET = DEV0 + `pyproject.toml`, range `>=0.10.0,<0.12`, HEAD = TARGET + `scripts/adopt-653/` only, tree clean apart from `scripts/adopt-653/rehearsal`. Task ready; hashes of the hook copy and entries; Main's Session id |
| P | Main | none | git credential helper (push); gh's stored login | OUTWARD-FACING (long-term authority). Fetches the release branch from the bundle into `<Harness>/graftling` (only if absent) and pushes it to origin fast-forward only, never forced. Dispatches `windows.yml` on it with `gh workflow run --ref` (also runs claude-real-entry), unless a dispatch run of GCOMMIT exists, which it then observes. Waits in this process (appearance 300 s, completion 6000 s). Judges as 652. **PASS only when the run is on GCOMMIT and** windows-tests matches windows-expected.txt, the 5 node ids of 652's new-tests.txt PASSED, dsh-windows-tests succeeded, and claude-real-entry succeeded with every results.json item PASS. Writes `WIN.txt`/`WIN.ok`. Last line: `VERDICT 653 P`, then the next command |
| W `[run-id]` | Main, observe only | none | gh login | the given run, or the newest dispatch run of GCOMMIT; waits and judges as P |
| X `<run-id>` | Main | none | gh login | `gh run rerun --failed`, only for a completed, failed run of GCOMMIT with a transient runner or download fault, never for a test result; waits and judges as P |
| rel | Main | none | no (no network) | As 625. STOPs, changing nothing, if dev ≠ GBASE (or GCOMMIT), main ≠ GMAIN0, a worktree is dirty, or the local branch is not GCOMMIT. Otherwise it fast-forwards dev and main to GCOMMIT and makes the annotated noreply v0.11.0 |
| B | Main | none | no | **graftling** wheel from git archive v0.11.0: the 4 version strings, the CHANGELOG heading and no Unreleased, the PUBLIC_API classification, METADATA, console scripts, wheel = archive, the 0.11.0 marker, no build/ or `__pycache__`. **graphtraj** wheel from git archive TARGET: wheel = archive, **no desktop/ entries**, data files = manuals, entry points and other Requires-Dist identical to 616's wheel, `graftling<0.12,>=0.10.0` includes 0.11.0 and 0.10.2 but excludes 0.12.0, no build/ |
| G (→ GR) | Main starts it as a **Runtime background command**; its own process waits | none | no | The FULL GraphTraj suite through `scripts/run_test_shards.py`, 6 shards, `-rA`. It runs this Worktree's HEAD (editable; = TARGET outside `scripts/adopt-653/`) with the 0.11.0 wheel. pytest temp under `TMPDIR=${TMPDIR:-/tmp}`, outside the Harness and printed; it waits behind another running suite. **GR** checks: the candidate is TARGET; the wheel is v0.11.0 = GCOMMIT; the test interpreter imports graftling 0.11.0 with its marker; the temp is outside the Harness; the launch environment is clean; every FAILED/ERROR id is known by 516's current definition only; no ABNORMAL or timed-out shard. **Last lines:** `RESULT 653 G/GR: PASS\|FAIL \| totals \| known \| NEW \| ABNORMAL \| test interpreter graftling: 0.11.0` and the next command |
| rp | Main, `ADOPT653_PUSH_CONFIRMED=yes` | none | git credentials (osxkeychain) | STOPs, pushing nothing, unless rel is done, Windows passed, G/GR passed and the push is confirmed. Then an atomic fast-forward push of dev, main and v0.11.0, never forced (GitHub then also runs windows.yml for dev; information only) |
| gh | Main, read only | none | no | GitHub main = dev = GCOMMIT; v0.11.0^{} = GCOMMIT; the GitHub tag object = the local annotated tag |
| C5 | Main, **FOREGROUND** | none | no (github.com, PyPI, uv Python download) | README's tagless `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git"` in `/private/tmp/uvtool-653` only. Checks: rc 0; version 0.11.0; commit_id = GCOMMIT; uv-managed base interpreter; `subagents --help` rc 0; subagents-mcp; the 0.11.0 marker; USER directories and conda unchanged |
| V | Main (scratch only) | none | no | Scratch venv with both new wheels + production's click, PyYAML and websockets: pip check, one graftling 0.11.0, the marker, bin. **The hook copy regenerated by the product differs from production's exactly as predicted** (`plugin653.py`); otherwise STOP. The regenerated SERVER/TOOL/TOOLS/PLUGIN lines. **The product's prediction of the 3 entries is 3× SAME.** graphtraj-mcp tools/list is exactly subagents and tasks; q617.py mcp; the Codex hooks entry; the entries' sha256 are saved. Writes `V-dialog.txt` (trust dialog expected) |
| Mpre | Main | none | no | Windows, G/GR, V, rp, gh and C5 passed; no member Worker or swarm batch runs. Main then tells the USER to `/exit` Main and run I |
| I | **USER**, in a Terminal after `/exit` | none (one Enter) | no | Members idle; backup `tmp/653/backup` COMPLETE (with R's tools); entries unchanged since V. **ONE** force-reinstall of both wheels. Checks after it: both direct_urls are the new wheels; the 0.10.2 dist-info is gone; installed = wheels; manuals; pip check; bin; one graftling; production reports 0.1.0 and 0.11.0; the marker. **`configuration --write`** rc 0; the hook copy = V's copy and changed from the backup exactly as predicted; the 3 entries byte-identical to the backup; tools/list; the Codex hooks entry; guard; other backups unchanged. A failure after INSTALL-STARTED prints the R command |
| `cd <Harness> && claude --continue` | **USER** | **expected: ONE plugin/hooks trust dialog for graphtraj-claude-host → trust.** Any other: Esc, and tell Main | the running Main | |
| M | Main (resumed) | none expected | no | [a] tool list: only mcp__graphtraj__subagents and tasks; [b] one subagents status and one tasks task_graph, arguments inline |
| Mr | Main, read only | none | no | Main's transcript after I holds the subagents and tasks calls without error (rec593.py); ToolSearch `select:` is INFO |
| N | Main | none expected | yes: the approved Claude login | Swarm prompt: an advisor member on Task 653 creates the Claude child n653 without tools; the child runs Bash and replies DONE-653; the member retires it |
| Nr | Main, read only | none | no | 593's nr_read with DONE-653; one completed notice; the member's subagents calls; the reply quotes claude-opus-5-5; the swarm result's agent; then the prompt to retire the member |
| done | Main, read only | none | no | Every CHECK of 00, WIN, rel, B, GR, rp, gh, C5, V, Mpre, I, Mr and Nr passed (plus I0 when a run was set aside); production graphtraj from wheels-afaaca41 and graftling 0.11.0 from wheels-0.11.0 |
| R | **USER** (Main asks first; the USER `/exit`s Main) | none at R (one Enter); at the next `claude --continue` the trust dialog may show again → trust | no | `zsh <Harness>/tmp/653/backup/tools/steps.zsh R`. It restores the venv's pre-install bytes (graphtraj from 616's wheel and graftling 0.10.2 from 625's wheel, sha256 checked in direct_url), the hook copy and the entries; then pip check |
| I0 | Main, before Mpre and a rerun of I | none | no | As 625. It only **moves** a rolled-back backup and that run's I/R records aside; other backups are not touched |

## Changed from adopt-625, and why

- **P/W/X** are new. They push the release branch and dispatch the Windows workflow on it, judged as 652; rp requires that verdict.
- **Both wheels are built and installed**, as 616 did for graphtraj and 625 for graftling. I uses one pip call.
- **The hook copy is regenerated** in I through `configuration --write` (as 593). The expected difference is computed from graftling's own templates (`plugin653.py`), and the trust dialog is expected.
- **The product guard** checks TARGET = DEV0 + `pyproject.toml` with the new range, and HEAD = TARGET + `scripts/adopt-653/`.
- **The marker** checks 0.11.0's code (647's `BOOT`, 652's `WINDOWS_UNSUPPORTED` and unloaded-plugin message, `native_claude`) instead of 619's.
- **Kept rollbacks** are not required. Whatever exists under `<Harness>/tmp/*/backup` is reported and checked unchanged.
- **No user path is written into the script.** The Harness and the Worktree come from the script's location, or, for R, from the HARNESS/WORKTREE files that I writes beside the backup's copy.

## Rehearsal (`rehearse.zsh release`, then `rehearse.zsh adopt`; outputs in `rehearsal/`, user paths replaced by `<HOME>`/`<Harness>`/`<SCRATCH>`)

Everything runs through `zsh steps.zsh <step>` against scratch copies under `$TMPDIR/r653`. Real production, `<Harness>/graftling`, the Harness state and GitHub are only read.

- **Scratch graftling:** a clone with main = v0.10.2 checked out and dev = 9650361e in a second worktree. Its origin is a scratch bare repository.
- **gh stand-in:** it serves **Task 652's retained run 46041409568** (real Windows results of 9650361e, whose tree equals GCOMMIT's apart from the 6 release files) as the dispatch run of GCOMMIT.
- **Fake production**, built by the real product:
  - 616's REAL graphtraj wheel and 625's REAL graftling 0.10.2 wheel;
  - `graphtraj setup`, and `configuration --write` writing the hook copy from 0.10.2.
- **Stubs:** `claude` and `ps`.
- **Real:**
  - P's push to the scratch origin and the real judge: `VERDICT 653 P: PASS`, with 1061 tests (793 passed, 224 POSIX-only skips, 44 environment skips), 5/5 652 tests, dsh-windows-tests, and claude-real-entry with 5 items. W was rehearsed as well;
  - rel, rp and gh;
  - B, including no desktop entries and the range check;
  - **G through `run_test_shards.py`**. It waited behind a fixture "other suite" and ended `RESULT 653 G/GR: PASS | 31 passed, 3750 deselected | … | test interpreter graftling: 0.11.0`. The PASSED lines include the repository-fixture test `test_runtime_distribution.py::test_wheels_have_separate_owners` (TARGET's wheel against the installed 0.11.0), 641's `test_github_backup.py` (21), the intent tests and the MCP tests;
  - **C5** from tagless `git+file://`: 0.11.0, commit_id 67b0fe9a, uv-managed CPython 3.14.7, `subagents --help` rc 0, the marker;
  - **V:** `CHANGED hooks/host_context.mjs: 3 lines removed, 67 added | template: 3 removed, 67 added`, `RESULT plugin653: exactly the template change`, and 3× SAME entries;
  - **I:** one pip call for both wheels; `configuration --write`; the hook copy equals V's; the entries byte-identical; the other backups unchanged;
  - R from the backup's own copy (graftling 0.10.2 and graphtraj from 616's wheel again, sha256 in direct_url);
  - I0 (moves), and I0 again.
- **Rehearsed STOPs:**
  - rel with dev moved (nothing changed);
  - I before V/GR/Windows;
  - rp (confirmed) before Windows and GR passed;
  - rp (confirmed) before GR passed;
  - GR with a NEW failure (`RESULT 653 G/GR: FAIL | … NEW ids: 1`);
  - rp unconfirmed;
  - Mpre with a member Worker;
  - I again with a backup present.
- **Results:** `done` reports **173 CHECK PASS, 0 not passed**, and the production line passes. The only CHECK FAILs in the consoles are those STOP fixtures (GR: 2 lines; Mpre: 1).

**Not rehearsed:**
- the real GitHub push of the branch, the real `gh workflow run` and the real Windows run of GCOMMIT (the judge ran on 652's retained record);
- the real push of dev/main/tag, GitHub's tag and the GitHub tagless install;
- the FULL GraphTraj suite (Main's G runs it; the rehearsal ran a `-k` selection);
- real production `.venv-runtime`, its hook copy and entries, and the real backups under `tmp/`;
- the real `ps`, and the real Claude (00's probe, /exit, `claude --continue` and its trust dialog, M, N and the child run);
- X (a re-run of failed jobs) and suite-base;
- homesnap (`ADOPT653_NOSNAP`);
- `/private/tmp/uvtool-653` and `/private/tmp/vproject-653` (the rehearsal used `$TMPDIR/r653/…`).
