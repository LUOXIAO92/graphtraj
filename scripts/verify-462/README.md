# 462 real-host check: a Codex child's tool survives its killed app-server and the owner reclaims it

Adapted from `scripts/verify-459`. Main runs every step except 00u. Each Main command returns within 10 minutes
or starts its work in the background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/462-codex-child-tool-process-reclaim/realhost/reopen/`
(`…/reopen` below).

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/462-codex-child-tool-process-reclaim/scripts/verify-462/steps.zsh`.

The base is `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/462/verify` (scratch venv `venv`, project `project`, suite venv `suite-venv`), under the
Harness `tmp/` as AGENTS.md asks (2026-11-14). No other verify directory is touched.

The Main and the member are Claude (`claude-opus-5-5`), as in 459. The child is Codex with `gpt-6-luna` only: its
model comes from the project's only Codex preset, `codex_child` (`probe.py prepare`). The member's `create` names no
model: GraphTraj's agents driver refuses a selected model, connection, preset or reasoning effort (`invalid-config`,
seen on the first real-host run, Correction 1). One Codex run.

| Step | Who | Command | Success |
|---|---|---|---|
| 00 | Main | `S 00` | Shows `462 fix: reconcile reads tool_descendants: True \| Codex owner samples: True \| Codex owner reclaims: True \| agents driver records Codex: True`, `deps: click 8.5.0`, `roles OK`, `task 1 ready`, `codex logged in: YES`, `codex result: MODEL OK`, `codex AGENTS.md from the Harness: none`, `graphtraj runner directory: …/project/.graphtraj/runner | project own: True`, `claude --version` (2.1.323) and `codex --version`, `claude memory from the Harness: none`, `result: MODEL OK` with `claude-opus-5-5`, and `graphtraj-claude-host loaded: YES`. Prints the 01 command. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd /Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/462/verify/project && claude`, choose 'Yes, proceed' on the folder-trust dialog, then `/exit` | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | Returns at once. It starts a `claude -p` Main in the background and prints its pid and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/reopen/02.txt` | Waits up to 9 minutes for 01's Main; STOPs (signals nothing) without a running child, its record facts, a live app-server leading its own group and carrying the child's marker. Kills ONLY the child's app-server group; the owner stays alive. Prints `CHECK A`-`D` and `summary: ALL PASS`; writes `02-kill.json`. Up to about 45 s after 01's Main ends. |
| 03 | Main | `S 03` | Starts the full suite at HEAD in the background; it stops itself after 25 minutes. Read it with `tail -n 25 …/reopen/03-suite.txt`. It is done when the file shows `== totals:`. |

## What each step does

### 00: preflight

Isolation from the Harness (the project is nested under its `tmp/`): 00 writes the project's own
`.claude/settings.local.json` only (never `~/.claude` or another user setting), merging into the keys already there:
`claudeMdExcludes` for the Harness `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` (and `**/` forms), and
`enabledPlugins: {"cc-plugin-agents-md@builtin": false}`. In the first reopen run Claude Code 2.1.323 reported the
Harness `AGENTS.md` among its instructions while `claudeMdExcludes` was set; the init record listed the builtin
`cc-plugin-agents-md`, which is the likely source (an inference: native memory loads CLAUDE.md, not AGENTS.md).
00 prints `plugins loaded: [...]` and `cc-plugin-agents-md loaded: YES/NO` from the init record. It STOPs if the model
reports any Harness file; if the plugin is still listed but no Harness file is reported, it prints a NOTE and goes on.
The probe Main (01, 02's wait) and the member run in the same project and read this same settings file, so the same
exclusions apply to them.

As 459's, plus the Codex lines. The Codex login check prints only `YES` or `NO` (it greps `codex login status`
for `Logged in` and prints nothing of its text). `codex exec -m gpt-6-luna --sandbox read-only --json` (the `codex_child` preset's model) answers one
line in the isolated project; only its last agent message is printed. No key value, account text or `~/.codex`
file is read or printed.

### 01: the member and its Codex child

The `claude -p` Main dispatches the member with `swarm`. The member uses only the agents tool. It creates a child
with `{"runtime": "codex", "instruction": "Use your shell tool once to run exactly: sleep 462 . Wait for it.
Then reply DONE-462."}` (model from the `codex_child` preset: `gpt-6-luna`), replies `CREATE <agent> <execution>` and ends its turn. Main
runs `probe.py child` until it prints `CHILD-RUNNING`: the member's turn ended, the child record is `running` with
a `runtime_pid` (the owned Codex app-server, the `codex` launcher), and a `sleep 462` is alive. Its state line says
`tool_marker recorded=True|False` and `tool_descendants recorded=True|False`; the marker value is never printed.

The child's `sleep 462` ends by itself about 7.7 minutes after it starts, so run 02 as soon as 01's Main ends.

### 02: kill only the app-server, the owner reclaims, the checks

`probe.py kill` prints the child's record and its descendants record, and the read-only ancestry of each live
recorded `sleep 462`. It STOPs (signals nothing) unless the child is `running` with `tool_marker` and
`tool_descendants`, and the recorded `runtime_pid` is alive, leads its own process group and carries the child's
marker. A record without a `sleep 462` does not STOP: there is nothing to act on, so CHECK A and B FAIL. Then:

1. starts three bystanders of its own (Python with another `GRAFTLING_MEMBER_RUN`, Python without it, `/bin/sleep 901`);
2. SIGKILLs only the app-server's process group (pid and start time re-checked right before); the owner Worker is
   not signalled;
3. as soon as the app-server is gone, prints the recorded descendants still alive. **CHECK A**: a recorded
   `sleep 462` is among them (the residue was observed);
4. waits up to 30 s for the owner's `codex-termination-*.yml` in the child's directory (next to `tool_descendants`).
   If none appears, it does one reconciling read and uses that `escaped_processes`, labelled `reconcile`;
5. **CHECK B**: every residue process, including the `sleep 462` (same pid), is in `stopped`; `remaining` is [];
   no `error`. **CHECK C**: no recorded descendant and no `sleep 462` (the command or a shell whose `-c` starts with
   it) alive. **CHECK D**: the three bystanders alive;
6. prints the child execution's state and outcome, then stops its bystanders.

### 03: full suite

As 459's step 03, against the Worktree HEAD, six shards, stopped at 25 minutes. Base for comparison: `b3d522ad`.

## Rehearsal without a model (sandbox)

`VERIFY462_NO_MODEL=1 VERIFY462_BASE=$TMPDIR/rh462b VERIFY462_OUT=$TMPDIR/rh462b-out`, then `S 00` and `S 02`.
00 builds the venv and project, checks GraphTraj isolation and prints versions, then stops before any model. 02 runs
`probe.py stub` first: a child record made through `AgentControl`; a stand-in owner (stays alive) runs the real
sampler on a stand-in service group (launcher plus a readable native child, both with the marker); the native child
starts a real `/bin/zsh -c 'sleep 462; :'` in its own session. Once the service group is killed, the owner waits about
1.5 s (as the Codex owner closes and joins its sampler), runs the real `stop_tool_processes` and writes
`codex-termination-stub.yml`. Expected: `summary: ALL PASS`. With `VERIFY462_STUB_TOOL_GONE=1` the stub stops the tool
before the kill; expected: CHECK A and B FAIL. Not rehearsed: models, logins, the Claude host and plugin, 00u, 01,
Codex's own tool shell, 03.
