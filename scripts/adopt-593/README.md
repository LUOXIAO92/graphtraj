# Task 593 — graftling 0.9.0 release and production adoption

Production now: graphtraj eb009725 + graftling 0.8.0 (579; v0.8.0 = 542a81df; `.venv-runtime/bin` has `agents` and
`agents-mcp`). After 593: graphtraj 3eb21101 (GraphTraj dev: 588, 592, 595; already `graftling>=0.9.0,<0.10`) +
graftling 0.9.0 (591: MCP tool `agents` → `subagents`, commands `agents`/`agents-mcp` → `subagents`/`subagents-mcp`,
no alias). The user confirmed 0.9.0 (Worldline user-decision 20261124T030013.925262+0900) and pre-approved the push of
graftling main and v0.9.0 and the use of their Claude login (20261124T030105.522331+0900). No Task-state migration.

**Status of this directory (early HEAD):** the steps Main can run now are final: `00`, `scan`, `scanhome`, `rel`, `rp`,
`gh`, `B`, `G`, `GR`, `SR`, `suite-base`. The later steps (`V`, `Vc`, `Mpre`, `I`, `M`, `Mr`, `N`, `Nr`, `X`, `C5`,
`done`, `R`) are still being changed for the new names and are not yet rehearsed; do not run them before the next HEAD.

## The two commits

**graftling 0.9.0** is `7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9` `graftling 0.9.0 (593)`.
- Carried as `graftling-0.9.0.bundle`, branch `agent/593-graftling-0.9.0`, one commit on graftling dev `49f97004`
  (v0.8.0 + 591). Author and committer `LUOXIAO92 <89069722+LUOXIAO92@users.noreply.github.com>`.
- Changes 5 files, shaped like 542a81df: version 0.9.0 in `__init__.py`, the Claude plugin manifest,
  `dsh/package.json` and `pi/package.json`; CHANGELOG `## Unreleased (incompatible; to be released as 0.9.0)` →
  `## 0.9.0 (incompatible)` (its lead already names the one incompatible change). No other `Unreleased` marker exists.
  PUBLIC_API section 7 already records 0.9.0 as incompatible (591) and is unchanged; `src/graftling/PUBLIC_API.md`
  stays the link.
- graftling's full suite on 7b5f4e6 (clean environment, pytest temp under TMPDIR): **876 passed, 21 skipped, 1 failed**.
  The failure, `tests/test_dsh_standalone_child.py::test_dsh_child_launch_needs_no_graphtraj_setting`, is environmental
  (an inference): the checkout path. See the Engineer report.

**graphtraj** is GraphTraj dev `3eb21101` itself: 593 makes no product change. product_guard requires this Worktree's
`src`, `tests`, `plugins` and `pyproject.toml` to equal it, and its pyproject to pin `"graftling>=0.9.0,<0.10"`.
B checks `Requires-Dist` is satisfied by 0.9.0 and NOT by 0.8.0 or 0.10.0.

## Layout

- Run each step as `zsh <Worktree>/scripts/adopt-593/steps.zsh <step>`.
- Raw output: `.graphtraj/core/state/tasks/593-graftling-0-9-0-release-and-production-adoption/adoption/raw-3eb21101/`.
- Backups and scratch: `<Harness>/tmp/593` (Main created it); backup `<Harness>/tmp/593/backup`.
- Isolated real-host project: `/private/tmp/vproject-593`. Requirement 5: `/private/tmp/uvtool-593`.
- 579's backup `<Harness>/tmp/579/backup` is only listed, never touched.

Each step prints who runs it, the single native dialog it may show and the choice (or none), its PASS lines, and the
next command with real values filled in.

## Changed from adopt-579 (release part)

- **Values:** 0.9.0/0.8.0, GOLDCOMMIT 542a81df, GBASE 49f97004, OLD eb009725, TARGET = GTBASE = 3eb21101.
- **rel:** as 579 (bundle fetched by exact SHA, dev fast-forward or a noreply merge that STOPs on conflict, main
  fast-forward, annotated noreply tag). On the real repository dev is checked out in `.graphtraj/core/worktrees/graftling-dev`
  and main in `<Harness>/graftling`; both must be clean.
- **rp:** cites the USER's pre-approval (20261124T030105.522331+0900) instead of "Main asks the USER";
  `ADOPT593_PUSH_CONFIRMED=yes` is still required so that the push never starts by accident.
- **B:** also checks v0.9.0's `[project.scripts]` are `subagents` and `subagents-mcp` and not `agents`/`agents-mcp`;
  markers.py holds 8 markers (0.9.0 version, 591's TOOL_NAME, hook TOOL line, Pi and DSH TOOL, the subagents-mcp entry
  point; 592's Claude host; 588's submit_report).
- **GR/SR:** every `ABNORMAL` line of suite.txt is read; a shard `timed out after <s> s` (run_test_shards.py) is printed
  `ABNORMAL shard TIMED OUT (NEW)` and counted (595's SR read only `exit N` lines). GR and SR print the two named tests:
  `test_runtime_distribution.py::test_wheels_have_separate_owners` (PASS expected now) and
  `test_execution_budgets.py::test_installed_runner_delivers_elapsed_notices_to_final_leader` (not in 516: a failure is
  NEW and goes to suite-base). Known ids come only from 516's current definition through its `task.yml`.
- **suite-base:** base = GraphTraj 3eb21101 + graftling 49f97004 (wheel). That graftling still says 0.8.0, so a
  version-pair test (like test_wheels_have_separate_owners) fails on the base side only; a candidate-only failure is a
  regression of this release.
- **scan (new):** read-only old-name search of live configuration and real launch scripts/wrappers (file:line; live
  configuration, docs and history apart). Run before I and after I.
- **scanhome (new):** the USER's `~/.claude/settings.json` and `~/.claude.json`; prints only matching rule strings. Main
  asks the USER first (`ADOPT593_HOME_ASKED=yes`).

## 588 and 595 (requirement 3)

Not repeated here. 588's real Engineer `submit_report` check was completed on an installation containing the change
(588 rounds/2 leader-2.md; accepted 20261123T231030.043120+0900). 595's two-member registration was accepted from a
real agent-runner entry (595 leader-2.md; accepted 20261124T025619.102747+0900); its acceptance does not depend on this
adoption.

## Step order

00 → scan → rel → rp → gh → B → G → GR (→ SR → suite-base only if NEW) → V → Vc → [scanhome, Main asks the USER first]
→ Mpre → [593's Leader and Engineer have ended their turns; Main asks the USER] USER `/exit` → I (USER) → USER
`cd <Harness> && claude --continue` → M → Mr → Mp → Mps → inbox → Nw → N → Nr → X → Nt → scan (after I) → C5 → done →
[Leader accepts 593] → [Main integrates this Task's branch] → T. Rollback: R.

## Rehearsal

`ADOPT593_PART=release zsh scripts/adopt-593/rehearse.zsh` (output in `rehearsal-output-release.txt`) covers 00, scan,
scanhome, rel (including negatives: dev moved, conflicts, missing base, wrong tag), rp and gh against a scratch bare
origin, B, G through its real entry (6 shards; real tests including ones using repository fixtures), GR, SR (including
a shard timeout) and suite-base on one real id.
