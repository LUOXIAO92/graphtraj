# 466 real-host check: a Claude member reads another Task member's Session through agents `session_read`

Main runs every step. 00u is the user's, only if a member step reports a folder-trust or login refusal. Each Main
command returns within 10 minutes or starts its work in the background. Every step prints `claude --version`. No
step signals a process it did not start, no step runs `rm` inside `zsh -c`, and no step leaves a process running
except 03's suite, which stops itself after 25 minutes. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/466-session-read-in-agents/realhost/`
(= the Task's `.state/realhost/`, `…/realhost` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/466-session-read-in-agents/scripts/verify-466/steps.zsh`.

Base: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/466/` (`src`, `venv`, `project`,
`suite-venv`). Nothing is created in the user's home.

| Step | Who | Command | Success | Native dialog |
|---|---|---|---|---|
| 00 | Main | `S 00` | `expected 2.1.325: yes`, `launched via zsh: yes`, `466 fix loaded: YES`, `deps: click 8.5.0`, `roles OK`, `ready tasks: ['1', '2']`, `isolation: OK`, `init: … model claude-opus-5-5 \| apiKeySource <name>`, `cc-plugin-agents-md loaded: NO`, `instruction files from the Harness: none`, `result: MODEL OK \| MEMORY: NONE`. Prints the 01 command. | none |
| 00u | USER, only if 01 or 02 reports a trust or login refusal | `cd …/tmp/466/project && claude`, 'Yes, proceed', `/exit` | Main reruns the refused step. | folder trust for the new path: choose 'Yes, proceed' |
| 01 | Main | `S 01 2>&1 \| tee …/realhost/01.txt` | Waits ≤ 9 min. `== summary: ALL PASS` (CHECK 1–5), the Task 1 member's alias and Session in the `identity:` line, its `member init record (session.yml): …` line and `member Worktree … .claude/settings.json exists: yes`. Refuses (STOP, rc 2, prints the 01c command) when Task 1 already has a member. | none (00u if refused) |
| 01c | Main, only when 01 refused or its wait ran out | `S 01c 2>&1 \| tee …/realhost/01c.txt` | Dispatches nothing. `== summary: ALL PASS`; writes `01-facts.out.json` for 02. | none |
| 02 | Main | `S 02 2>&1 \| tee …/realhost/02.txt` | Waits ≤ 9 min. The three `call A/B/C:` lines, the member's init-record and Worktree-settings lines as in 01, and `== summary: ALL PASS` (CHECK 1–10). Refuses like 01 (then 02c). | none (00u if refused) |
| 02c | Main, only when 02 refused or its wait ran out | `S 02c 2>&1 \| tee …/realhost/02c.txt` | Dispatches nothing. As 02. | none |
| 03 | Main | `S 03` | Full suite at HEAD in the background, six shards, stops itself after 25 min. `tail -n 25 …/realhost/03-suite.txt`; done at `== totals:`. | none |

## Acceptance and the observable that proves it

The Task's real-host criterion: a real Claude member uses the agents entry on another member's Session for a default
read, one page back and one keyword search, each returned within its tool output limit; no credential value.

| Criterion | Observable (02 unless named) |
|---|---|
| real Claude members, Runner-dispatched, `claude-opus-5-5`, `permission_mode: auto` | 00 `roles OK` (probe roles), `member Claude Code … 2.1.325` in 01 and 02, `identity:` lines |
| Task 1's Session needs paging | 01 CHECK 1 (≥ 12 text events, ≥ 10 tool calls) and CHECK 2 (the marker is before the last 5) |
| default read via `mcp__agents__agents`, feature `session_read` | `call A:` line; CHECK 1 and CHECK 5 (indices `== list(range(total))[-5:]`) |
| one page back with a negative slice | `call B:` line (`start -10, stop -5`); CHECK 2 and CHECK 6 (`[-10:-5]`) |
| one keyword search with positions | `call C:` line; CHECK 3 and CHECK 7 (first hit index equals the probe's own read) |
| each result within the member's tool output limit | CHECK 1–3: the tool_result in the member's own transcript is present, not `is_error`, complete JSON (an over-limit or saved-to-file notice is not JSON), with its size in characters |
| no credential value | CHECK 8 (the fake value Task 1 wrote is `[redacted]` in call A) and CHECK 9 (no fake value, `sk-ant-` or Bearer token anywhere in Task 2's transcript); 01 CHECK 3 shows the value was really written |
| the members ran without the Harness instruction files | 00 `cc-plugin-agents-md loaded: NO` and `instruction files from the Harness: none` (host in the project); 01 CHECK 5 and 02 CHECK 10: each member's own init record, retained by the Runner, lists no `cc-plugin-agents-md` and names no Harness `CLAUDE.md`/`AGENTS.md` path; the `.claude/settings.json exists: yes` line for each member's Worktree. The member's `memory=` self-report is printed as an extra line only |
| no new failures | 03 `== totals:` compared with Main's last dev baseline |

A check that was not actually observed (for example a member that never made call C) is FAIL, not PASS.

## Isolation

As verify-465: the project under `tmp/466/project` has its own `git init` and `.graphtraj` (from `graphtraj setup`),
so graphtraj discovery and Claude Code's project root stop there; 00 prints both. As verify-462, 00 writes the
project's own `.claude/settings.local.json` with `claudeMdExcludes` for the Harness `CLAUDE.md`, `CLAUDE.local.md`,
`AGENTS.md` (and `**/` forms) and `enabledPlugins: {"cc-plugin-agents-md@builtin": false}`, and checks the init
record of a `claude -p` in the project. The members run in their Task Worktrees under the project
(`.graphtraj/.agent-worktrees/`), where an untracked `settings.local.json` does not exist. So 00 also writes the same
settings into a tracked `.claude/settings.json` and commits it in the project's initial commit, before `graphtraj
setup` creates `dev`; every Task Worktree branches from it. 01 and 02 print whether that file exists in each member's
Worktree.

Each member's isolation is observed from its own init record. The Claude execution stores the native `system/init`
record in the member's Runner directory (`runner/sessions/<alias>/session.yml`, key `native_init`; a projection is in
its diagnostics as `system_init`). The probe prints its model, plugins and any instruction or memory fields, and
the CHECK fails when `cc-plugin-agents-md` is listed or a Harness `CLAUDE.md`/`CLAUDE.local.md`/`AGENTS.md` path
appears anywhere in it. If no init record is retained, the CHECK prints `NOT RETAINED` and FAILs; the member's
self-report never substitutes for it. Limit: an init record names plugins, not every file Claude Code read, so a
Harness file loaded without being named there would not be seen.
The members are dispatched by the Runner (`agent-runner --swarm-input`, as the project's root caller), as in
verify-465; no Main model session is used.

## What each step does

### 00 preflight

Scratch venv from the commit under test (`git archive`, editable install, click/yaml/websockets copied read-only from
production `.venv-runtime`). `probe.py fix` prints where `graftling` and `graphtraj.sessions.query` are imported from
and `466 fix loaded: YES` when they are the archive's source, `session_read` is an agents feature and `tasks`
`session_read` forwards to `read_events`. Then the project, one `team_leader` role (`claude`, `claude-opus-5-5`,
`permission_mode: auto`), probe Tasks 1 and 2 set ready, the isolation facts, the Claude settings and one `claude -p`
line (no tool, no MCP) whose init record gives the model and the login source name.

### 01 Task 1's member

One Runner-dispatched member writes a scripted conversation: a sentence before each of 12 Bash `echo` calls, a marker
`KW466-ORCHID` at step 3 and a made-up `api_key=sk-probe466fakevalue0000` at step 12, then `DONE-466-T1`. The member
assembles both strings itself, so its prompt does not contain them. The probe reads the archive as its owner (the
library `read_events`, unredacted) and prints the text, tools and all counts.

### 02 Task 2's member

The member calls `mcp__agents__agents` three times with `action: execute`, `feature: session_read`: A
`{"agent": "<Task 1 alias>"}`, B `{"session": "<Task 1 Session>", "start": -10, "stop": -5}`, C
`{"session": "<Task 1 Session>", "search": "KW466-ORCHID"}` (02 fills in the real IDs from `01-facts.out.json`), then
replies `RESULT-466 a=… b=… c=… memory=…`. The probe reads Task 2's own archived transcript and pairs each
`mcp__agents__agents` tool call with its tool_result. It prints, per call, the arguments, the tool_result size, its
`is_error`, whether it is complete JSON or an over-limit notice, and the returned positions, and compares them with
its own read of Task 1's Session.

### 03 full suite

As verify-465's step 04, against the Worktree HEAD.

## Rehearsal (sandbox, no model)

Correction 1: the settings writer and the initial commit (`git ls-files` shows `.claude/settings.json` and
`README.md`), `graphtraj setup` from that commit, and `member_isolation` on a synthetic Runner directory: with a
clean `native_init` (PASS), with `cc-plugin-agents-md` listed (FAIL), with a Harness `AGENTS.md` path (FAIL) and with
no init record (`NOT RETAINED`, FAIL).

Round 1:

`probe.py fix`, `prepare` and `isolation` ran against a project under `$TMPDIR` (`466 fix loaded: YES`, `roles OK`,
`ready tasks: ['1', '2']`, `isolation: OK`). The CHECK code of 01 and 02 ran on synthetic Claude-shaped archives:
a Task 1 Session built from the real Task 1 instruction and a Task 2 Session whose three tool results are real
`session_read` documents; every CHECK passed and the prompt contains neither the marker nor the fake value. Not
rehearsed: `claude -p`, the dispatch, the members' tool calls, 00u and 03. `zsh -n steps.zsh` and `py_compile
probe.py` pass.
