# verify-535 — interactive Codex Main: agents messages shown as who + Markdown

Baseline = GraphTraj `8ac35e31` (dev) + graftling `f67d147a` (dev, 533's `notice_text`). Candidate = this Worktree's
HEAD (535 changes exactly `src/graphtraj/runtimes/codex/display_hook.py`, `src/graphtraj/runtimes/codex/host_events.py`,
`tests/codex_stdio_peer.py`, `tests/test_codex_agent_display.py`, `tests/test_codex_main_root_notice_401.py`, `tests/test_current_host_events.py`, `tests/test_mcp_host_tools.py`; B
checks that against 8ac35e31) + graftling `87d83d68` (`GLC`) of the untracked clone `.scratch/graftling` (git dir
`.scratch/graftling-git`, branch `agent/535-codex-main-agents-message-display`, bundle
`.scratch/graftling-535.bundle`).

The change: a pushed notice reaches the interactive Codex Main as the tool output of graftling's
`CodexAppServer.send_host_event`. Before, that output was the event's JSON; GraphTraj's `send_event` now passes
`notice_text(event)` (533's Runtime-independent text) through send_host_event's new optional `text`. The event and
every record are unchanged.

Main runs `zsh <abs path>/steps.zsh <step>`; every step prints the next command with real values.

| Step | Who | Dialog | What |
|---|---|---|---|
| 00 | Main | none | zsh, `codex --version`, isolated `/private/tmp/vproject-535` (own git, graphtraj setup by production's graphtraj, read only; no AGENTS.md at or above), `codex login status`, one `codex exec -m gpt-6-luna` answer naming its model |
| B0 | Main | none | baseline wheels from `git archive` of both exact commits; venv `<Harness>/tmp/535/base/venv` |
| T | USER | exactly one: Codex's own 'Do you trust the contents of this directory?' → Yes (Codex records it in the user's Codex config itself; the script writes nothing there) | `cd /private/tmp/vproject-535 && codex -m gpt-6-luna`, no prompt, `/exit`; runs before the project's `.codex` exists |
| Vb | Main, then USER | USER: exactly one: Codex's hook review of the project's `.codex/hooks.json` → approve | links `<Harness>/tmp/535/active` → base; writes the isolated project's own `.codex/config.toml` (graphtraj MCP, tools pre-approved) and `.codex/hooks.json` (SessionStart = `graphtraj.runtimes.codex.stop_hook`, the Main claim the push needs; no Stop completion checker (Task 541), no SessionEnd; the UI-only display hook on PostToolUse/Stop; `main_start535.py` deleted); isolation also STOPs on CLAUDE.md/CLAUDE.local.md at or above the project; removes only `/private/tmp/vproject-535/.graphtraj/runner/main-sessions` (printed); picks a fresh child name `n535HHMM` (saved in `child-name`, used by the prompt and Vr); writes ONE role `claude` (roles535.py, exactly 533's: connection claude/anthropic/opus-5_5, effort high, permission_mode auto), so the child runs no Codex hook (a Codex child claimed Main in tries 1-2, Task 540); resolves it without a model (STOP otherwise); prints the USER command and prompt; USER takes the BEFORE screenshots |
| Vr | Main | none | takes the Main session from the last `codex:SessionStart` claim in the project's `continuity.jsonl` after the newest Vb/V start stamp, and reads the rollout under `~/.codex/sessions` whose session_meta id is that session (read only; FAIL if none): each pushed notice PASS/FAIL (no escaped JSON, no permissions/session_id/terminal_confirmed, child + execution id present, Markdown lines) |
| B | Main | none | exact 535 GraphTraj diff check; candidate wheels/venv `<Harness>/tmp/535/cand`; prints whether send_host_event takes `text` |
| V | Main, then USER | USER: none expected (same hooks.json as Vb) | as Vb with `active` → cand; AFTER screenshots |
| P | USER, then Main | none (hooks.json unchanged) | delegation-cell probe (542 Q2 F2, Q4; script only, `probe535.py send`): USER first runs `cd /private/tmp/vproject-535 && codex -m gpt-6-luna`, types `Reply only READY-535 and wait.` and leaves Codex idle; P takes the Main thread from the last `codex:SessionStart` claim and sends ONE `turn/start {threadId, input: [], toolOutput: {name: send_message_to_thread, namespace: codex_app, output: <codex_delegation> wrapper}}` (source `n535probe`, a notice_text-shaped Markdown body, `& < >` escaped) through the active venv's `CodexAppServer.call` over `codex app-server proxy`; prints the result, the PASS criterion (`• Sent by Codex from task n535probe` with rendered Markdown) and the screenshot path `realhost/probe.png`; USER notes the model's reaction, then `/exit` |
| Pr | Main | none | read only (`probe535.py read`): the Main rollout's records from the probe's function_call_output on (what the model saw and its reply) |
| G / GR | Main | none | full suites (graphtraj 6 shards, graftling) against the candidate, background; pytest temp roots under `TMPDIR` outside the Harness; GR reads them |

Nothing is written to `~/.codex`, the Codex install, dotfiles, `.venv-runtime` or the Harness's `.codex`.

`rehearse.zsh <empty dir>` runs 00, B0, T, Vb, B, V (stub `codex`; stand-ins with the real layout: production roles with no luna preset, a catalog with the opus connection), checks hooks.json is exactly SessionStart(stop_hook) + PostToolUse/Stop(display), Vr on the Main's rollout
holding what each venv's REAL `send_event` writes, next to a NEWER decoy rollout of the same cwd (`fake_push535.py`: baseline → FAIL, candidate → PASS; no claim → FAIL) and G
(real limited pytest runs); its output is `rehearsal-output.txt`.
