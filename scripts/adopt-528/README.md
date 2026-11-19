# Task 528 — production adoption of graftling v0.6.2 (GraphTraj not reinstalled)

`steps.zsh` installs graftling 0.6.2 into production `<Harness>/.venv-runtime`. Production currently holds 525's
graftling 0.6.1 + graphtraj 8267f9e5.

- graftling: a wheel built from `git -C <Harness>/graftling archive v0.6.2`. v0.6.2 must be an annotated tag peeling
  to 4a002129f8b97f32980afd59e5a1a64c428fe684 (phase A: version and CHANGELOG on dev c7616578 = 0.6.1 + 527 + 526).
- graphtraj: **not reinstalled**. This Worktree differs from 8267f9e5 only in `scripts/`. B and G check that
  `git diff 8267f9e5 HEAD -- src tests plugins` is empty. The production graphtraj requires `graftling<0.7,>=0.6.0`,
  which B checks. B also builds a graphtraj wheel from `git archive 8267f9e5`, used only for the scratch venv of
  V/Vc and for V's file-by-file check that it equals production. It is never installed.

The scripts are `scripts/adopt-525/` copied and adapted; adopt-525 is unchanged. Every 503/515/525 protection is kept:

- the isolated real-host project, `/private/tmp/vproject-528`;
- proddiff file by file, and markers checked both ways;
- the backup `<Harness>/tmp/528/backup`, and rollback R from the backup's own tool copy;
- the guard that waits, never signals, and runs again right before pip;
- the Claude Code version recorded at 00;
- no exported key value in raw output;
- timers listed and never signalled.

`<Harness>/tmp/528` is created by the first step Main or the USER runs; the Engineer's sandbox cannot create it.
Main has already created it empty.

Run each step as `zsh <Worktree>/scripts/adopt-528/steps.zsh <step>`. Raw output goes to
`.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/raw-8267f9e5/`. G writes to
`adoption/G-8267f9e5-<time>/`. Every step prints who runs it, its dialog, how to judge it, and the next command with
real values.

## What changes in production

| | before (525) | after |
|---|---|---|
| graftling | 0.6.1 (v0.6.1 = 483b16a8) | 0.6.2 (v0.6.2 = 4a002129). CODE: 526's `control.py`, `locks.py`, `sessions/archive.py`; 527's `dsh/client.mjs` and `dsh/package.json` (inject list). VERSION: `__init__.py`, `pi/package.json`. DOC: `CHANGELOG.md`, `README.md` |
| graphtraj | 8267f9e5 | unchanged. V: wheel = production; I/done: installed = backup |
| plugin, `.mcp.json`, settings, host config | — | unchanged: V's candidate plugin bytes are SAME, so no plugin trust dialog and no MCP dialog are expected |

graftling's own `claude-plugin/.claude-plugin/plugin.json` version moves 0.6.1 → 0.6.2, as 525 moved it to 0.6.1.
`claude-plugin/` is not in the graftling wheel at all, so it never reaches production. 525's `V-graftcode.txt` lists
VERSION as `__init__.py`, `dsh/package.json` and `pi/package.json`, without it. Production's Claude plugin is
`graphtraj-claude-host`, which `graftling.claude.claude_host_plugin` writes from `graftling/claude/host_context.mjs`
and the hooks; V compares it byte for byte. `__version__` reaches only the MCP `serverInfo` (`graftling/claude/host.py:206,593`,
`claude/execution.py:266`, `mcp.py:342`). Claude Code's trust and MCP approvals key on the plugin files and on the
`.mcp.json` entries, and neither changes, so no dialog is expected from the version change.

## Restart of Main: needed

Main's host process `graphtraj.runtimes.claude.host serve` imports graftling once, at start:

- `graphtraj/runtimes/claude/host.py:25` imports `graftling.claude`, and `:28` imports `graftling`;
- `graftling/__init__.py:47` imports `graftling.control`, and `control.py:70` imports `graftling.locks`;
- `graftling/__init__.py:71` imports `graftling.sessions.archive`, and `archive.py:24` imports `graftling.locks`.

A running host keeps 0.6.1's code, so Main's own records gain 526's `.gitignore` only after the restart. The 503
guard also needs Main exited during I. The user does `/exit` in Main before I, and after I runs
`cd <Harness> && claude --continue`.

## Correction (round 2): 529's test fix, step Gt, GR on G+Gt

Main's G failed one NEW test, `tests/test_pi_generic_execution.py::test_task_free_child_launches_messages_and_continues`.
The test took `native/.gitignore`, which 526 writes, for the agent directory, and it fails about half the runs.
Task 529 fixes only that test. The changes:

