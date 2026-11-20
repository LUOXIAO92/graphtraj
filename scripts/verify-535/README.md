# verify-535 — interactive Codex Main: agents messages shown as who + Markdown

Baseline = GraphTraj `8ac35e31` (dev) + graftling `f67d147a` (dev, 533's `notice_text`). Candidate = this Worktree's
HEAD + `GLC` of the untracked clone `.scratch/graftling` (git dir `.scratch/graftling-git`, branch
`agent/535-codex-main-agents-message-display`).

Main runs `zsh <abs path>/steps.zsh <step>`; every step prints the next command with real values.

| Step | Who | Dialog | What |
|---|---|---|---|
| 00 | Main | none | zsh, `codex --version`, isolated `/private/tmp/vproject-535` (own git, graphtraj setup by production's graphtraj, read only; no AGENTS.md at or above), `codex login status`, one `codex exec -m gpt-6-luna` answer naming its model |
| B0 | Main | none | baseline wheels from `git archive` of both exact commits; venv `<Harness>/tmp/535/base/venv` |
| T | USER | exactly one: Codex's own 'Do you trust the contents of this directory?' → Yes (Codex records it in the user's Codex config itself; the script writes nothing there) | `cd /private/tmp/vproject-535 && codex -m gpt-6-luna`, no prompt, `/exit`; runs before the project's `.codex` exists |
| Vb | Main, then USER | USER: at most one: the hook review of the project's `.codex/hooks.json` → approve (or none) | links `<Harness>/tmp/535/active` → base; writes the isolated project's own `.codex/config.toml` (graphtraj MCP, tools pre-approved) and `.codex/hooks.json` (GraphTraj's Codex Main hooks + the UI-only display hook); copies ONE production preset (codex, gpt-6-luna; production roles only read) as role `codex` and resolves it without a model; prints the USER command and prompt; USER takes the BEFORE screenshots |
| Vr | Main | none | reads the newest rollout of the isolated project under `~/.codex/sessions` (read only): each pushed notice PASS/FAIL (no escaped JSON, no permissions/session_id/terminal_confirmed, child + execution id present, Markdown lines) |
| B | Main | none | candidate wheels/venv `<Harness>/tmp/535/cand` (second delivery sets `GLC`) |
| V | Main, then USER | USER: none expected (same hooks.json as Vb) | as Vb with `active` → cand; AFTER screenshots |
| G / GR | Main | none | full suites (graphtraj 6 shards, graftling) against the candidate, background; pytest temp roots under `TMPDIR` outside the Harness; GR reads them |

Nothing is written to `~/.codex`, the Codex install, dotfiles, `.venv-runtime` or the Harness's `.codex`.
