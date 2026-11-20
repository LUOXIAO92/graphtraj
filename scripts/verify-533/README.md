# verify-533 — Claude Code Main: agents messages shown as who + Markdown

Candidates: GraphTraj = this Worktree's HEAD (533 changes exactly `src/graphtraj/runtimes/claude/host.py` and
`tests/test_claude_main_notice_text_533.py`; B checks that against 27029f96), graftling = `f67d147a` on branch `agent/533-claude-main-agents-message-display` of the untracked clone
`.scratch/graftling` (git dir `.scratch/graftling-git`; bundle `.scratch/graftling-533.bundle`, requires 4a002129 = v0.6.2, sha256 a1f694a7…; `.state` refused the
bundle's lock file).

Main runs `zsh <abs path>/steps.zsh <step>`; every step prints the next command with real values.

| Step | Who | Dialog | What |
|---|---|---|---|
| 00 | Main | none | zsh, `claude --version` >= 2.1.314 (else STOP), isolated `/private/tmp/vproject-533` (own git, graphtraj setup by production's graphtraj, read only), `claude -p` answer check (model, login, no Harness AGENTS.md) |
| B | Main | none | wheels from `git archive` of both exact commits into `<Harness>/tmp/533/wheels`; scratch venv `<Harness>/tmp/533/venv` |
| V | Main, then USER | USER: none expected (folder trusted in try 1; if a folder/MCP/hooks trust dialog still appears, choose its affirmative option and report the title) | candidate `configuration --write --claude` into the isolated project; checks `enabledMcpjsonServers` holds graphtraj; writes ONE role `claude` (connection claude/anthropic/opus-5_5, effort low, permission_mode auto; roles533.py) and resolves it without launching a model; prints the USER command and the prompt (create with runtime + name only); USER takes two screenshots |
| Vr | Main | none | reads the newest isolated Main transcript; PASS/FAIL observables of the pushed notice text (sender/event/ids, no `permissions`, no escaped JSON, Markdown lines) and of the agents create/send calls |
| G | Main | none | graphtraj (6 shards) and graftling full suites in the background against the candidates; pytest temp roots under `TMPDIR` (outside the Harness; printed) |
| GR | Main | none | read only: tails and FAILED/ERROR lines of both suites |

Placed rows are not in the transcript (Claude never reads them): the screenshots are the evidence of the display.
`rehearse.zsh <empty dir>` runs 00, B, V, Vr (new text PASS, old JSON FAIL) and G (real limited pytest runs) with a
stub `claude`; its output is `rehearsal-output.txt`.
