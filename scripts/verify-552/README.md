# verify-552: concept-clarification across four agents under test (Sonnet, Haiku, DSH deepseek-flash, Codex gpt-6-luna)

Main runs from this Worktree in Main's own Bash, which must not itself be inside a Seatbelt sandbox (see "Seatbelt" below): `zsh scripts/verify-552/steps.zsh <step>`. No step has a dialog. The answer key is `scripts/verify-550/design.md` (unchanged). `design-552.md` holds the 552 differences. `drv552.py` parses both, and through `drv550.design()` it reuses 550's parse.

| step | dialog | observable that proves it |
|---|---|---|
| `00` | none | Version lines (claude, codex 0.171.0, dsh 0.2.2-alpha.2, zstd, production graphtraj/graftling). `claude host configuration written` and `project settings: ...`. `codex: Logged in ...` and `DEEPSEEK_API_KEY: set`. `CHECK 552 READY-552-U/A: PASS`, each with `init model`. Seven `codex sandbox ...: PASS` lines and `CHECK 552 codex sandbox: PASS`. Per agent: `probe (a)`, four `probe (b)` lines, `probe (c)` lines, `probe (d) READY` and `CHECK 552 READY-552-S-<agent>: PASS`, followed by the agent's exact argv/config (for dsh, also the patch and the outer Seatbelt profile). `summary`: `<agent>: PASS (R allowed)`, or FAIL. A FAIL blocks that agent from R. Main reports it to the Leader. |
| `F` | none | `S# research started`. In W: `research S#: done \| ... web_search_requests N \| WebSearch/WebFetch calls M`. Output: `BASE/u/research/S#.md`. |
| `R <agent\|all> <S#\|all> [runs=3] [cap=8]` | none | `batch started`. `BASE/logs/R-batch-*.out` lists the run ids and then prints `<run> ended rc=0` for each. Each `logs/<run>/driver.log` has one `turn NN S/<agent> ... model=... web=0` or `turn NN U ...` line per turn and ends with `END {...}`. |
| `W` | none | Per run: `ended {...} \| audit: AUDIT: ...`, `running \| <last driver line>` or `queued`. Then `runs: N known, E ended, A audited` and the next command. |
| `A <agent\|all\|run id> [cap=8]` | none | `audits started`. `logs/<run>/audit-inputs.txt` lists the audit folder. The first line of `logs/<run>/audit.md` is `AUDIT: CLEAN`, `AUDIT: CHEATED` or `AUDIT: UNCLEAR`. |
| `C` | none | One line per run: `<run>: copied -> <Worktree>/.state/realhost/<agent>/<S#>-r<k> \| ok \| audit: ...`. Each run directory holds `digest.md`, `logs/` (all native records; codex `rollouts/`), `S-final-files/` and `audit.md`; dsh runs also hold `dsh-session-store/`. Also copied: `u-research/`, `step-logs/` (00/F logs, `probes-<agent>.txt`) and `runs-table.md`. |

Order: `00` → `F` → `W` (until 4 notes exist) → `R all all` → `W` (repeat) → `A all` → `W` → `C`. Main saves the raw output of each step.

## Layout (BASE=/private/tmp/cc-552)

- `project/`: own git repository, set up with production `graphtraj setup` and `claude.host configuration --write` (as in 550).
- `project/runs/<run>/ws`: S's cwd and workspace.
- `u/<run>`: U's cwd. `u/research/S#.md`: F's notes. `u/ready/`: canaries.
- `audit/<run>`: A's cwd and the audit folder.
- `dsh/<run>/{home,agents-home}`: DSH_HOME and DSH_AGENTS_HOME of a dsh run.
- `bin/mcp_tasks_only.py`: copy of the relay.
- `logs/<run>`: every native record, argv, stdin text, driver.log, status.json, u-sources.txt and audit.md.

## How each S is confined (details and sources: engineer.md)

