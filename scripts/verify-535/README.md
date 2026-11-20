# verify-535 — interactive Codex Main: agents messages shown as who + Markdown

Baseline = GraphTraj `8ac35e31` (dev) + graftling `f67d147a` (dev, 533's `notice_text`). Candidate = this Worktree's
HEAD (535 changes exactly `src/graphtraj/runtimes/codex/host_events.py`, `tests/codex_stdio_peer.py`,
`tests/test_codex_main_root_notice_401.py`, `tests/test_current_host_events.py`, `tests/test_mcp_host_tools.py`; B
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
| Vb | Main, then USER | USER: at most one: the hook review of the project's `.codex/hooks.json` → approve (or none) | links `<Harness>/tmp/535/active` → base; writes the isolated project's own `.codex/config.toml` (graphtraj MCP, tools pre-approved) and `.codex/hooks.json` (GraphTraj's Codex Main hooks + the UI-only display hook); writes ONE role `codex` (roles535.py): prints every production preset with its resolution and the user's catalog codex models (both read only), takes gpt-6-luna's catalog reference (provider openai preferred), copies the production preset astra_coding_team.engineer without instructions/prompts/reports, sets its connection to that reference and keeps its effort if luna supports it, else high; resolves it without a model (STOP with the printed reason otherwise); prints the USER command and prompt; USER takes the BEFORE screenshots |
| Vr | Main | none | reads the newest rollout of the isolated project under `~/.codex/sessions` (read only): each pushed notice PASS/FAIL (no escaped JSON, no permissions/session_id/terminal_confirmed, child + execution id present, Markdown lines) |
| B | Main | none | exact 535 GraphTraj diff check; candidate wheels/venv `<Harness>/tmp/535/cand`; prints whether send_host_event takes `text` |
| V | Main, then USER | USER: none expected (same hooks.json as Vb) | as Vb with `active` → cand; AFTER screenshots |
| G / GR | Main | none | full suites (graphtraj 6 shards, graftling) against the candidate, background; pytest temp roots under `TMPDIR` outside the Harness; GR reads them |

Nothing is written to `~/.codex`, the Codex install, dotfiles, `.venv-runtime` or the Harness's `.codex`.

`rehearse.zsh <empty dir>` runs 00, B0, T, Vb, B, V (stub `codex`; stand-ins with the real layout: production roles with NO luna preset, a catalog holding codex/openai/gpt-6-luna; Vb again without luna in the catalog must STOP with the reason), Vr on rollouts
holding what each venv's REAL `send_event` writes (`fake_push535.py`: baseline → FAIL, candidate → PASS) and G
(real limited pytest runs); its output is `rehearsal-output.txt`.
