# verify-546: send right after create is refused with runtime-input-closed

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-546/steps.zsh <step>`. Only `Tu before` and
`Tu after` are USER steps, with one dialog each. Every headless run (the gate, P, B and A) uses
`claude -p --mcp-config <project>/.mcp.json --strict-mcp-config --allowedTools mcp__graphtraj__agents`, as verify-519
did, so init lists exactly the `graphtraj` server.
Main kind: Claude Code (headless, a verified Main through the product's claude host configuration). Child Runtime:
claude. BEFORE = GraphTraj f754d3a9 + graftling 6794ce0. AFTER = this Worktree HEAD + graftling branch
`agent/546-send-after-create-runtime-input-closed` (clone `.scratch/graftling`, git dir `.scratch/graftling-git`).
Every step ends with a ready-to-paste `==> next` line with real paths.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Version line; `BEFORE:`/`AFTER:` commits. `before venv: ... 546 fallback in graftling: False` and `after venv: ... True`. Per project, the role is written idempotently (as verify-514 prep514.py): exactly one role, `claude_member: {runtime: claude, model: claude-opus-5-5, worktree_access: read, claude: {permission_mode: auto}}` and `role_tree: {claude_member: {}}`. Doctor accepts only the exact claude-opus-5-5 without a model connection; it rejected sonnet in the rehearsal. Then `roles OK <phase> (claude role: claude_member; ... graphtraj doctor ...: roles: OK)`. Doctor alone also says OK for `roles: {}`, so the claude role is counted as well. Per project, `.mcp.json servers ['graphtraj'] \| graphtraj -> <venv>/bin/python -m graphtraj.runtimes.claude.host serve`. `CHECK 546 READY-546-CLAUDE: PASS` with `init model` and `auth source`. `plugin gate before/after:` lines are information only. Before Tu they read `NOT PASSED`, with `project-scope-suppressed-untrusted` in plugin_warnings and no graphtraj-claude-host plugin. 00 then prints the Tu commands as its next lines instead of stopping. |
| `Tu before` | USER: one | Prints the paste-ready `cd /private/tmp/send-546/before/project && <claude>`. The dialog is Claude Code's 'Do you trust the files in this folder?' naming that project: choose 'Yes, proceed', then type /exit and send no message. If an MCP approval for 'graphtraj' appears, approve it for this project. For any other dialog, press Esc and report its title. No dotfile is edited. |
| `Tu after` | USER: one | The same for `/private/tmp/send-546/after/project`. |
| `P` | none | First `roles OK before` / `roles OK after`, the same check as 00; STOPs otherwise. Then per project, the gate checks verify-519's four conditions: init `mcp_servers` is exactly `['graphtraj']`; plugin_warnings contains no `untrusted`; `mcp__graphtraj__agents` is in the tools; a plugin named `graphtraj-claude-host` is loaded. It prints `plugin gate <phase>: PASS` and `CHECK 546 AGENTS <phase>: PASS` for the `agents execute status {}` call, with `error: False` and no authority or verified-caller refusal. STOPs on any failure. |
| `B` | none | Runs the plugin gate first and STOPs unless it is PASS. Attempts go to `/private/tmp/send-546/<phase>/attempts/`, a new directory; the older `runs/run-1..5` of 011786de were all invalid and are left as they are. A valid attempt (create ok and at least one send) is saved as `run-<n>`. Any create error, no create, no agent, or no send prints `VERDICT 546: INVALID (<reason>)`. The attempt is then saved as `invalid-<n>` and not counted, and B/A exit 3 with `STOP: invalid attempt (<reason>) ...; Report to the Leader.` Results are parsed as JSON (`{"error": {"code": ...}}`, `result.agent`/`execution`/`delivery`), with the `key: value` text as fallback. At most 5 valid B attempts. Then one line per agents call (create/send/wait) with called/returned times, error code and delivery. Then the child's record: every input receipt with `delivery=`, `error=` and `N s before this execution's recorded end`. `VERDICT 546: REPRODUCED` when a send got `runtime-input-closed` (receipt `delivery=rejected`) while the execution had not yet recorded its end. On `NOT-HIT`, repeat B (at most 5). |
| `S before` / `S after` | none | Read only. Re-summarizes every `<phase>/attempts/run-*` from its `main.jsonl` and its copied `agent-record.json`, or the live record if no copy exists, and writes only each `summary.txt`. It prints each attempt's VERDICT, with the refused receipt's gap to the recorded end, then one totals line: `B summary: valid N, REPRODUCED k (run-..), NOT-HIT m, ...` (or `A summary`). Record timestamps may be epoch floats or ISO strings, and both are parsed. A summary crash makes the attempt `STOP: summary failed (rc=N)`, and the run is not labelled valid. `S before` on Main's 44aad571 attempts gives `valid 5, REPRODUCED 3 (run-2, run-3, run-4), NOT-HIT 2` (see `rehearsal/S-before-real-attempts.txt`), so B is complete. |
| `A` | none | The same gate and output on the candidate. Criterion: no send returns `runtime-input-closed`. A send that lands in the window shows `delivery: next-execution` with `closed_execution` and the new `execution`, and the verdict `CLOSING WINDOW HIT, NOT REFUSED`. Run A as many times as B. |
| `G` | none | `pytest temp: TMPDIR=... (outside the Harness)`. `uncommitted in ... src/tests: none`. `GraphTraj suite imports: graphtraj <Worktree>/src/... \| graftling <T>/venv-g-<sha>/...`, where the graftling wheel comes from git archive of the candidate. `graftling suite imports: graftling <T>/src-gl-<sha>/src/...`. `started in the background`. GraphTraj runs first with `scripts/run_test_shards.py --shards 6 --timeout 1500 -- -rA`, then graftling with `pytest -q -rA`. |
| `GR` | none | Read only. Prints `run.txt`, each suite's `exit=` line (plus the `leftover processes` line and any `ABNORMAL` line) and its summary line. Every FAILED/ERROR line is classed `known (516)`, `known (graftling flake, fails on base 6794ce0 too)` or `NEW`. Pass: exit=0, or only `known` lines. |
| `C` | none | Prints each attempt's verdict. Copies `before/`, `after/` runs and attempts, `ready/` (READY and probe streams) and the newest G to `<Worktree>/.state/realhost/`, then counts the VERDICT lines. |

