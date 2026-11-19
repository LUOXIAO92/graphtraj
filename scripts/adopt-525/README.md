# Task 525 — production adoption of graftling v0.6.1 + GraphTraj dev 8267f9e5

`steps.zsh` installs graftling 0.6.1 and graphtraj into production `<Harness>/.venv-runtime`, which holds 515's
graftling 0.6.0 + 4ad22e90.

- graftling: a wheel built from `git -C <Harness>/graftling archive v0.6.1`. v0.6.1 must be an annotated tag and must
  peel to 483b16a8d6e05b1c866e69439fada8478791f1fb.
- graphtraj: a wheel built from `git archive 8267f9e5`. Its Requires-Dist is `graftling<0.7,>=0.6.0`, and it carries 0
  graftling files.

The scripts are `scripts/adopt-515/` copied and adapted; adopt-515 is unchanged. Every 503/515 protection is kept:

- the isolated real-host project, `/private/tmp/vproject-525`;
- proddiff file by file, and markers checked both ways;
- the backup `<Harness>/tmp/525/backup`, and rollback R from the backup's own tool copy;
- the guard that waits, never signals, and runs again right before pip;
- the Claude Code version recorded at 00;
- no exported key value in raw output;
- timers listed and never signalled.

Run each step as `zsh <Worktree>/scripts/adopt-525/steps.zsh <step>`. Raw output goes to
`.graphtraj/core/state/tasks/525-production-adoption-graftling-0-6-1/adoption/raw-8267f9e5/`. G writes to
`adoption/G-8267f9e5-<time>/`. Every step prints who runs it, its dialog, how to judge it, and the next command.

## What changes in production

| | before (515) | after |
|---|---|---|
| graftling | 0.6.0 (v0.6.0 = a51e100) | 0.6.1 (v0.6.1 = 483b16a8): code change only `graftling/sessions/archive.py` (518, header-only lookup); `__init__.py` and 3 manifests version-only; CHANGELOG |
| graphtraj | 4ad22e90 | 8267f9e5: only `execution/runner_results.py`, `interfaces/tools.py` (521), `execution/runner_status.py` (523) differ |
| plugin, `.mcp.json`, settings, host config | — | unchanged: plugins and `runtimes/claude` have no diff 4ad22e90..8267f9e5, so no plugin trust dialog and no MCP dialog are expected |

## Restart of Main: needed

Main's `mcp__graphtraj__tasks` and `mcp__graphtraj__agents` calls run inside its host process,
`.venv-runtime/bin/python -m graphtraj.runtimes.claude.host serve`. The call path is `main_calls` →
`handle_task` / `handle_request`, at `src/graphtraj/runtimes/claude/host.py:115-138`.

That process imports the changed modules once, at start:

- `host.py:33` imports `runtimes/claude/mcp.py`;
- `mcp.py:20` imports `interfaces/gateway.py`;
- `gateway.py:12` imports `interfaces/tools.py`;
- `tools.py:14` imports `execution/runner_control.py`;
- `runner_control.py:41` imports `execution/runner_status.py`.

`host.py:115` also imports `runner_status`. Python keeps these modules for the life of the process, so the host keeps
4ad22e90's code until Main restarts. A cleanup that Main calls before the restart would still refuse 519 and 520.

The 503 guard also requires Main to be exited during I, because Main's host uses `.venv-runtime`. The user therefore
does `/exit` in Main before I, and after I runs `cd <Harness> && claude --continue`. M then checks three things:

- Main's `mcp__graphtraj__*` tools are present;
- each notice is delivered once;
- `inbox` reports `duplicate ids: 0` for every file.

Mps also shows that the host's start time is later than the install.

## Step order

| Step | Who | Dialog | Time |
|---|---|---|---|
| 00 preflight | Main | none | ~2 min (one `claude -p`, 120 s cap) |
| B two wheels | Main | none | < 2 min |
| G full suite (6 shards, background) | Main | none | starts at once; ~25 min |
| V pre-install checks | Main | none | ~2 min |
| GR classify G's failures (after G ends) | Main | none | < 10 s |
| Vu (only if Vc asks) | **USER** (Terminal) | one: folder trust for `/private/tmp/vproject-525` → **Yes, proceed**; then `/exit` | < 1 min |
| Vc isolated real-host probe | Main | none | ~2 min |
| Mpre (prints GR state) | Main | none | < 1 min |
| `/exit` Main | **USER** | — | — |
| I backup + install + `configuration --write` | **USER** (Terminal) | none | ~3 min + waiting for members (Ctrl-C safe) |
| `cd <Harness> && claude --continue` | **USER** | none expected | — |
| M (prompts), Mp, Mps, inbox | Main | none | < 3 min |
| D 523 diagnosis with the installed code | Main | none | < 30 s |
| C 523's public cleanup of 519 and 520; Cc checks | Main | at most the Runtime's tool approval (allow once) | < 2 min |
| Nw (background sampler), N (one dispatched advisor member creates `n525`), Nr, Nt | Main | none | ~5 min |
| done | Main | none | < 1 min |
| T (after the Leader accepts 525) | Main | none | < 30 s |
| R rollback (only if needed) | **USER** | none | ~3 min |

