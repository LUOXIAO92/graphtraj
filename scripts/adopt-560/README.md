# Task 560 — graftling 0.6.3 release and production adoption of the paired GraphTraj candidate

Production now: graphtraj a7b20447 (532) + graftling 0.6.2 (528, v0.6.2 = 4a002129), Task state not yet migrated (563).
After 560: graphtraj 8949caff (GraphTraj dev 3b9c2af7 + this Task) + graftling 0.6.3 (v0.6.3 = ef7c37db), Task state
migrated by 563's `graphtraj migrate-task-definitions`.

- **graftling 0.6.3** (`graftling-0.6.3.bundle`, branch `agent/560-graftling-0.6.3` on graftling dev 9f962bc):
  - `10dd56b5` conventional layout: `pyproject.toml`, `README.md`, `CHANGELOG.md`, `PUBLIC_API.md` at the repository
    root, install guides in `docs/install/`; `src/graftling/` keeps code and runtime files. The README and CHANGELOG
    are no longer shipped. `PUBLIC_API.md` and `install/*.md` stay shipped (as links in `src/graftling/` to the root
    files) because GraphTraj's tests read the installed copies (`tests/test_graphtraj_public_agents_api.py`,
    `tests/test_codex_parent_uses_agents.py`).
  - `ef7c37db` `graftling 0.6.3 (560)`: version in `__init__.py`, the Claude plugin manifest, the DSH and Pi
    `package.json`; CHANGELOG heading 0.6.3 (compatible) with 545's, 546's and the layout's entries.
  - From 0.6.3 the wheel builds from the archive ROOT: `pip wheel <git archive v0.6.3>` (no longer `src/graftling`).
- **graphtraj** `8949caff`: `graftling>=0.6.3,<0.7` (pyproject), the README's range and graftling links. GraphTraj dev
  uses 555's names (`ValidationErrors`, `arguments_file`), so 0.6.2 does not satisfy it: B checks
  `Requires-Dist` is satisfied by 0.6.3 and NOT by 0.6.2, and I installs both wheels together.
- **Task state**: I runs 563's migration right after the install, while Main is exited and no member runs.

Run each step as `zsh <Worktree>/scripts/adopt-560/steps.zsh <step>`. Raw output goes to
`.graphtraj/core/state/tasks/560-graftling-0-6-3-release-and-production-adoption/adoption/raw-8949caff/`. Each step
prints who runs it, the single native dialog it may show (or `none`), how to judge it, and the next command.
Copied from `scripts/adopt-532/` (unchanged there) with every 503/515/525/528/532 protection.

## Step order

