# Task 600: graftling 0.9.1 release and production adoption

The user made three decisions for this Task (Worldline user-decisions):
- **Release and push:** 20261124T114043.053104+0900.
- **Production adoption** ("发布后换到生产"): 20261124T115149.870298+0900.
- **Claude login:** pre-approved for 00's probe and for N, 20261124T115605.289456+0900.

0.9.1 is a compatible patch release:
- 597 changes the printed install command and the install documentation;
- 599 adds a PUBLIC_API note on Retired Agents.

No public name, result, archive format or behavior changes. The wording of error messages is internal, by PUBLIC_API's preamble. Nothing is published to PyPI or npm.

**Production adoption.** `.venv-runtime` now has graphtraj 0.1.0 from 593's wheel of 6fe8c8d9, plus graftling 0.9.0. This Worktree's `src`, `tests`, `plugins` and `pyproject.toml` equal 6fe8c8d9, so the GraphTraj product does not change. **I installs only the graftling 0.9.1 wheel**, with `pip --no-deps --no-index`; graphtraj is not reinstalled.

Between graftling 0.9.0 and 0.9.1 the only code changes are message text in `claude-plugin/bin/graftling-host` and `dsh/plugin.mjs`. The Harness hook copy is written from `claude/plugin.py` and `claude/host_context.mjs`, and both are unchanged. So the hook copy should stay byte-identical: no regeneration, and no trust dialog at `claude --continue`. V checks this through the product itself.

## Values (fixed in steps.zsh)

| name | value |
|---|---|
| graftling dev at dispatch (GBASE) | `2b4a33aef93dc45b953bd412e4d5dd61347c38ea` (597 + 599) |
| graftling main = v0.9.0 (GMAIN0) | `7b5f4e6b48ec2c502947942f5ebbb3029ecc2fc9` |
| release commit (GCOMMIT) | `e8c2e80241dff1151f2122e8957fca5598ec987b` "graftling 0.9.1 (600)": one commit on GBASE that changes 5 files. Author and committer: LUOXIAO92 &lt;89069722+LUOXIAO92@users.noreply.github.com&gt;. |
| bundle | `graftling-0.9.1.bundle` (`2b4a33ae..agent/600-graftling-0.9.1`); sha256 `b5c6d530ef5f3f5324438a4f3ba6d47d0ef8bee271e4b7f53f34f2f2fe66ee12` |
| tag | annotated `v0.9.1` at GCOMMIT, with the noreply tagger; the message names 597, 599 and "compatible" |
| production graphtraj (TARGET) | `6fe8c8d97b5eedaf3fae898cd3f3f86a66a7acf7`, from 593's `adoption/wheels-6fe8c8d9/` |
| C5 install | `uv tool install --managed-python "git+https://github.com/LUOXIAO92/graftling.git@v0.9.1"`, with UV_TOOL_DIR, UV_TOOL_BIN_DIR, UV_CACHE_DIR and UV_PYTHON_INSTALL_DIR under `/private/tmp/uvtool-600` |
| wheel G and I install | `<state>/tasks/600-graftling-0-9-1-release/adoption/wheels-0.9.1/`, with SHA256SUMS |
| backup | `<Harness>/tmp/600/backup`: venv, hook copy, `.mcp.json`, `settings.local.json`, `config.json`, the R tools, and a COMPLETE marker |
| raw output | `<state>/tasks/600-graftling-0-9-1-release/realhost/main-raw/` |
| scratch | `<Harness>/tmp/600` (00 creates it), `/private/tmp/uvtool-600`, `/private/tmp/vproject-600` |

## Steps

Run each step as `zsh <Worktree>/scripts/adopt-600/steps.zsh <step>`. They form one ordered list; each step prints who runs it, its dialog, whether it needs a login, its PASS lines, and the exact next command.