Order: `00` → `Tu before` → `Tu after` → `P` → `B` (at most 5 valid attempts) → `S before` → `A` (as many runs) →
`S after` → `G` → `GR` (until both `exit=`) → `C`. Main runs full suites one at a time, so G starts only when Main's queue allows.

Trigger condition: Claude, Codex and DSH stop accepting input at the turn end. They report the end to agents only
after closing and archiving. In Claude's `execution.py` run(), `accepting = False` is set before `done`, and the record
stays `running` meanwhile. The window is the process shutdown (`_close`) plus the archive join. A send that arrived
in it was refused. The window is short, so B may need several runs.

MCP and plugin: the claude host configuration writes `.mcp.json` and `.claude/settings.local.json` (env only), plus
the project-scope hook plugin under `.claude/skills/`. `--mcp-config <project>/.mcp.json --strict-mcp-config` loads
exactly the graphtraj server without an approval, and no user connector (e.g. `claude.ai Claude Docs`). Claude Code
loads the hook plugin only in a trusted folder. Without it there is no PreToolUse association, so agents calls fail
with `authority-denied: No matching current native call association` (Main's 00 on 070b40a5). That is why Tu runs
once per project. 070b40a5's 00 also wrote `enabledMcpjsonServers` into each project's own settings.local.json. The
current steps no longer write it, and the strict `--mcp-config` makes it irrelevant.

Layout: projects and runs go under `/private/tmp/send-546/<before|after>/`, and READY/probe streams under
`/private/tmp/send-546/ready/`. Venvs, wheels, archive trees and suite outputs go under `<Harness>/tmp/546/`
(`G-latest` names the newest G). Pytest temp roots go under `$TMPDIR`.

Rehearsal: `zsh scripts/verify-546/rehearse.zsh <empty dir>`. It runs every step through the same entry Main uses.
- **This version:** `rehearsal/output.txt` covers these steps in order:
  - 00, which writes the role and prints `roles OK`;
  - B before trust, which STOPs at the gate;
  - Tu before and Tu after, then a simulated trust;
  - P, then a valid B (create, then send);
  - with the before project's `roles: {}` restored: P STOPs on the role check, and B gives `INVALID (create error
    invalid-config)` with exit 3, the attempt saved as `invalid-2`;
  - 00 again, which rewrites the role;
  - a valid B (`run-2`), A and C.

  drv546 summary also turns Main's real `/private/tmp/send-546/before/runs/run-1` stream into `INVALID (create error
  invalid-config)`. G and GR are unchanged since 070b40a5, so they were not re-run; their rehearsal is
  `rehearsal/output-G-070b40a5.txt`.
- **The stub (`stub_claude.py`, as `claude`) replaced:** every model answer and Claude Code's init record. In that
  record, `mcp_servers` comes from the real `--mcp-config` file; `plugins` and `plugin_warnings` are invented, in the
  untrusted form (builtins only plus `project-scope-suppressed-untrusted`) and the trusted form (with
  `graphtraj-claude-host`). The stub also replaced the agents status call and its result, which are invented:
  authority-denied when untrusted, success when trusted, and no MCP server is called. It replaced B and A's Main as
  well. The stub reads the project's real `.graphtraj/roles.yml`. With no role, it returns the product's real
  create error JSON. With the role, it invents a create success, one send (submitted) and a wait. No child exists, so
  a valid attempt prints `NOT-HIT`. Tu's dialog is not shown. The user's 'Yes,
  proceed' is simulated by creating `<project>/.stub-trusted`, a file only the stub reads.
- **Real:** steps.zsh and both phase venvs, built from git archive of the exact commits (the fallback flag is
  False/True). Also real: `graphtraj setup`, the claude host configuration, drv546.py gate/probe/summary parsing, the
  gate STOP, and B/A's exact argv. On 070b40a5, G's guards, venvs, temp root and background runner were real too.
  There, G ran a subset through the same venvs and temp root:
  GraphTraj `tests/test_agents_configuration_recorded.py` (its `project` fixture; agents create/wait/status through
  GraphTraj) and graftling `tests/test_agent_control.py`, `tests/test_claude_send_closing_546.py` (real ClaudeDriver
  with the CLI fixture) and `tests/test_dsh_standalone_child.py`. GR's classification and C were real too. Only the
  full shard runner was not rehearsed, because the subset uses plain pytest, as in 531.
