# Task 593 — graftling 0.9.0 release and production adoption

Production now: graphtraj eb009725 + graftling 0.8.0 (579; v0.8.0 = 542a81df; `.venv-runtime/bin` has `agents` and
`agents-mcp`). After 593: graphtraj 3eb21101 (GraphTraj dev: 588, 592, 595; already `graftling>=0.9.0,<0.10`) +
graftling 0.9.0 (591: MCP tool `agents` → `subagents`, commands `agents`/`agents-mcp` → `subagents`/`subagents-mcp`,
no alias). The user confirmed 0.9.0 (Worldline user-decision 20261124T030013.925262+0900) and pre-approved the push of
graftling main and v0.9.0 and the use of their Claude login (20261124T030105.522331+0900). No Task-state migration.

**Status:** Main already ran `00`, `scan`, `scanhome`, `rel`, `rp`, `gh` and `B` from the early HEAD 6a715d25. All
passed, and G is running. Do not rerun rel, rp or gh. Real-host facts used below:
- before I, the scan found one live hit, the expected hook copy line `const TOOLS = ["agents", "tasks"];`, and no
  launch scripts or wrappers;
- scanhome found 0 USER allow rules naming the old names;
- `.claude/settings.local.json` has no `mcp__` rule.

All steps are now written for the new names and rehearsed (`rehearsal-output.txt`).

## Correction 3 (Worldline user-decision 20261124T101325.067460+0900): X on graftling's own host

The real X failed with `invalid-config` (raw-6fe8c8d9/X.txt):
- X created the child with preset `x593` on the GraphTraj host.
- graftling `control.py:826-828` refuses a selection when the driver's `prepare` takes no `selection`.
- GraphTraj's driver (`agent_driver.py:194`) has none: it selects only through roles.yml `configuration`.
- graftling's own Claude driver (`claude/driver.py:74`) accepts a selection.

So X now runs on graftling's own Claude host in `/private/tmp/uvtool-593/project`. C5 created that project with
`configuration --write` from the uv install of GitHub v0.9.0; the USER trusted it in C5u, and C5r passed there.
- **Config:** the data root is `root` in `<project>/.agents-control/claude-host.json` (graftling `claude/host.py`; by
  default `<project>/.agents-control`). graftling reads `config.yml` there (`config.py`).
  - X keeps a copy of an existing `config.yml` as raw `X-config-before.yml`. The rewrite does not keep comments; the
    copy does.
  - X then merges in: the local command reviewer `x593-review` (`x593.py reviewer`), the connection `x593c` (runtime
    claude, review x593-review), the preset `x593`, and `save_normalized_sessions: true`, so the child's Session is
    archived for the judge.
  - graftling 0.9.0 from that install reads the result back.
  - X writes only under `/private/tmp/uvtool-593` and its raw directory. It never touches production's config,
    `.venv-runtime` or `/private/tmp/vproject-593`.
- **Real run:** `claude -p` in that project, in a clean environment, `--allowedTools mcp__graftling__subagents`. It
  creates `x593` with preset x593, waits until the child ends and retires it. The child calls its own subagents tool
  (status) and runs Bash.
- **Judge:** `x593.py judge <data root>` checks the same five CHECKs. Any `mcp__<server>__subagents`, including
  `mcp__graftling__subagents`, counts as exempt. The reviewer must see `subagents/connectivity-check`.
- **Order:** … → C5 → C5u (USER) → C5r → **X** → done. X STOPs, naming C5/C5u/C5r, when the project or C5r's PASS is
  missing. It runs after C5r's before/after comparison, which therefore does not see X's writes.
- **No rerun needed:** TARGET stays `6fe8c8d9`, product_guard is unchanged, and only `scripts/` changed.

## Correction 2 (user option A, Worldline user-decision 20261124T091451.431013+0900)

Main's G on 3eb21101 + v0.9.0 found 4 NEW failures:
`tests/test_mcp_adoption.py::test_installed_proxy_uses_websocket_for_public_refresh`, all four params.