| | sonnet / haiku (`claude -p`) | codex (`codex exec --json`, `exec resume <id>`) | dsh (`dsh --profile headless --json`, `--session-id <id>`) |
|---|---|---|---|
| (i) no web, no network | `--tools Read,Edit,Write,Glob,Grep` and `--disallowedTools Bash,WebSearch,WebFetch,...` (550) | `-c web_search="disabled"`, permission profile `s552` with `network={enabled=false}`, and `--disable` for multi_agent, apps, plugins, web_search_request, standalone_web_search, ... | the patch disables `tool-web`, `web`, `web-search-deepseek`, `web-deepseek-api`, `web-fetch-http`, `tool-bash`, `tool-jobs`, the subagent/workflow tools and `tool-skill`. S has no shell. |
| (ii) reads | 550's `--settings` deny list, plus a deny of every sibling run dir (R creates all run dirs before any S starts), plus `blockReadsOutsideWorkingDirectories` | profile `s552` is a restricted filesystem policy: only `:minimal` (platform files), the ws (write) and the guide directory (read). `--ignore-user-config` drops the user's other MCP servers, hooks and profiles. | DSH's file tools do not confine reads (dsh-fs-sandbox README). So the whole dsh process runs under `sandbox-exec -f logs/<run>/dsh.sb`, which denies reads of BASE/u, logs, audit, project/runs, dsh, the workspace tree containing the Harness, ~/.claude, ~/.codex, ~/.dsh, ~/.agents and ~/.pi. It re-allows reads of the own ws, own dsh dir, `$H/.venv-runtime` (the production install that the MCP child runs from; it holds the guide) and BASE/bin. |
| (iii) tasks only | `--disallowedTools mcp__graphtraj__agents` | `mcp_servers.graphtraj.enabled_tools=["tasks"]` | `mcp_tasks_only.py`: a stdio relay in front of the production `graphtraj-mcp` that drops `agents` from `tools/list` and refuses calls to it |
| (iv) own ws | cwd + `acceptEdits` | profile grants the ws `write` | `--permission-mode workspace-write` |

## Rehearsal (`zsh scripts/verify-552/rehearse.zsh <empty dir>`, output in `rehearsal/`)

It ran from an empty directory under `$TMPDIR`. Harness `tmp/552/` is not writable in the Engineer sandbox. It runs the same entry Main uses (`zsh steps.zsh <step>`) for every step: usage, 00, F, W, R all all 1 8 (16 runs), W, A all, W, C. Saved files: `rehearsal/output.txt`, `rehearsal/runs-table.md`, `rehearsal/realhost-codex-S1-r1/` and `rehearsal/realhost-dsh-S2-r1/`.

- **Stub (`stub552.py`, first on PATH):** every model; `claude`, `codex` and `dsh` themselves; and their permission enforcement. That includes the probe refusals, `curl` failing, Codex's Seatbelt in `codex sandbox`, the codex rollout content (`turn_context` with a stub `permission_profile`) and the outer `sandbox-exec`, which runs dsh WITHOUT applying the profile. Every refusal text in the rehearsal ends in `(stub)`. No deny rule, Seatbelt profile or network block was tested by the rehearsal.
- **Real in the rehearsal:**
  - steps.zsh and drv552.py, including the relay loop with resume ids for all three hosts and the 550/552 design parse. `texts` confirms the replaced U sentence, the `RESEARCH NOTES:` ending and the 3 auditor additions.
  - The production `graphtraj setup` and Claude host configuration.
  - Each S's `tasks describe concept-clarification` as a real tools/call to the configured server: the production `graphtraj-mcp` for claude and codex; for dsh, the real `mcp_tasks_only.py` relay in front of it.
  - The Reads of the guide and the ws files, and S's edits.
  - The dsh session log, which is real zstd. Its `request/header.tools` lists the relay's real `tools/list` answer, `mcp__graphtraj__tasks` only.
  - The codex rollout lookup by thread id: a decoy rollout of another session was not copied.
  - Every audit folder, C's copy, the digests and the table.
- **Real, outside the stubbed rehearsal (Engineer, no paid model):**
  1. Real dsh 0.2.2-alpha.2 booted headless with this exact patch, a fake key and no network (`rehearsal/real-dsh-boot-*`). All plugins loaded, and the MCP row (`failOnStartupError: true`) connected through the relay to production `graphtraj-mcp`. The session log's `request/header` recorded `tools` = create_goal, edit, get_goal, glob, grep, list_mcp_resource_templates, list_mcp_resources, mcp__graphtraj__tasks, read, read_image, read_mcp_resource, todo_write, update_goal, working_directory, write. It also recorded `config` = deepseek-official / deepseek-flash / reasoningEffort high. The turn then ended `TRANSPORT` with exit 1, because the network was blocked.
  2. Real codex 0.171.0 `codex sandbox` with the run's `-c default_permissions` / `-c permissions={s552=...}` reached `sandbox-exec`, so the profile parses. An undefined profile instead stops with `default_permissions requires a [permissions] table`. The Seatbelt itself could not run here (below).

## Correction 1 (after Main's real 00 on 0c054918)

- **New step `P <agent>...`** (e.g. `P codex dsh`). It re-runs only those agents' no-model Seatbelt checks and their S READY + probes. U/A READY, F and other agents' runs are not touched. For each agent that passes it prints `R <agent> all`. 00 calls the same function for all four agents.
- **codex leak.**
  - Cause: `:minimal` makes Codex's Seatbelt add `/private/tmp` and `/private/var/tmp` as readable+writable scratch roots (codex-rs/sandboxing/src/seatbelt_scratch.rs:36-48,71-78 @ rust-v0.171.0, used by seatbelt.rs:841-856). Those roots exclude only the profile's `deny` roots (scratch.rs:26,75).
  - Fix: profile `s552` now lists as `"deny"` every sibling entry along `/private/tmp → BASE → project → runs → <run>` (recomputed each turn), plus `/private/var/tmp`.
  - Also added: `-c agents.enabled=false --disable multi_agent_v2`. Main's S had offered `collaboration.spawn_agent`.
