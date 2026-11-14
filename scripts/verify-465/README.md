# 465 real-host check: a Claude member's history grant does not grow with associated Sessions

Main runs every step. 00u is the user's, only if a member step reports a folder-trust or login refusal. Each Main
command returns within 10 minutes or starts its work in the background. No step signals a process, and no step
runs `rm` inside `zsh -c`. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/465-bounded-team-history-read-grants/realhost/`
(= the Task's `.state/realhost/`, `…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/465-bounded-team-history-read-grants/scripts/verify-465/steps.zsh`.

Base: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/465/` (`src`, `venv`, `project`,
`histories`, `bin-2.1.325`, `suite-venv`). Nothing is created in the user's home.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | `465 fix loaded: YES`, `deps: click 8.5.0`, `roles OK`, `ready tasks: ['1', '2']`, `isolation: OK`, `2.1.323: 2.1.323 (Claude Code)` and `2.1.325: 2.1.325 (Claude Code)`, each with `result: MODEL OK`, model `claude-opus-5-5` and an `init:` line (apiKeySource is a source name, not a key). |
| 00u | USER, only if 02 or 03 reports a trust or login refusal | `cd …/tmp/465/project && claude`, 'Yes, proceed', `/exit` | Main reruns the refused step. |
| 01 | Main | `S 01 2>&1 \| tee …/realhost/01.txt` | `associated JSONL files (project_history_files): 1000` and both `SEEDED_…` IDs. |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits ≤ 9 min. `== summary: ALL PASS` (CHECK 1–7) and a `settings:` line with `"seeded paths present": 0`. |
| 03 | Main | `S 03 2>&1 \| tee …/realhost/03.txt` | Adds 500 associations (N = 1500), waits ≤ 9 min. `== summary: ALL PASS` and `counts independent of N: True`. |
| 04 | Main | `S 04` | Full suite at HEAD in the background, six shards, stops itself after 25 min. `tail -n 25 …/realhost/04-suite.txt`; done at `== totals:`. |

No step shows a native dialog (00u only if needed: folder trust).

## Isolation

The isolated project lives under the Harness root, which has `AGENTS.md` and `.graphtraj`, and no `.git` and no
`CLAUDE.md`.

- graphtraj: `discover_project_root` walks up from the cwd and stops at the first directory whose
  `.graphtraj` configuration loads. 00 runs `graphtraj setup` in the project, so it stops there; the Harness's
  `.graphtraj` is never reached. 00 prints `graphtraj project root: …/tmp/465/project | isolated: True`.
- Git and Claude Code: 00 runs `git init` in the project, so the Git top level (Claude Code's project root for
  `.claude/` settings) is the project. Claude Code loads `CLAUDE.md`/`CLAUDE.local.md` from the cwd upward, not
  `AGENTS.md`; 00 prints any `CLAUDE.md`/`CLAUDE.local.md` found at or above the project (expected `none`) and the
  `AGENTS.md` above it (the Harness's, which Claude Code does not load). `isolation: OK` needs all three.
- The members are dispatched directly by the Runner (`agent-runner --swarm-input`, as the project's root caller),
  as in the real-Claude test in `tests/test_claude_runner.py`; no Main model session, plugin or `.mcp.json` is used.

## What each step does

### 00 preflight

A scratch venv from the commit under test (`git archive`, editable install, click/yaml/websockets copied read-only
from production `.venv-runtime`). The `465 fix loaded` line checks the venv's source: the Claude member settings
no longer call `project_history_files`, and the Codex member grants pass `history=False`. Then the isolated
project, one `team_leader` role (`claude`, `claude-opus-5-5`, `permission_mode: auto`), probe Tasks 1 and 2 set
ready, the isolation facts, and each binary's `--version` and one `claude -p` line (no MCP). 2.1.323 is `claude` on
PATH. 2.1.325 is `/Users/luoxiao/.local/share/claude/versions/2.1.325`, reached only through the link
`…/tmp/465/bin-2.1.325/claude`; `~/.local/bin/claude` is not changed. It also prints the unassociated production
Session file the members will check (path only) and whether `~/.codex/auth.json` exists (never read).

### 01 seed

`probe.py seed` writes N (default 1000; `VERIFY465_N`) runner records
`project/.graphtraj/runner/sessions/seed-465-NNNNN/session.yml`, each with a `rollout_path` to a dummy JSONL under
`…/tmp/465/histories` (half `claude/projects/…/<uuid>.jsonl`, half `codex/sessions/…/rollout-….jsonl`), and one
Claude and one Codex Session in the isolated archive (`SEEDED_CLAUDE`, `SEEDED_CODEX`). It prints the count that
`project_history_files` returns: the number of files the old code granted to every member.

### 02 and 03: one member each

`probe.py run` checks that the Runner resolves the expected Claude Code version, dispatches one member, and waits
(≤ 9 min) until it settles. The member:

1. Bash `echo bash-ok`;
2. `session_read` on an associated Session ID in the isolated archive: in 02 the seeded Claude Session
   `4650c1a0-0000-4000-8000-000000000465`; in 03 the 02 member's own Claude Session (cross-member);
3. Bash `cat FILE >/dev/null 2>&1 && echo READABLE || echo DENIED` on an unassociated production Session file
   (default `~/.claude/projects/-Users-luoxiao-workspace-you-are-a-product-architect-delivery/f3ce62db-….jsonl`,
   override with `VERIFY465_UNASSOCIATED`);
4. native Read on the same file, limit 1, reporting only READABLE/DENIED;
5. Bash redirect form only on `~/.codex/auth.json` (never Read, never `cat` to stdout);

and replies with one `RESULT-465 …` line. The probe reads the member's Session through `session_read` and prints
only that line's fields, never tool output. CHECKs: 1 no `E2BIG`/`Could not start` anywhere in the Session; 2
`bash-ok`; 3 the `session_read` header equals the header the probe itself reads for the target; 4–6 the three
denials; 7 the member's `claude-settings.yml` names no seeded path. The `settings:` line gives the file's byte
size and the counts of `permissions.allow/deny/additionalDirectories` and `sandbox.filesystem.allowRead/denyRead/
allowWrite/denyWrite`. 03 first adds 500 associations and finally compares 02's and 03's counts
(`counts independent of N: True`; the byte sizes differ only by path lengths).

### 04 full suite

As 460's step 03, against the Worktree HEAD.

## Rehearsal (sandbox, no model)

`VERIFY465_NO_MODEL=1 VERIFY465_BASE=$TMPDIR/rh465 VERIFY465_OUT=$TMPDIR/rh465-out`, then `S 00`, `S 01`, `S 02`.
Rehearsed: 00 (venv, `465 fix loaded: YES`, project, roles, both Tasks ready, `isolation: OK`, 2.1.325 version),
01 (1000 records, `project_history_files` = 1000, both seeded Sessions readable by native ID through the library
`read_session`) and 02 up to dispatch. Not rehearsed: the model lines, the dispatch, the members' tool calls, 03's
comparison, 00u and 04. In the sandbox `~/.local/bin/claude` and `~/.claude/projects` are not reachable.
