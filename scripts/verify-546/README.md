# verify-546: send right after create is refused with runtime-input-closed

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-546/steps.zsh <step>`. No step needs user action
and no step raises a native dialog (headless `claude -p`; `--allowedTools mcp__graphtraj__agents`).
Main kind: Claude Code (headless, a verified Main through the product's claude host configuration). Child Runtime:
claude. BEFORE = GraphTraj f754d3a9 + graftling 6794ce0. AFTER = this Worktree HEAD + graftling branch
`agent/546-send-after-create-runtime-input-closed` (clone `.scratch/graftling`, git dir `.scratch/graftling-git`).
Every step ends with a ready-to-paste `==> next` line with real paths.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Version line; `BEFORE:`/`AFTER:` commits. `before venv: ... 546 fallback in graftling: False` and `after venv: ... True`. Per project, `.mcp.json graphtraj -> <venv>/bin/python -m graphtraj.runtimes.claude.host serve \| approval: enabledMcpjsonServers ['graphtraj'] in <project>/.claude/settings.local.json`. `CHECK 546 READY-546-CLAUDE: PASS` with `init model` and `auth source`. `CHECK 546 AGENTS before: PASS` and `CHECK 546 AGENTS after: PASS`: same flags as B/A, `mcp__graphtraj__agents in init tools: True`, the `agents execute status {}` call with `error: False` and a result without an authority/verified-caller refusal. |
| `B` | none | One line per agents call (create/send/wait) with called/returned times, error code and delivery. Then the child's record: every input receipt with `delivery=`, `error=` and `N s before this execution's recorded end`. `VERDICT 546: REPRODUCED` when a send got `runtime-input-closed` (receipt `delivery=rejected`) while the execution had not yet recorded its end. On `NOT-HIT`, repeat B (at most 5). |
| `A` | none | The same output on the candidate. Criterion: no send returns `runtime-input-closed`. A send that lands in the window shows `delivery: next-execution` with `closed_execution` and the new `execution`, and the verdict `CLOSING WINDOW HIT, NOT REFUSED`. Run A as many times as B. |
| `G` | none | `pytest temp: TMPDIR=... (outside the Harness)`. `uncommitted in ... src/tests: none`. `GraphTraj suite imports: graphtraj <Worktree>/src/... \| graftling <T>/venv-g-<sha>/...`, where the graftling wheel comes from git archive of the candidate. `graftling suite imports: graftling <T>/src-gl-<sha>/src/...`. `started in the background`. GraphTraj runs first with `scripts/run_test_shards.py --shards 6 --timeout 1500 -- -rA`, then graftling with `pytest -q -rA`. |
| `GR` | none | Read only. Prints `run.txt`, each suite's `exit=` line (plus the `leftover processes` line and any `ABNORMAL` line) and its summary line. Every FAILED/ERROR line is classed `known (516)`, `known (graftling flake, fails on base 6794ce0 too)` or `NEW`. Pass: exit=0, or only `known` lines. |
| `C` | none | Copies `before/`, `after/` runs, `ready/` (READY and probe streams) and the newest G to `<Worktree>/.state/realhost/`, then counts the VERDICT lines. |

Order: `00` → `B` (until REPRODUCED, at most 5) → `A` (as many runs) → `G` → `GR` (until both `exit=`) → `C`.

Trigger condition: Claude, Codex and DSH stop accepting input at the turn end. They report the end to agents only
after closing and archiving. In Claude's `execution.py` run(), `accepting = False` is set before `done`, and the record
stays `running` meanwhile. The window is the process shutdown (`_close`) plus the archive join. A send that arrived
in it was refused. The window is short, so B may need several runs.

MCP approval: the claude host configuration writes `.mcp.json` and `.claude/settings.local.json`, but that file
holds env only. It does not approve the `.mcp.json` server, so `-p` mode would not load it. `00` therefore adds
`enabledMcpjsonServers: ["graphtraj"]` to the isolated project's own `.claude/settings.local.json`, as verify-533 did.

Layout: projects and runs go under `/private/tmp/send-546/<before|after>/`, and READY/probe streams under
`/private/tmp/send-546/ready/`. Venvs, wheels, archive trees and suite outputs go under `<Harness>/tmp/546/`
(`G-latest` names the newest G). Pytest temp roots go under `$TMPDIR`.

Rehearsal: `zsh scripts/verify-546/rehearse.zsh <empty dir>`. Output is in `rehearsal/output.txt`. It runs every step
through the same entry.
- **The stub (`stub_claude.py`, as `claude`) replaced:** the READY answer and the 00 probe's init tool list. It also
  replaced the probe's `agents status` call and result, which were invented: no MCP server was called and no
  authority check was made. It replaced the whole Main model of B and A too. The stub makes no agents call there,
  so B and A print `NOT-HIT`.
- **Real:** steps.zsh and both phase venvs, built from git archive of the exact commits (the fallback flag is
  False/True). Also real: `graphtraj setup`, the claude host configuration, the approval write, drv546.py parsing,
  and G's guards, venvs, temp root and background runner. G ran a subset through the same venvs and temp root:
  GraphTraj `tests/test_agents_configuration_recorded.py` (its `project` fixture; agents create/wait/status through
  GraphTraj) and graftling `tests/test_agent_control.py`, `tests/test_claude_send_closing_546.py` (real ClaudeDriver
  with the CLI fixture) and `tests/test_dsh_standalone_child.py`. GR's classification and C were real too. Only the
  full shard runner was not rehearsed, because the subset uses plain pytest, as in 531.
