# verify-551: tools and MCP of Task-free children created through `agents create`

Main runs these from this Worktree in Main's Bash: `zsh scripts/verify-551/steps.zsh <step>`. The header of
steps.zsh says what each step does. Everything the script creates lives under `BASE=/private/tmp/agents-551`,
outside the Harness. No step writes `~/.claude`, `~/.codex`, `~/.pi`, a dotfile, the Harness or `.venv-runtime`.
The only exception is each host's normal session file for its own run.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Versions, including `in-use installation (BEFORE): graphtraj ... graftling 0.6.2`. Four `READY-551` lines: claude `claude-sonnet-5-5`, codex `gpt-6-luna`, pi and dsh `deepseek-flash`. `CHECK 551 role <claude\|codex\|pi\|dsh>: PASS`, resolved without a model by the Task-free driver's own `AdapterDriver.prepare`. `CHECK 551 tasks probe: PASS`, with the manual_ref and its first heading. `CHECK 551 Claude parent gate: PASS`: the init of the project's `.mcp.json` lists `graphtraj` connected and `mcp__graphtraj__agents`. |
| `U` | one, only when 00 asks for it: "Do you trust the files in this folder?" → **Yes, proceed**, then `/exit` | 00 again passes the gate. |
| `B <claude\|codex\|pi\|dsh\|all>` | none (headless; the parent denies any child approval request and prints `REQUEST-551`) | Per Runtime: `summary.txt` in `runs/B-<rt>-<time>/`. `parent create result` (agent or exact error); `self-report TOOLS-551 / MCP-551 / TASKS-551 / DESCRIBE-551 / READ-551` (the child model's own words); and, from the child's own records, `RECORD init` (native tools and mcp_servers), `RECORD launch flags`, `RECORD tool calls by name`, `RECORD tasks calls`, `RECORD manual guide.md reads`, `a tool result holds the manual heading: YES/NO`. |

Order: `00` → (`U`, only if 00 says so) → `B all`. Steps `A0` (candidate installation built from the
GraphTraj and graftling branches), `A` (B again, plus one manual deny and one beyond-host request), `G` and `GR`
(full suite, modelled on verify-531 G/GR, with the graftling branch) are added once the Leader names the commits.

How B works:
- The parent is a headless Claude Main: `claude -p` with `--model claude-sonnet-5-5`, run in the isolated project
  with its own `.mcp.json` (written by `graphtraj.runtimes.claude.host configuration --write`). It passes
  `--strict-mcp-config` and `--allowedTools mcp__graphtraj__agents` and is a verified native Main Session. A plain
  MCP client is refused with `authority-unavailable`, so the parent has to be a real host.
- The child is created by GraphTraj's Task-free driver in that host. Its Runtime comes from one inline role per
  Runtime in `.graphtraj/roles.yml` (prep551.py). Claude uses `claude-opus-5-5` effort low and Codex uses
  `gpt-6-luna`. Pi uses `deepseek/deepseek-flash`, with srt from `~/agents-pi-sandbox/pi-sandbox.env` as in
  verify-513. DSH uses `deepseek-flash`. Pi and DSH read the key from `DEEPSEEK_API_KEY`, which comes from
  `~/.zshrc` and is never printed.
- The child's instruction is in steps.zsh `child_instruction`. It lists its tools and MCP servers, calls `tasks`
  discover, then describe `concept-clarification`, then reads the manual_ref with its file tool.
- Evidence comes from two sources: the parent's stream-json, and every project record changed during the run.
  The Codex child's rollout is copied only by the session id found in those records.

Rehearsal: `zsh scripts/verify-551/rehearse.zsh <empty dir> [steps...]` (default `00` and `B claude`).
- **The stub (`stub551.py`) replaced:** every host and model. In B it also replaced the parent's create and wait
  results and the child's record. These are fabricated, so the rehearsal shows only that the plumbing works.
- **Real:** steps.zsh and the in-use installation's `graphtraj setup` and Claude host configuration. Also real: the
  four roles resolved by `AdapterDriver.prepare`, which refuses them under stubs or without keys (see the output),
  the `tasks` discover/describe probe through the in-use `graphtraj-mcp`, collect, and sum551.py.
