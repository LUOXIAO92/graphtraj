# verify-550: weak agent (Haiku 5.5) vs. concept-clarification, strong simulated user (Fable 5.2), Sonnet audit

Main runs from this Worktree in Main's Bash: `zsh scripts/verify-550/steps.zsh <step>`. No step needs user action.
Shape A (Main's decision ~16:55): three headless `claude -p` roles and a plain relay script. design.md is the
answer key and the single source of every fixed text and scenario file (drv550.py parses it).

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Version line (zsh, git, claude, production graphtraj/graftling). `project settings: ...` (isolated project built). `CHECK 550 READY-550-U/A/S: PASS` with `init model: claude-fable-5-2 / claude-sonnet-5-5 / claude-haiku-5-5` and `auth source (init apiKeySource)`. `probe (a)`: tasks describe called and a Read result holds the guide heading. `probe (b)`: canary Read in BASE/u refused and the token absent. `probe (c)`: init tools without WebSearch/WebFetch/Bash/agents. Then S's exact argv, settings and MCP config, and `efforts: U high, S <x>, A <y>`. |
| `R <S1\|S2\|S3\|S4\|all>` | none | `S# started (pid N)`. In `BASE/logs/R-S#.out` / `logs/S#/driver.log`: one `turn NN S/U ... model=...` line per turn, then `END {"exchanges": n, "done": true/false, "error": null}`. |
| `W` | none | Per scenario `run: ended {...}` or `running` + last driver line. After A: `audit: AUDIT: CLEAN/CHEATED/UNCLEAR`. |
| `A <S#\|all>` | none | `S# audit started`. `logs/S#/audit-inputs.txt` lists the audit folder (S and U stream-json of every turn, S flags/settings/MCP config, S's final files, design.md). `logs/S#/audit.md` first line is one of `AUDIT: CLEAN`, `AUDIT: CHEATED`, `AUDIT: UNCLEAR` (W and C print it). |
| `C` | none | Per scenario: copied to `<Worktree>/.state/realhost/S#/` (`logs/` + `S-final-files/`). `K0a: first tasks describe ... \| first Edit/Write ... \| first question ...`. `K0b supporting list` (each S tool path outside its ws; the guide marked `(allowed)`). `audit.md first line`. |

Order: `00` → `R all` → `W` (repeat until all ended) → `A all` → `W` → `C`.

Layout under `BASE=/private/tmp/cc-550`:
- `project/`: own git, production `graphtraj setup` and `claude.host configuration --write`, read only.
- `project/runs/S#/ws`: S's cwd. It holds only the scenario's files. S1's CONTEXT.md is copied from the Harness at run time.
- `u/S#`: U's cwd. It is empty; the hidden block is only U's `--append-system-prompt`, and the logs show it as a placeholder.
- `audit/S#`: the auditor's cwd.
- `logs/S#`: every stream-json, argv, stdin text, driver.log, status.json, u-sources.txt and audit.md.

S's isolation (drv550.py `argv`/`s_files`) uses these flags:
- `--tools Read,Edit,Write,Glob,Grep`, `--disallowedTools Bash,WebSearch,WebFetch,mcp__graphtraj__agents` and `--allowedTools mcp__graphtraj__tasks`.
- `--strict-mcp-config --mcp-config` pointing to the product's stdio `graphtraj-mcp`. The project's own `.mcp.json` host refuses any cwd other than the project.
- `--permission-mode acceptEdits` and `--setting-sources project`.
- `--settings`, which denies Read of BASE/u, audit and logs, of `~/.claude` and of the Harness parent tree except the concept-clarification manual directory. It also denies Edit/Write in that manual directory and sets `blockReadsOutsideWorkingDirectories`.
- `--add-dir <manual dir>`. `tasks describe` returns a `manual_ref` path, and S must Read that file.

Every child process gets a clean environment (HOME, USER, PATH, TERM, TMPDIR, LANG), so none inherits the caller's `GRAPHTRAJ_CLI_CONNECTION`.

Rehearsal: `zsh scripts/verify-550/rehearse.zsh <empty dir>`. Output: `rehearsal/output.txt`, with the S1 copy in `rehearsal/realhost-S1/`.
- **The stub (`stub_claude.py`) replaced:** every model and Claude Code's permission enforcement. That covers the READY answers, S's questions and edits, U's replies and the audit verdict. The canary refusal in probe (b) is the stub's text: no real deny rule was tested.
- **Real:** steps.zsh, the drv550.py relay with `--resume` and the verbatim check, the design.md parse and scenario files, and the production graphtraj setup and host configuration. Also real: S's `tasks describe concept-clarification` through the production `graphtraj-mcp`, and the Reads of the guide and the ws files. The audit folder and C's copy, K0a output and path list are real too.