Cause:
- 592's c9d68f31 changed the assertion at :111 to `['subagents', 'tasks']`.
- It left the test's own fake Codex server reply at :68 as `'tools': {'agents': {}, 'tasks': {}}`.
- The test skips without codex on PATH (:39-40), which hid the mismatch.

Fix: `6fe8c8d9`, one line, test only. The fake reply now lists `subagents` and `tasks`.

The candidate (TARGET) is now `6fe8c8d9`, so the raw directory, wheels, G records and V copies are named `6fe8c8d9`:
- product_guard requires TARGET's src, plugins and pyproject.toml to equal `PRODUCT0` = 3eb21101. It prints that only
  `tests/test_mcp_adoption.py` differs.
- B checks that the graphtraj wheel equals both `git archive 6fe8c8d9` and `git archive 3eb21101 src`.

suite-base on these 4 ids:
- On 2f66c0ad it gave "fails on both", because both sides ran 3eb21101's test file.
- With the fix, base (3eb21101 + graftling 49f97004) should fail them and the candidate should pass them:
  `base-only (passes on the candidate)`.
- Before/after in the Engineer's sandbox: all 4 SKIP on both commits, `Host denies Unix socket binding ([Errno 1]
  Operation not permitted)`, so Main's suite-base is the proof. Command:
  `zsh <Worktree>/scripts/adopt-593/steps.zsh suite-base 'tests/test_mcp_adoption.py::test_installed_proxy_uses_websocket_for_public_refresh[False-False]' '…[False-True]' '…[True-False]' '…[True-True]'`,
  with each id written out in full.

**Rerun order:** B → G → GR (→ SR / suite-base only if NEW) → V → Vu (USER, folder trust for
`/private/tmp/vproject-593`; not run yet) → Vc → [scanhome is done] → Mpre → … as below.
Do not rerun 00, scan (before I), scanhome, rel, rp or gh.

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

## Changed from adopt-579 (adoption part)

- **Hook copy (V, I):** production's `.claude/skills/graphtraj-claude-host` is regenerated ONLY through the product:
  V's `adopt_plugin.py regen` (adoption_material + write_adoption) on a scratch copy, and I's `configuration --write`.
  `plugin593.py` names the exact 0.8.0→0.9.0 difference, as seen when the 0.9.0 wheel regenerates a copy 0.8.0 wrote:
  - `hooks/hooks.json` stays the same: it holds `{"modules": [...]}` and no matcher.
  - `.claude-plugin/plugin.json` changes its description only (592: "subagents and tasks").
  - `hooks/host_context.mjs` changes by 591's 14 removed and 19 added lines: `const TOOL = "subagents"`,
    `TOOLS = [TOOL, "tasks"]`, PREFIX, the labels and `name === TOOL`.

  V STOPs on anything else; I checks the installed copy equals V's (SAME-AS-VALIDATED) and the same prediction. **At
  `claude --continue` the plugin/hooks trust dialog for graphtraj-claude-host is expected: the USER chooses trust.**
- **New names everywhere:** `mcp593.py` requires tools/list to be exactly `[subagents, tasks]`, and a `tools/call`
  named `agents` must be refused (`Unknown tool: agents`). It runs in V on the scratch venv, in I and done on production,
  and Mr prints it. After I, `.venv-runtime/bin` must have `subagents` and `subagents-mcp` and no `agents` or
  `agents-mcp`; R checks that 0.8.0's are back. `rec593.py` judges `mcp__graphtraj__subagents`/`tasks`, and treats
  `mcp__graphtraj__agents`, `mcp__<s>__agents` and `mcp__agents__*` as old names.
- **Mpre and I (requirement 3: no member running):** `members_idle` STOPs while a member Worker
  (`-m graphtraj.execution.runner_worker`) or swarm batch runs. It never signals. Mpre allows Main's own host; I also
  needs guard's BLOCKING 0 before the backup and again before pip. 593's own Leader and Engineer must have ended their
  turns first. (579's I waited; 593's STOPs, as the Leader asked.)
- **M and Mr (after `claude --continue`):**
  - M[a]: the tool list holds only `mcp__graphtraj__subagents` and `tasks`.
  - M[b]: one real `mcp__graphtraj__subagents` status call and one tasks `task_graph` call.
  - Mr reads Main's own transcript `~/.claude/projects/<Harness path>/<MAIN>.jsonl` after I's install end. It needs a
    `tool_use` of each with a non-error result. An old-name call there is recorded as `INFO 593 … old-name calls`, not
    failed: the resumed history holds the old name (590 4.1).
  - Dialog: none expected. No allow rule names the old tool (scanhome 0, settings.local.json has no `mcp__` rule), so
    the first new-name call behaves like the earlier agents calls. If a tool-permission dialog shows anyway, choose
    'Yes' for this once and tell Main.
  - Optional: the USER's `/agents-context` should show subagents and tasks registered, and no agents.
  - 575's Ma is removed.
- **N and Nr:** the member creates the Claude child `n593` through `mcp__graphtraj__subagents`, without `tools`. The
  child runs Bash and replies DONE-593. Nr checks:
  - the member's `mcp__graphtraj__subagents` calls are ok and it made no old-name call;
  - the child was created without tools;
  - a Bash `tool_use` is archived.
- **X (review exemption, real):** graftling exempts `mcp__<server>__subagents` (`claude/execution.py` `agents_tool`,
  `_review_hook`). Review is on only for a connection that names a reviewer in config.yml.
  - X first prints production's reviewers and reviewed connections, names only.
  - Production's config is not readable from the Engineer's sandbox, so X does not assume that production reviews. It
    runs the minimal real check with a local command reviewer (`x593.py reviewer`), which records only tool names and
    allows; it needs no provider. **Since correction 3** this runs on graftling's own host in
    `/private/tmp/uvtool-593/project`, not in `/private/tmp/vproject-593` (see Correction 3).
  - A real `claude -p` creates the reviewed Claude child `x593` through `mcp__graftling__subagents`.
  - `x593.py judge`: the reviewer saw the create probe under the new name (`subagents/connectivity-check`) and the
    child's Bash; no `mcp__*__subagents` reached the reviewer or `review.jsonl`; the child's own subagents call ran
    with a non-error result; the child completed.
  - `claude-diagnostics-*.yml` keeps no tool list, so the startup registration is shown by that call.
- **scan after I:** expect 0 live configuration hits.
- **C5, C5u, C5r (requirement 5, Claude Code as the host):**
  - C5 snapshots `~/.local`, the USER's uv tool dir, `~/.pi`, `~/.dsh`, `~/.codex` and conda. `~/.codex` is compared by
    name and sha256 without `logs_*.sqlite*` and `models_cache.json`, which the USER's running Codex writes.
  - C5 runs the release's single install method as graftling's README states it,
    `uv tool install "git+https://github.com/LUOXIAO92/graftling.git@v0.9.0"`. No interpreter preference is set
    ("uv gets a Python 3.12 or later when it needs one"). Only `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_CACHE_DIR` and
    `UV_PYTHON_INSTALL_DIR` are isolated under `/private/tmp/uvtool-593`. uv's own interpreter lines are printed as
    `uv said: …` (full output in `C5-uv.txt`).
  - CHECK (correction 1): the tool's `sys.prefix` is `/private/tmp/uvtool-593/tools/graftling` and
    `graftling.__version__` is 0.9.0.
  - `REPORT 593 C5 base interpreter: <sys._base_executable or sys.base_prefix> (<class>)` gives the class: uv-managed
    (under `/private/tmp/uvtool-593/python`), conda (under the conda root) or other. For conda it adds
    `NOTE 593 C5: the uv tool environment is based on conda's Python (…); no install into conda was made; Main decides
    whether this meets requirement 5`. The NOTE is neither PASS nor FAIL, and C5r still runs.
  - C5 generates `/private/tmp/uvtool-593/project` with `configuration --write` from that installation: project files
    only, no plugin install into the USER's Claude Code, no `~/.claude` change.
  - C5u: the USER trusts that folder once.
  - C5r runs inside `zsh -f`, in a clean environment, with `conda shell.zsh hook` and `conda activate` (default `base`,
    `ADOPT593_CONDA_ENV`). It shows conda's python on PATH and that the `subagents` CLI works. A real `claude -p`
    creates a child through `mcp__graftling__subagents` and waits for it to end.
  - A ps sampler records the graftling processes: they must run as `/private/tmp/uvtool-593/tools/graftling/bin/python`
    (the tool environment's bin/python as invoked), and no process line may name the conda root. Then before and after are compared. If a per-environment install proves necessary, C5r installs
    nothing and says so; Main decides.

## 588 and 595 (requirement 3)

Not repeated here. 588's real Engineer `submit_report` check was completed on an installation containing the change
(588 rounds/2 leader-2.md; accepted 20261123T231030.043120+0900). 595's two-member registration was accepted from a
real agent-runner entry (595 leader-2.md; accepted 20261124T025619.102747+0900); its acceptance does not depend on this
adoption.

## Step order

00 → scan → rel → rp → gh → B → G → GR (→ SR → suite-base only if NEW) → V → Vc → [scanhome, Main asks the USER first]
→ Mpre → [593's Leader and Engineer have ended their turns; Main asks the USER] USER `/exit` → I (USER) → USER
`cd <Harness> && claude --continue` → M → Mr → Mp → Mps → inbox → Nw → N → Nr → Nt → scan (after I) → C5 → C5u (USER)
→ C5r → X (correction 3) → done →
[Leader accepts 593] → [Main integrates this Task's branch] → T. Rollback: R.

## Step table

| Step | Who | Dialog (choice) | PASS lines |
|---|---|---|---|
| 00 | Main | none | answer check OK; `CHECK 593 Codex answers CODEX-593-OK …: PASS`; markers absent 8/8; production bin `agents agents-mcp`; `CHECK 593 probe Task 593 ready …: PASS`; conda/uv lines; MAIN=<id> |
| scan (before I) | Main | none | `REPORT 593 old-name scan [before-I]: …` with each LIVE file:line (expected: the hook copy's TOOLS line) |
| scanhome | Main, after asking the USER | none | `REPORT 593 USER allow rules naming the old tool or commands: N` (only matching strings printed) |
| rel / rp / gh | Main (done) | none | as the early HEAD (four rel CHECKs; rp remote = local; three gh CHECKs) |
| B | Main | none | product guard PASS (pins `graftling>=0.9.0,<0.10`); version strings; console scripts subagents only; Requires-Dist 0.9.0 yes, 0.8.0/0.10.0 no; wheels = archives; markers present 8/8; leaked 0 |
| G → GR (→ SR → suite-base) | Main | none | `CHECK 593 G record … no new failure: PASS`; `CHECK 593 GR (guard + G record): PASS`; `named:` lines; `shard timeouts …: 0` |
| V | Main | none | `CHECK 593 plugin differs by exactly 591/592 …: PASS`; `CHECK 593 candidate plugin as predicted …: PASS`; mcp593 two PASS; scratch bin PASS; Codex hooks two PASS; markers 8/8 both ways |
| Vu (only if Vc asks) | USER | folder trust for /private/tmp/vproject-593 → Yes, proceed | — |
| Vc | Main | none | `CHECK 515 .mcp.json …: PASS`; `graphtraj-claude-host loaded: YES`; PASS mcp__graphtraj__tasks and mcp__graphtraj__subagents; four `CHECK 593 init …: PASS` |
| Mpre | Main | none | `GR: PASS`; `members_idle [Mpre]: no member execution is active: PASS` (593's Leader and Engineer have ended their turns) |
| /exit Main, I | USER (Main asks first) | none | `Successfully installed graftling-0.9.0 graphtraj-0.1.0`; `CHECK 593 production bin has subagents, subagents-mcp and no agents, agents-mcp: PASS`; SAME-AS-VALIDATED; `CHECK 593 installed plugin changed as V predicted …: PASS`; `CHECK 593 production-graphtraj-mcp MCP tools/list is exactly subagents, tasks: PASS` and `… agents is unknown …: PASS`; Codex hooks two PASS |
| `cd <Harness> && claude --continue` | USER | **plugin/hooks trust for graphtraj-claude-host → trust** (any other: Esc, tell Main) | — |
| M | Main | none expected (if a tool-permission dialog shows: Yes once, tell Main) | M[a] only subagents and tasks; M[b] subagents status ok, task_graph ok |
| Mr | Main | none | `CHECK 593 [Main …] mcp__graphtraj__subagents …: PASS`, `… tasks …: PASS`; `INFO 593 … old-name calls …` (recorded only) |
| Mp, Mps, inbox | Main | none | four `CHECK 593 init …: PASS`; host on .venv-runtime after the install; duplicate ids 0 |
| Nw, N, Nr | Main | none | Nr: 576 CHECKs; `CHECK 593 [member …] mcp__graphtraj__subagents …: PASS`; `… no old-name call …: PASS`; notice once |
| Nt | Main | none | as 579 |
| scan (after I) | Main | none | `REPORT 593 old-name scan [after-I]: live configuration hits 0` |
| C5 | Main | none (network) | `uv tool install rc=0`; `CHECK 593 C5 one install from GitHub v0.9.0 in the uv tool environment /private/tmp/uvtool-593/tools/graftling (sys.prefix), graftling 0.9.0: PASS`; `REPORT 593 C5 base interpreter: … (<class>)`, plus a `NOTE 593 C5: …` only for conda (neither PASS nor FAIL; Main decides) |
| C5u | USER (once) | folder trust for /private/tmp/uvtool-593/project → Yes, proceed | — |
| C5r | Main | none | `conda active: …`; `subagents CLI: …`; four `CHECK 593 C5 …: PASS`; `REPORT 593 <dir> unchanged: yes` for each |
| X (correction 3) | Main | none expected (folder trusted at C5u; if Claude asks about the project MCP server 'graftling': approve for this project) | `graftling reads it: ['x593c'] ['x593'] ['x593-review']`; PASS mcp__graftling__subagents; five `CHECK 593 X …: PASS`; STOP naming C5/C5u/C5r when the project or C5r's PASS is missing |
| done | Main | none | all CHECKs PASS; production bin `subagents subagents-mcp`; scan after-I live 0; key values 0 |
| T | Main (after acceptance and integration) | none | as 579 |
| R | USER (Main asks first) | none at R; at the next `claude --continue` the plugin trust dialog may show again → trust | venv and plugin SAME; restored CHECKs; `CHECK 593 R: bin has 0.8.0's agents, agents-mcp again …: PASS` |

## Rehearsal

`zsh scripts/adopt-593/rehearse.zsh` (output in `rehearsal-output.txt`; the release part alone, as run for the early
HEAD, in `rehearsal-output-release.txt`) uses a fake production under `$TMPDIR`:
- graphtraj eb009725 + the real v0.8.0 wheel, its plugin written by 0.8.0;
- a scratch graftling clone and a scratch bare origin;
- stub `claude`, `codex` and `ps`.

The MCP server, Codex hooks entry, plugin regeneration (V and I), the old-name scan, the x593 reviewer command, G's
real test entry and suite-base are real. Main's transcript (Mr), the member and child records (Nr) and X's data root
(judge) are labelled REHEARSAL FIXTUREs.

**Not rehearsed:**
- a real Claude Main, its resume, and the trust and permission dialogs;
- real member dispatch;
- X's real `claude -p` with a reviewed child;
- C5's network install and its conda-activated `claude -p`. What is rehearsed: C5's refusals, C5u's text, and the C5
  interpreter check per class (a real venv on Miniconda's Python gives conda plus the NOTE; a fixture interpreter
  under `<uvt>/python` gives uv-managed and no NOTE; a wrong `sys.prefix` FAILs);
- GitHub.