- **dsh abort.**
  - The outer profile now denies only `file-read-data file-read-xattr` (contents and listings) and leaves path metadata readable. 0c054918 denied `file-read*` on subtrees containing the cwd's ancestors.
  - Layers, the last match deciding: deny `/private/tmp`, `/private/var/tmp`, the workspace tree and the home configs → allow BASE/project, `$H/.venv-runtime`, BASE/bin → deny BASE/project/runs → allow own ws and own BASE/dsh/<run>.
  - New no-model gate `dsh-sandbox`. Under the exact profile it runs pwd, `node -e 1`, a node tmpdir write/read, and reads of the own ws, the scratch project config and the guide; all must succeed. Reads of the BASE/u, BASE/u/research, BASE/logs and sibling-ws canaries, design.md, another DSH_HOME, a listing of BASE/logs and of ~/.claude/projects must fail. A diagnosis line (not a gate) runs `node -e 1` under the old form.
- **Probes.** Canaries are added in BASE/logs and BASE/u/research. Codex gets every attempt as its own mandatory shell command.
- **Rehearsal stubs now model the rules instead of always refusing.** The `codex sandbox` stub applies the scratch roots minus `deny` entries. With the old profile it reads the canary (negative control, rc=0); with the new one it refuses. The `sandbox-exec` stub evaluates the profile's rules for cat/ls, last match deciding. Real Seatbelt is still proved only by Main.

## Correction 2 (DSH only, after Main's `P dsh` on 3356b581)

- **What Main's run showed:** every deny held, and every re-allow was ignored. The re-allows were `(allow file-read* …)` after `(deny file-read-data file-read-xattr …)`.
- **Inferred from that run, not from Apple documentation:** a rule naming the specific operation is not overridden by a later rule using the `file-read*` wildcard.
- **Fix:** each re-allow now names exactly the deny's operations (`file-read-data file-read-xattr`), in the same layer order.
- **New gate line:** the real `dsh --version` must succeed under the new profile, with the run's exact environment (DSH_HOME, DSH_AGENTS_HOME).
- **Diagnosis lines (not a gate)**, printing rc, signal and the stderr tail:
  - `dsh --version` and `dsh --profile headless --patch <run patch> --dump-config`, under the new profile and under the exact 0c054918 profile;
  - if the 0c054918 profile fails, a bisection that drops one of its deny subpaths at a time and reports the first whose removal lets dsh start, as an INFERRED cause.
- **Stub changes:** the stub `sandbox-exec` now applies this precedence. Applied to Main's real 3356b581 profile, it reproduces the refusal of the own ws (`rehearsal/negative-control-3356b581-profile.txt`).
- **Bisection self-test:** a stub dsh that aborts when `project/runs` is denied by `file-read*` (`rehearsal/bisection-selftest.txt`).

## Correction 3 (DSH only, after Main's `P dsh` on ff4ed8bd)

- **Moved:** dsh reads its `--patch` file at run time (`dsh-app-boot` `loadOverlayPatches`). That file now lives in `BASE/dsh/<run>/dsh-patch.yml`, which the run's profile already re-allows. An identical copy stays in `logs/<run>/dsh-patch.yml` for the audit folder (`S-dsh-patch.yml`) and for C.
- **Not moved:** the other per-run inputs are not read from BASE/logs by dsh or its children. The relay is in BASE/bin, the task comes on stdin, and `dsh.sb` is read by `sandbox-exec` before the profile applies.
- **Profile unchanged:** the profile text is identical to ff4ed8bd.
- **Gate additions:** reading the run's patch must succeed, and `dsh --profile headless --patch <that patch> --dump-config` must succeed, both with the run's env. On failure the diagnosis line `... --dump-config under the new form` prints the stderr tail.
- **Negative control:** `rehearsal/negative-control-ff4ed8bd-patch-in-logs.txt`. The stub `sandbox-exec` now also checks dsh's `--patch` file against the profile.

## Seatbelt

`sandbox-exec: sandbox_apply: Operation not permitted` is printed by macOS `/usr/bin/sandbox-exec` (its own `sandbox-exec:` prefix) when it runs inside another Seatbelt sandbox, as in the Engineer's Claude Code Bash. Main's 00 is the proof that Codex's shell Seatbelt and dsh's outer profile work on Main's host. If either is refused there too, the probes FAIL and that agent is blocked (STOP to the Leader). The isolation is never weakened.