- **Guard** (`product_guard`; B, G, Gt, GR, I): the Worktree's `src`/`tests`/`plugins` must equal 8267f9e5, except
  for exactly one file, `tests/test_pi_generic_execution.py`. The guard derives the fix commit
  F = `git log -1 --format=%H 8267f9e5..HEAD -- tests/test_pi_generic_execution.py` and requires all of the following:
  - the name-only diff 8267f9e5..HEAD in src/tests/plugins is exactly that file;
  - F's own diff (first parent) in src/tests/plugins is that file only;
  - `git diff F HEAD -- <file>` is empty.

  It prints F and its subject, and STOPs on anything else. With no difference, the behaviour is as before.
- **Gt** (Main, no dialog): reruns that file through G's machinery:
  - the same guard, B's v0.6.2 wheel and G's venv with the Worktree editable;
  - a new `${TMPDIR:-/tmp}/verify-528-Gt-<time>` root outside the Harness;
  - `VERIFY528_REPEAT` runs (default 10), each with its own `--basetemp` and exit line, in the foreground at about
    5 s per run.

  Gt prints one summary line per run and the `native/` entries of run 1. The output goes to
  `adoption/Gt-8267f9e5-<time>/`, and `adoption/Gt-latest` points at it.
- **GR** judges Main's existing G together with the latest Gt. The G failure in that file counts as
  `fixed (529 <F8>)` only when all of these hold:
  - the latest Gt ran all its repeats (at least 3, each ended);
  - Gt ran for the same F the guard finds now;
  - the test passed (a PASSED line) in every repeat.

  Every other G failure, and every failure inside a Gt run, is classified as before. Example: in a `/tmp`-symlinked
  venv `test_graphtraj_member_launch_matches_base` fails for path reasons and is classified `known (521 F)`.
  GR prints `CHECK 528 G+Gt no NEW failure: PASS|FAIL`. The G-alone CHECK is still printed, for information only.
  Earlier GR.txt files are kept as `GR-<time>.txt`.
- **Mpre** shows the G+Gt CHECK. **I** refuses to run without `CHECK 528 G+Gt no NEW failure: PASS` in GR.txt or
  when the guard STOPs.

Order from here: … GR (old: FAIL, done) → [529 merged into this Worktree] → **Gt** → **GR** → Vc → Mpre → /exit →
I → restart → M … → N … → done → T.

`rehearse-Gt.zsh` → `rehearsal-Gt.txt`. The rehearsal uses a scratch clone of the Worktree, with a stand-in commit
that edits only that test, a copy of Main's real G, and real Gt runs (3 repeats) with the repository fixtures.
Its negatives:

- GR without Gt;
- a forced-fail Gt;
- a 1-repeat Gt;
- an extra src change;
- a fix commit that also touched another file;
- no difference at all.

## Step order

| Step | Who | Dialog | Time |
|---|---|---|---|
| 00 preflight | Main | none | ~2 min (one `claude -p`, 120 s cap) |
| B graftling wheel (+ scratch-only graphtraj wheel) | Main | none | < 2 min |
| G full suite (6 shards, background) | Main | none | starts at once; ~25 min |
| V pre-install checks | Main | none | ~2 min |
| GR classify G's failures (after G ends) | Main | none | < 10 s |
| Vu (only if Vc asks) | **USER** (Terminal) | one: folder trust for `/private/tmp/vproject-528` → **Yes, proceed**; then `/exit` | < 1 min |
| Vc isolated real-host probe (after G ends) | Main | none | ~2 min |
| Mpre (prints GR state) | Main | none | < 1 min |
| `/exit` Main | **USER** | — | — |
| I backup + graftling install + `configuration --write` | **USER** (Terminal) | none | ~3 min + waiting for members (Ctrl-C safe) |
| `cd <Harness> && claude --continue` | **USER** | none expected | — |
| M (prompts), Mp, Mps, inbox | Main | none | < 3 min |
| Nw (background sampler), N (one dispatched advisor member creates `n528`), Nr, Nt | Main | none | ~5 min |
| done | Main | none | < 1 min |
| T (after the Leader accepts 528) | Main | none | < 30 s |
| R rollback (only if needed) | **USER** | none | ~3 min |

## Steps

- **B**:
  - v0.6.2 must be an annotated tag peeling to 4a002129. B prints the tagger and the commit author and committer
    (expected: the noreply LUOXIAO92).
  - The graftling wheel must be version 0.6.2, carry `def ignore_in_git`, and name neither `tool.call.toolview` nor
    `AgentsRow` in `client.mjs`.
  - `wheels-8267f9e5/` holds only that wheel; I installs everything in it. The graphtraj wheel is built into
    `gtwheel-8267f9e5/`.
