# verify-549: does an MCP progressive-disclosure result appear twice?

Steps: `zsh scripts/verify-549/steps.zsh 00 | X | XU | P | D | R | C`. The header of steps.zsh says what each step does, which dialogs to expect (none) and its time limit.

## What the server returns (step S, GraphTraj dev 500e1f17 + graftling dev 6794ce0, no host)

Every call returns one `content` text block and one `structuredContent` object. Both hold the same document, so each `tools/call` result carries the document twice by design: once as YAML text and once as JSON. src/graphtraj/interfaces/mcp.py:184-193 returns the YAML from `yaml.safe_dump(document)`. graftling src/graftling/mcp.py:335-336 returns the JSON from `json.dumps(document)`. Inside each copy, every field occurs once (rehearsal/00.log). The result shape has not changed since it was introduced. `git log -L` on the result block shows only 81b2fc21, 7f53b98f and d582cf94. graftling's `git log -S structuredContent` shows only 9a12d9a.

## Host by host (installed versions, source evidence; real-host runs are steps X/P/D)

| Host | Model input | User view | Evidence |
|---|---|---|---|
| Codex 0.171.0 TUI | JSON of `structuredContent` only, so once | card shows `content` only, so once | protocol/src/models.rs:2487-2505 @ rust-v0.171.0 (ccf9be8c); tui mcp_result.rs:46-110 (543, bb5b9c62); user observation 2026-11-21 16:45 (not reproduced) |
| Codex 0.171.0 `codex exec` human | same as TUI, once | prints only `mcp: server/tool started` and `mcp: server/tool (completed)`, never the result, so 0 times. The model's final reply goes to stderr (:103-110). When stdout or stderr is not a terminal, the reply is also printed to stdout (:398-425, :535-541) | exec/src/event_processor_with_human_output.rs @ rust-v0.171.0 |
| Codex 0.171.0 `codex exec --json` | same, once | the `item.completed` event of type `mcp_tool_call` holds `result.content` (the server's text) and `result.structured_content` (the same document), so the document appears twice in one event | exec/src/exec_events.rs:262-276 (`McpToolCallItemResult {content, _meta, structured_content}`), event_processor_with_jsonl_output.rs:213-235 @ rust-v0.171.0 |
| Pi 1.4.0 | `content` blocks only, once. `structuredContent` goes only to codemode scripts and `tool_result` hooks | the renderer draws `getTextOutput(result)`, the same content text, so once | dist/extensions/mcp/tools.js:198-215 (convertMcpResult), :278-300 (renderResult); dist/core/agent-session.js:348-381 |
| DSH 0.2.2-alpha.2 | tool/result message `content` = `output.render(value)` = `extractText(value.content)`, once | the client UI packages never read `structuredContent` (grep finds no match) | dsh-mcp-client/lib/index.js:198-218, 228-240; dsh-tools/lib/pipeline.js:202-205, 710-735 |
| Claude Code (Leader, Main) | JSON of `structuredContent`, once | once | Leader and Main observations |

Classification: no host gives the model, or shows the user, a field twice. The only place where the same document appears twice is the Codex `--json` event stream. There, `result.content` and `result.structured_content` are two fields of Codex's own event protocol, one for each part of the MCP result. GraphTraj does not print anything twice. Separately, a human `codex exec` whose output is piped or captured prints the model's final reply twice, once to stderr and once to stdout. That is the model's own reply, not the tool result.

## Rehearsal (from an empty directory, inside the Engineer sandbox)

- 00: venv, project, S and the DSH patch all completed. The one-line host prompts failed at their first access to the user's host homes: Codex with `Failed to read config file ~/.codex/config.toml: Operation not permitted`; Pi with `EPERM ... ~/.pi/agent/settings.json.lock`; DSH with `rc=1`. These are sandbox limits. Main's runs are not affected.
- R: host-shaped fixtures built from S's real results, run through the same counter: Codex rollout and Pi session show once; the Codex exec `--json` event shows once in `result.content` plus once in `structured_content`; human output prints no field; a constructed defect shape (text plus JSON in one model output) shows TWICE.
- X rollout selection (`rehearse-x.zsh`, log rehearsal/rehearse-x.log): a stub `codex` writes its two runs' ids, one in a human stderr header `session id:` with a bold key and one in a `thread.started` event, plus a rollout for each id. It also writes a newer decoy rollout with another id, standing in for the user's interactive Codex session. Step X copied only the two rollouts for its own ids, printed both `codex resume <id>` lines and did not copy the decoy. When the output carries no id, both runs print STOP and nothing is copied.
- Real Codex: step X reads `~/.codex/sessions` only for the two ids of its own `codex exec` runs, and those runs write their rollouts there as usual. Codex also starts the other MCP servers from the user's global `~/.codex/config.toml`; only `graphtraj` is overridden.
- X, P, D were not run against real hosts by the Engineer. They call paid models with the user's logins, and the permission classifier denied running X in this session.