| step | who | dialog | login | PASS lines (`CHECK 600 <step> …: PASS`) |
|---|---|---|---|---|
| 00 | Main (read only; creates `tmp/600`) | none | yes: one `claude -p` probe, pre-approved | **Release:** runs under zsh; uv has `--managed-python`; `$UVT` absent; dev = GBASE and main = GMAIN0, in their worktrees, both clean; v0.9.1 absent locally and on GitHub; GitHub main = GMAIN0 and GitHub dev is an ancestor of GBASE; bundle sha256, verify and head; GCOMMIT is one noreply commit that changes exactly 5 files; README line = C5's command. **Adoption:** TMPDIR outside the Harness; production is graphtraj 0.1.0 + graftling 0.9.0 from 593's wheels; pip check; bin has subagents and subagents-mcp; 593's wheels present; backup absent; product guard; probe Task 600 ready; `claude -p` answers READY-600; Main's Session id found |
| rel | Main | none | no | v0.9.1 peels to GCOMMIT; main == dev == GCOMMIT; annotated tag with the noreply tagger; message names 597, 599 and compatible; version 0.9.1. STOPs, changing nothing, if dev ≠ GBASE or main ≠ GMAIN0. A rerun prints "already released". |
| B | Main, before the push | none | no | version strings in the archive and in the wheel; CHANGELOG heading; console scripts exactly subagents, subagents-mcp; wheel = git archive; 597/599 markers; no build/ or `__pycache__`; GraphTraj's range includes 0.9.1 (REPORT: no change needed); `wheels-0.9.1/` with SHA256SUMS |
| G | Main; background, ~25-30 min | none | no | Starts the full suite: this Worktree's HEAD (editable) + the 0.9.1 wheel, clean environment, pytest temp under TMPDIR, serial queue (waits behind another suite). Returns at once. |
| rp | Main; `ADOPT600_PUSH_CONFIRMED=yes` | none | no (the user's usual git credentials) | remote main == v0.9.1^{} == GCOMMIT; remote dev == local dev. The push is atomic and fast-forward only, never forced. |
| gh | Main, read only | none | no | GitHub main = GCOMMIT; v0.9.1^{} = GCOMMIT; GitHub's tag object = the local one |
| C5 | Main | none | no | README's command from GitHub: rc 0; version 0.9.1; sys.prefix; base interpreter uv-managed; commit_id = GCOMMIT; `subagents --help` rc 0; subagents-mcp exists; USER directories and conda unchanged |
| GR | Main, after G ends | none | no | The record's product = 6fe8c8d9 and its wheel = v0.9.1; temp outside the Harness, clean environment; click 8.5.0; no new failure. Ids not named in 516's current definition, and any ABNORMAL shard (including "timed out after"), are NEW. |
| SR, suite-base | Main, only if GR names NEW ids | none | no | SR prints the suite-base command. suite-base reruns the ids on 6fe8c8d9 + 593's 0.9.0 wheel (base) and on G's venv (candidate). |
| V | Main | none | no | Scratch venv (593's graphtraj wheel + 0.9.1): pip check, one graftling, subagents bin. **The hook copy regenerated by the product is byte-identical to production's**; on any difference V STOPs and hands the diff to the Leader. Scratch graphtraj-mcp tools/list is exactly subagents, tasks and 'agents' is unknown; Codex hooks entry. |
| Mpre | Main | none | no | GR and V passed; no member Worker or swarm batch runs. Main then tells the USER: the USER /exits Main and runs I in a Terminal. |
| I | USER, in a Terminal after /exit | none (one Enter) | no | members idle; backup COMPLETE; entries unchanged since V; pip install of the 0.9.1 wheel only; graftling 0.9.1 from the 600 wheel; the 0.9.0 dist-info gone; installed = wheel; graphtraj direct_url and package unchanged; pip check; bin; one graftling; production graphtraj-mcp tools/list subagents, tasks; Codex hooks entry; hook copy, `.mcp.json`, `settings.local.json` and `config.json` byte-identical to the backup |
| claude --continue | USER | none expected (a plugin/hooks trust dialog: Esc and tell Main, since it would be unexpected) | the running Main | |
| M | Main (resumed) | none expected | no | Prints [a] the tool list (only mcp__graphtraj__subagents and tasks) and [b] one subagents status call and one tasks task_graph call |
| Mr | Main, read only | none | no | Main's transcript after I holds subagents and tasks calls without error (rec593.py) |
| N | Main | none expected | yes, pre-approved | Prints the swarm prompt: an advisor member on Task 600 creates the Claude child n600 through subagents, without tools; the child runs Bash and replies DONE-600 |
| Nr | Main, read only | none | no | 593's record checks (n600 stored selection, no tools, one completed execution, notification delivered, Bash ran, member end), one completed notice, the member's subagents calls, the swarm result's agent |
| done | Main, read only | none | no | production graftling 0.9.1 from the 600 wheel and graphtraj unchanged; every step's CHECK passed |
| R | USER (Main asks first; the USER /exits Main) | none (one Enter) | no | venv equals the pre-install bytes; hook copy and entries restored; graftling 0.9.0 again; pip check |

## Trimmed from adopt-593 (and why)

- **scan, scanhome:** 0.9.1 renames nothing, so there are no old names to look for.
- **Vc, Vu** (`claude -p` in an isolated project): V's real MCP entry plus the byte-identical hook copy cover what Vc proved.
- **Mp, Mps, inbox:** Mr reads Main's own transcript for the real calls. 0.9.1 does not touch the notice path.
- **Nw, Nt, T, timers** (490's budget timers and 525's Worker CPU): unrelated to a message-text release. Budget timers are still listed by the guard and never block or get signalled.
- **X:** the review-exemption code is unchanged.
- **C5u, C5r:** the definition asks C5 for no login.
- **markers.py:** its markers are 0.9.0-specific. onegraft.py (with version 0.9.1) and the wheel-equals-installed comparison take its place.

## Rehearsal (`rehearse.zsh`; outputs in `rehearsal/`)

The rehearsal runs against scratch copies under `$TMPDIR/r600` and only reads real production, `<Harness>/graftling` and GitHub.

What it uses:
- **Scratch graftling:** a clone of `<Harness>/graftling`, with dev in a second worktree. A scratch bare repository stands in for GitHub.
- **Fake production (fixture, built by the real product):**
  - a venv of 593's real wheels (graphtraj 6fe8c8d9, graftling 0.9.0), plus production's click, yaml and websockets;
  - `graphtraj setup`, and the product's own `configuration --write`, which writes `.mcp.json`, the settings, `config.json` and the hook copy;
  - copies of Tasks 600 and 516.
- **Stubs (fixtures):** `claude`, and `ps` (the sandbox refuses `/bin/ps`; the stub prints a fixture listing).
- **Fixtures, labelled in the files:** Main's transcript lines (Mr) and Nr's child and member records, notice, reply and swarm result.

What runs for real:
- rel, rp and gh as git operations;
- the wheel build;
- C5's uv install from `git+file://`;
- **G through `run_test_shards.py`**, with `-k` selecting real tests, including fixture users such as `test_wheels_have_separate_owners` (built_wheel);
- GR and SR;
- suite-base on one real id;
- V: the product's regeneration of the hook copy, and graphtraj-mcp;
- I: the backup and the pip install;
- R: the restore.

Rehearsed STOPs:
- rel with dev moved;
- rp before rel;
- rp unconfirmed;
- I before V/GR;
- Mpre with a member Worker (fixture ps line);
- I again with a backup present.

**Not rehearsed:**
- the real `<Harness>/graftling` and graftling-dev Worktree;
- GitHub: `ls-remote`, the push with the user's credentials, and uv's GitHub fetch, which the sandbox proxy refuses;
- the USER-directory and conda snapshots (the sandbox cannot read `$HOME`);
- the real `ps`, so the guard ran on fixture listings;
- the real Claude: 00's probe, Main's restart, M, N and the child run (stub and fixtures only);
- the uv on Main's PATH (597 used `~/.local/bin/uv` 0.9.18; the rehearsal used Miniconda's 0.12.3).