- **G and GR**:
  - The GraphTraj suite runs at the Worktree checkout (editable) with B's v0.6.2 wheel, as
    `scripts/run_test_shards.py --shards 6 --timeout 1500`, in the background.
  - Every run gets a new `TMPDIR` root `${TMPDIR:-/tmp}/verify-528-G-<time>`, so pytest's basetemp is new as well.
    G prints `TMPDIR of the run is outside the Harness: yes` and stops if the root is inside the Harness or has a
    Harness marker above it.
  - `VERIFY528_TESTS=<files>` runs plain pytest on those files through the same entry. Only rehearsal uses it.
  - GR's known sources are 516, 523 F, 521 F and 518 G, as in 525. **525 G** is new:
    `adoption/G-8267f9e5-20261119T204121` with its 1 failure
    `tests/test_team_replacement.py::test_interrupt_returns_after_slow_terminal_record`. 525's
    `rounds/1/leader.md` classifies that failure known/load; GR prints that this decision is present.
  - `CHECK 528 G no NEW failure` must be PASS before I.
- **V**:
  - candidate plugin bytes equal production's (CHECK);
  - graftling, by `graftcode.py`: the wheel equals the v0.6.2 archive, and against production each class is
    exactly its expected set (CODE, VERSION, DOC above). An unexpected file, or an expected one that does not
    differ, is a STOP;
  - the graphtraj wheel equals production file by file (`gtdiff528.py`);
  - markers (`markers.py`, 8/8): 526's `ignore_in_git` in locks/control/archive; 527's client.mjs without `AgentsRow`
    or the `tool.call.toolview` registration, and package.json without `dsh-client-ui-tool`; version 0.6.2 present,
    0.6.1 gone. They must be present in the candidate and absent in production;
  - layout, node resolution, plugin validate, entry prediction and readcheck are as in 525.
- **I**:
  - `pip install --no-deps --no-index` of the graftling wheel only;
  - proddiff of the installed graftling against the wheel;
  - `CHECK 528 graphtraj unchanged (installed vs backup)`: the graphtraj package and its dist-info, except the files
    pip rewrites;
  - graftling 0.6.2, with 526 and 527 found by name in the installed code;
  - `graftling-0.6.2.dist-info/direct_url.json` names `wheels-8267f9e5/graftling-0.6.2-…whl`, and I prints
    `built from: graftling git archive v0.6.2 4a002129…`;
  - markers 8/8;
  - `.mcp.json` server keys are only `graphtraj`;
  - plugin and entry files are unchanged.
- **M, Mp, Mps, inbox**: as in 525. These cover `mcp__graphtraj__*` present, each notice once, `duplicate ids: 0`,
  and the host started after the install.
- **Nw, N, Nr, Nt**:
  - N dispatches one `opus_coding_team.advisor` member. The member creates the claude child `n528` through
    `mcp__graphtraj__agents`, waits for it, reads its status and retires it.
  - Nr prints `CHECK 528 Main got exactly one completed notice of the member`, plus the 455, 452 and 477 checks and
    the member's tool calls.
  - Nr also prints these non-blocking REPORT lines:
    - the 468 Worker CPU window, beside 525's 0.538/0.112;
    - `REPORT 528 526 .gitignore <root>/<dir>` for `sessions/`, `control/`, `live/` and `native/` under
      `.graphtraj/swarm` and `.graphtraj/core/runner`. `live/` without one is a known 526 leftover.
  - 00 and R print the same REPORT lines.
- **R**: restores the venv, plugin and entry files from the backup. `graftling/sessions` may differ only in
  `archive.py`: 526 adds the `.gitignore` call, and the format is unchanged. The `.gitignore` files 0.6.2 wrote are
  listed and kept.

Dropped from 525: D, C and Cc (523's cleanup check on 519/520). Labels printed by helpers kept from 515/525
(`CHECK 515 .mcp.json …`, `CHECK 515 init …`, `rec515.py`, `REPORT 525 468 …` from `cpu468.py`) check the same
things for 528.

## Rehearsal

`zsh scripts/adopt-528/rehearse.zsh` → `rehearsal-output.txt`.

- It starts from an empty base under `$TMPDIR/adopt528-rehearsal`.
- The fake production is graphtraj 8267f9e5 plus graftling from the real v0.6.1.
- `claude` and `ps` are stubs.
- B reads the real annotated v0.6.2 of `<Harness>/graftling`, read only; no stand-in is used.

The negative cases are:

- a wrong commit;
- the v0.6.1 tag (version STOP);
- the commit id, which peels to the commit but is not an annotated tag;
- a wheel file that differs from the archive;
- an extra CODE difference;
- an expected CODE file that does not differ;
- a differing graphtraj file;
- markers both ways;
- a GR list with known (521 F, 516, 525 G, clock) and NEW failures.

`rehearsal-G.txt`: G through the same entry with `VERIFY528_TESTS=tests/test_agent_runner_cleanup.py`, then GR on
that run. These are real tests that use the repository conftest fixtures (not `--collect-only`), with the real v0.6.2
wheel.

`graftling-0.6.2.patch`: the phase-A commit 4a002129 as `git format-patch`.