| Step | Who | Dialog | PASS lines (all must hold) |
|---|---|---|---|
| 00 preflight | Main | none | `answer check (expect clean): OK`; `CHECK 560 Codex answers CODEX-560-OK …: PASS`; `TMPDIR=… (outside the Harness)`; `markers expected absent: PASS (6/6)`; `isolation: OK`; MAIN=<id> |
| rel graftling release | Main | none | `CHECK 560 v0.6.3 peels to ef7c37db…: PASS`; `CHECK 560 graftling dev == main == v0.6.3: PASS`; `CHECK 560 v0.6.3 is annotated with the noreply tagger: PASS` |
| rp push (only after the USER's explicit yes) | Main | none | remote lists dev, main and v0.6.3 at ef7c37db |
| integrate this Task's branch into GraphTraj dev | Main | — | (B checks it) |
| B wheels | Main | none | `CHECK 560 GraphTraj dev product = candidate 8949caff: PASS`; `RESULT 560 layout: PASS` (5 layout CHECKs); both Requires-Dist CHECKs; both `… wheel equals git archive …: PASS`; `markers expected present: PASS (6/6)`; `leaked: 0` |
| GR full suite (read only) | Main | none | `CHECK 560 G record (… + v0.6.3) no new failure: PASS`; `CHECK 560 GR (guard + G record): PASS` |
| G (only if the Leader asks for a rerun) | Main | none | background; then `ADOPT560_GREC=<dir> … GR` |
| V pre-install | Main | none | `CHECK 560 candidate plugin changes only hooks/host_context.mjs (533): PASS`; MCP tools/list and two Codex hooks CHECKs; 563 demo: `CHECK 560 563 second run renames nothing: PASS`, `RESULT: PASS`, `CHECK 560 563 migration: … hash-equal: PASS`; markers both ways |
| Vu (only if Vc asks) | **USER** | folder trust for `/private/tmp/vproject-560` → Yes, proceed | — |
| Vc isolated real host | Main | none | as 532 |
| Mpre | Main | none | `GR: PASS …` |
| `/exit` Main | **USER** | — | — |
| I backup + pair install + configuration --write + real entries + migration | **USER** (Terminal) | none | see I's success line; ends with `CHECK 560 backup state copy equals the state just before the migration: PASS` |
| `cd <Harness> && claude --continue` | **USER** | at most ONE: the plugin/hooks trust dialog of graphtraj-claude-host (hooks/host_context.mjs changed, 533) → trust | — |
| M, Mp, Mps, inbox | Main | none | M[b] also reads task_graph (migrated state) |
| Nw, N, Nr, Nt | Main | none | as 532 (one advisor member creates `n560`) |
| done | Main | none | both versions and direct_urls; `graftling 0.6.2 dist-info left: 0`; `Task state now: task.md 0`; real entries PASS |
| T (after the Leader accepts 560) | Main | none | as 532 |
| Im (only if I stopped before the migration) | **USER** | none | as I's migration lines |
| R rollback | **USER** | none (at resume the old plugin may bring the trust dialog once more) | venv and plugin SAME; `CHECK 560 graftling restored …: PASS`; `CHECK 560 graphtraj restored …: PASS`; `CHECK 560 Task state after R equals the pre-migration copy …: PASS` |

## Restart of Main: needed

Main's host keeps the graphtraj and graftling modules it loaded (a7b20447 + 0.6.2). After I the Task state is migrated,
which the old code should not read and the new code requires. So the USER exits Main before I, and resumes with
`claude --continue` only after I has installed both wheels and migrated: no host reads migrated state with old code,
and no new code reads unmigrated state.

## Full suite

The Engineer ran the suite of the candidate with the v0.6.3 wheel; the record is `G-record/` (run.txt with the
candidate, the graftling commit and the test interpreter's click/PyYAML/websockets/pytest versions; suite.txt;
failures.txt with each failed test's assertion lines). GR reads it. The known list is exactly (Leader decision):

- `test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[helper-main]` and
  `[thread-1-main]`: fail at `tests/test_native_gateway.py:88`, the expected MCP `inputSchema` properties lack 555's
  `arguments_file`; recorded by 551 (rounds/3 engineer-engineer_4 3c) on dev 3b9c2af7 + graftling 9f962bc; 551 fixes.
- the same test's `[helper-independent]` and `[thread-1-independent]`: recorded by 556's G (known on base B); 551
  owns the test. The observed line is printed; the cause is an inference.
- `test_child_env_own_key.py::test_a_model_cannot_ask_for_a_key`: recorded by 556's G (known on base B); no fixing
  Task named. The observed line is printed; the cause is an inference.

A test named in 516's CURRENT definition (read through its task.yml) is listed as `known flaky (516)` and does not
block. Everything else is NEW and blocks. The test interpreter uses production's click 8.5.0, PyYAML 6.0.3 and
websockets 16.1.1 (copied read only from `.venv-runtime`), so 564's click-8.2.1 failure counts as NEW.

## Helpers

`markers.py` (560 markers), `wheelcmp560.py` (layout proof), `mcp560.py` (MCP tools/list over stdio),
`fails560.py` (failure blocks), `gr560.py` (known/NEW), `defs563.py` (from verify-563: per-Task hashes); the rest as
in 532. `proddiff.py` fixes the inherited leftover-dist-info check (it split at `dist-info` and never matched).

## Rehearsal

`zsh scripts/adopt-560/rehearse.zsh` writes its checks to stdout (kept in `rehearsal-output.txt`). Fake production
under `$TMPDIR`, a scratch graftling clone for rel, a scratch GraphTraj clone whose dev holds the candidate, stub
`claude`/`codex`/`ps`; the MCP server and the Codex hooks entry are real. Negatives: B before rel, dev moved, a wrong
existing v0.6.3, a tag peeling elsewhere, a wrong target commit, dev without the candidate, an uncommitted src change,
GR with an unknown failure / a known test failing elsewhere / another graftling commit / Miniconda's click / a nonzero
exit, a tampered definition (hash compare FAIL), graftling 0.6.2's dist-info left (proddiff LEFTOVER), markers both
ways, a member Worker under the venv (guard BLOCKING, no backup), I without GR PASS; then R restores both packages and
the pre-migration Task state, and the old code reads it.
