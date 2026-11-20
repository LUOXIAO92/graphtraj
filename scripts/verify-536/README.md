# verify-536 — Pi Main: agents messages shown as who + Markdown

BASELINE = GraphTraj `8ac35e31` + graftling `f67d147a`. CANDIDATE = this Worktree's HEAD (536 changes exactly
`src/graphtraj/runtimes/native_entry.py`, `src/graphtraj/runtimes/pi/extension.mjs`,
`tests/test_pi_main_notice_display_536.py`; B checks that against 8ac35e31) + graftling `fc081a3f` on branch
`agent/536-pi-main-agents-message-display` of the untracked clone `.scratch/graftling` (git dir
`.scratch/graftling-git`; bundle `.scratch/graftling-536.bundle`, requires f67d147a).

Main runs `zsh <abs path>/steps.zsh <step>`; every step prints the next command with real values.

| Step | Who | Dialog | What |
|---|---|---|---|
| 00 | Main | none | zsh, `pi --version`, isolated `/private/tmp/vproject-536` (own git, graphtraj setup by production's graphtraj, read only), each host answers one line: Main host `pi --print` (deepseek/deepseek-flash as verify-444/514; no extension, so it claims no Main; STOP without a `READY-536 <model>` line) and child host `claude -p` (claude-opus-5-5, verify-533's ask_model with `verify-common/claude_isolation.py` prompt/check: model, login, no Harness AGENTS.md); both bounded to 120 s, output under the realhost folder |
| B | Main | none | wheels from `git archive` of the exact commits into `<Harness>/tmp/536/wheels/{baseline,candidate}`; venvs `<Harness>/tmp/536/venv-{baseline,candidate}`; prints whether each Pi extension has the notice renderer |
| V0 | Main, then USER | USER: none expected (a Pi folder/extension trust prompt: choose its affirmative option and report the title) | BEFORE on BASELINE: writes ONE child role `claude` (connection claude/anthropic/opus-5_5, effort high, permission_mode auto — production's opus_coding_team.engineer; `../verify-533/roles533.py`) and resolves it without a model; prints the USER `pi --session-dir … --extension …` command and the prompt (create with runtime + name, one Markdown send); USER takes two screenshots |
| V1 | Main, then USER | as V0 | the same AFTER on CANDIDATE |
| Vr | Main | none | reads the V0 and V1 Pi Session files (`--session-dir` under the realhost folder): per `graphtraj:main-notice`, model input has the title with execution id, no escaped JSON/`permissions`, display details (`sender`, `event`, `body`) present. Expect V0 FAIL, V1 PASS |
| G | Main | none | graphtraj (6 shards) and graftling full suites in the background; pytest temp roots under `TMPDIR` (outside the Harness; printed) |
| GR | Main | none | read only: tails and FAILED/ERROR lines of both suites |

The child role resolution runs in V0/V1 (with that venv), not 00, because it needs the venv's graphtraj.
The drawing itself is not in the Session file (Pi draws from `details`): the screenshots are the display evidence.
`rehearse.zsh <empty dir>` runs 00, B, V0, V1 with a stub `pi`, Vr on Session rows made from GraphTraj's real queue and
notices native entry, and G (real limited pytest runs with the real `pi` and node); output in `rehearsal-output.txt`.