## Steps

- **G and GR**: the GraphTraj suite runs at the Worktree checkout, editable. Before it starts, G checks
  `git diff 8267f9e5 HEAD -- src tests plugins` is empty. The graftling it uses is B's wheel, built from the v0.6.1
  archive. G runs `scripts/run_test_shards.py --shards 6 --timeout 1500` in the background.
- **G's temp root**: every run gets a new `TMPDIR` root `${TMPDIR:-/tmp}/verify-525-G-<time>`, as in verify-521. G
  stops if that root is inside the Harness or has a Harness marker above it. Earlier roots are listed and kept.
  `VERIFY525_TESTS=<files>` runs plain pytest on those files through the same entry, venv, temp root and exit file.
  Only rehearsal uses it.
- **GR**: prints each FAILED/ERROR line as either `known (<source>)` or `NEW`. The sources are:
  - Task 516's list: its ids, the two whole files, and the clock step-back message;
  - 523 F, `realhost/F-20261118T231935/pytest.txt`, which lists 2;
  - 521 F, `realhost/F-summary.txt`, which lists 1;
  - 518 G, `realhost/G-a9a54bba-gl-ed19e48-015240`, which lists 0.

  `CHECK 525 G no NEW failure` must be PASS before I.
- **V**:
  - candidate plugin bytes equal production's (CHECK);
  - graftling wheel = v0.6.1 archive, and against production only `graftling/sessions/archive.py` differs in code (`graftcode.py`);
  - the graphtraj wheel differs from production in exactly the three 521/523 files (`gtdiff525.py`);
  - markers for 518, 521, 523 and 0.6.1 are present in the candidate and absent in production (`markers.py`, 8/8);
  - layout, node resolution, plugin validate, entry prediction and readcheck are as in 515.
- **I**:
  - installed graftling is 0.6.1;
  - 518, 521 and 523 are found by name in the installed code;
  - `direct_url.json` of both distributions names the `wheels-8267f9e5` wheels, and the output prints that they were
    built from `git archive 8267f9e5` and `v0.6.1 483b16a8`;
  - markers 8/8;
  - `.mcp.json` server keys are only `graphtraj`;
  - plugin and entry files are unchanged.
- **R**: restores the venv, plugin and entry files from the backup. It also lists `graftling/sessions` differences;
  only `archive.py` is expected, because 518 changes how headers are read, not the archive format.
- **D and C**: D runs `scripts/verify-523/diag523.py` on the installed site-packages, read only. Both 519 and 520 must
  show not busy. C prints `scripts/verify-523/steps.zsh C`, the two public cleanup calls. Main saves each raw result to
  `C-519.txt` and `C-520.txt`. Cc then requires `cleanup_status` cleaned and the Worktree gone, and lists the branch
  and the kept standby sessions.
- **Nw, N, Nr and Nt**:
  - Nw starts `cpu468.py sample … advisor`. It ignores Workers already running when it starts (this Task's Leader and
    Engineer) and samples only an advisor Worker of Task 525.
  - N dispatches one `opus_coding_team.advisor` member. The member creates the claude child `n525` through
    `mcp__graphtraj__agents`, waits for it, reads its status and retires it.
  - Nr prints `REPORT 525 468 Worker CPU 30 s before/after child creation`, which is not blocking, beside 515's
    0.626/0.969. It also prints the 455, 452 and 477 checks from 515's `nr_read`, `CHECK 525 Main got exactly one
    completed notice of the member`, and the member's tool calls by name.
  - Nt and T are as in 515.

Dropped from 515: S (reused suite), Rs/Rsr (resume under the old server name) and N484. Labels printed by helpers
kept from 515 (`CHECK 515 .mcp.json …`, `CHECK 515 init …`, `rec515.py`) check the same things for 525.

## Rehearsal

`zsh scripts/adopt-525/rehearse.zsh` → `rehearsal-output.txt`: 57 checks, all PASS. It starts from an empty base under
`$TMPDIR/adopt525-rehearsal`, with a fake production of graphtraj 4ad22e90 and graftling from the real v0.6.0. The
`claude` and `ps` commands are stubs. B reads the real annotated v0.6.1 of `<Harness>/graftling`, read only. The
negative cases are:

- a wrong commit;
- the 0.6.0 tag (version STOP);
- `main`, which peels to the commit but is not an annotated tag;
- a wheel file that differs from the archive;
- a second CODE difference;
- an unexpected graphtraj file;
- markers both ways;
- a GR list with known and NEW failures;
- Cc with no results, and with one result not cleaned.

`rehearsal-G.txt`: G through the same entry with `VERIFY525_TESTS=tests/test_agent_runner_cleanup.py`. These are real
tests that use the repository conftest fixtures (not `--collect-only`), with the real v0.6.1 wheel: 29 passed, 2
skipped, exit=0. GR on that run passes.

`graftling-0.6.1.patch`: the phase-A commit 483b16a8 as `git format-patch`.
