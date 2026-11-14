# 461 real-host check (round 2): a killed owner's Pi child leaves an orphaned tool process; one read reclaims it

Main runs every step except 00u. Each Main command returns within 10 minutes or starts its work in the
background. Output goes to
`/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/461-pi-child-tool-process-reclaim/realhost/r2/`
(`…/r2` below). Round 1's `realhost/` files are left untouched.

`S` below is `zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/461-pi-child-tool-process-reclaim/scripts/verify-461/steps.zsh`.

The base is the Harness tmp directory `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/tmp/461`
(AGENTS.md rule), never the home directory. Nothing under `~/.claude`, `~/.codex`, `~/.pi`, any dotfile or the
production `.venv-runtime` is changed. No key value is printed; step 03 and the probe run with no key variable.

| Step | Who | Command | Expected time | Success |
|---|---|---|---|---|
| 00 | Main | `VERIFY461_ACCEPT_PI_CONTEXT=1 S 00` (only after Main/the user accepted the Pi context; without it 00 STOPs when Pi would load a file above the project) | 2-4 min | `claude --version` 2.1.323, `pi --version` 1.4.0, the `461 fix:` line all True, `deps: click 8.5.0`, Pi values (key variables by name only), no `pi.deny_read`, `pi role keys accepted: True`, `sandbox available …: YES`, `roles OK`, `task 1 ready`, `committed: .claude/settings.json`, `isolation: OK`, `Pi child context: loads ['…/you-are-a-product-architect-delivery/AGENTS.md'] (no supported deny in GraphTraj Pi roles; accepted by Main/user decision)`, `MODEL OK first line: True \| cc-plugin-agents-md absent from init plugins: True \| MEMORY line present: True`, `claude memory from the Harness: none`, `Claude context isolated: YES` (NO stops 00), `pi deepseek-flash OK: PI OK` (or `SKIPPED`), `graphtraj-claude-host loaded: YES`. |
| 00u | USER, once, only if 00 prints `graphtraj-claude-host loaded: NO` | `cd …/tmp/461/project && claude`, 'Yes, proceed' on folder trust, `/exit` | 1 min | Main reruns 00 and sees `loaded: YES`. |
| 01 | Main | `S 01` | returns at once | Records the dispatch, starts the background `claude -p` Main, prints its pid, the timeline and the 02 command. |
| 02 | Main | `S 02 2>&1 \| tee …/r2/02.txt` | <= 9.5 min (waits for 01's Main) | `01 Main init plugins:` without `cc-plugin-agents-md`; `member Claude cwd (its worktree): … \| .claude/settings.json tracked: True \| cc-plugin-agents-md off: True`; the `member:` line names the member created by 01's dispatch; `CHECK PASS: 0` (the orphan alive after the kill, outside the Runtime group), CHECK 1-4 PASS, `summary: ALL PASS`; facts in `02-kill.json`. If it prints `still running`, rerun 02 once. |
| 03 | Main | `S 03` | starts in background; 25 min max | Full suite at HEAD; `tail -n 25 …/r2/03-suite.txt`; done at `== totals:`. |

No step opens a dialog except 00u.

## Timeline (t0 = 01's dispatch)

The Pi child gets exactly: `Use the bash tool to run exactly: sleep 1461 >/dev/null 2>&1 & sleep 3 . Then use the
bash tool again to run exactly: sleep 1200 . Then reply DONE-461.`

- about t0+2 min: call 1 leaves `sleep 1461` in the background (24 min, alive to >= t0+26) and ends after 3 s
  (the 1 s descendant sampler records the orphan meanwhile);
- about t0+3 min: call 2, `sleep 1200`, starts (20 min, running to >= t0+23);
- by about t0+10: 01's Main ends (at most 5 polls of `probe child`, 100 s each);
- 02 waits <= 9 min for 01's Main and kills at once: <= t0+9, or <= t0+18 when 02 is rerun once.

So both are alive at the kill in the worst case. No `nohup`: Pi SIGKILLs a tool's process group
(`utils/shell.js:189-213`), so nohup changes nothing, and macOS nohup fails without a console. On shutdown (the stdin
EOF a dead owner causes) Pi aborts only the running call (`sleep 1200`); the orphan sits in the ended first call's
group, so it outlives the owner until the reconciling read stops it (round 1: the foreground variant left nothing).

## Which member (round 1's 02b defect)

01 runs `probe.py dispatch`, which writes `<project>/.graphtraj/probe-461/dispatch.json` (time, stream path) before
the `claude -p` starts; `01-dispatch.txt` keeps the line. `probe child` and `probe kill` select task 1's team_leader
session created at or after that time and, once 01's stream holds the swarm result, only its alias. They print
`member: <alias> (dispatch at …; task 1 team_leader sessions […]; created at/after the dispatch […]; swarm result
alias …)`. Zero or more than one match: `member: NONE` and `STOP`, nothing signalled.

## 00: isolation and the Pi child's context files

`probe isolation` prints the graphtraj project root and git top level (both the project), CLAUDE.md/CLAUDE.local.md
at or above the project (none), then the Pi facts:

- Pi 1.4.0 loads its agent dir's context file, then one of `AGENTS.override.md`, `AGENTS.md`, `AGENTS.MD`,
  `CLAUDE.md`, `CLAUDE.MD` from every directory from cwd up to `/`
  (`dist/core/resource-loader.js:115-134, 160-196`); only `--no-context-files` turns that off
  (`resource-loader.js:466`, `cli/args.js:197-198`). graftling's argv never passes it
  (`src/graftling/pi/execution.py:374-380`), and a GraphTraj Pi role accepts only `sandbox_python`, `sandbox_path`,
  `agent_dir`, `read_paths` and `allow_*` (`src/graphtraj/runtimes/pi/pi_adapter.py:136-140`; anything else,
  such as `deny_read`, is ROLE_CONFIG_UNSUPPORTED at create, as the real 01 of r2 showed). The child cwd is
  resolved (`pi_adapter.py:337`). So under the Harness tmp base the child loads the Harness `AGENTS.md`, and there is
  no supported way to stop it within this probe.
- The probe's `pi` role therefore holds only the user's production Pi keys. 00 checks them without a model against
  the allowed set read from the installed `PiRuntimeAdapter.preflight_runtime_context` (`probe.py pi_role_keys`):
  `pi role keys accepted: True`, otherwise STOP.
- 00 prints `Pi child context: loads [<files>] (no supported deny in GraphTraj Pi roles; accepted by Main/user
  decision)` and STOPs unless `VERIFY461_ACCEPT_PI_CONTEXT=1` is set (when the list is non-empty). The Claude
  isolation gate below is unchanged and fail-closed. The user's own global `~/.pi/agent` context file is printed
  separately (not the Harness).

## Claude context (00 and 02)

Task 462's reopened 00 (Claude Code 2.1.323, project under Harness tmp) was given the Harness AGENTS.md; its init
record listed `cc-plugin-agents-md@builtin`, and `claudeMdExcludes` alone did not stop it. Here:

- 00 writes `<project>/.claude/settings.json` before the initial commit (`probe.py claude_settings`):
  `enabledPlugins {"cc-plugin-agents-md@builtin": false}` and `claudeMdExcludes` for every `CLAUDE.md`,
  `CLAUDE.local.md`, `.claude/CLAUDE.md` and `AGENTS.md` found above the project, computed at 00. It is committed, so
  `dev` (made by setup from that commit) and every member worktree carry it. `settings.local.json` stays as the host
  configuration writes it. `~/.claude` and `~/.claude.json` are never written.
- 00's one `claude -p` asks for `MODEL OK` and a `MEMORY:` line naming every CLAUDE.md/CLAUDE.local.md/AGENTS.md it
  was given (`probe.py claude_check`). It fails closed unless the first line is `MODEL OK`, the init plugins lack
  `cc-plugin-agents-md` and no listed file is outside the project.
- 02 prints, read only (`probe.py claude_facts`), the 01 Main's init plugins and the member's Claude cwd. The member's
  Claude runs with cwd = its Task worktree (`src/graftling/claude/execution.py:837`, `Popen(cwd=worktree_path)`),
  made from dev's commit (`src/graphtraj/workspace/runner_project.py:56-66`), so the committed settings.json is
  there; 02 shows it tracked and the plugin off. The member's own init record is not retained (its trace links the
  native transcript, `graftling/claude/execution.py:551-556`; the init event is kept only in memory, :955-964).

## 02: kill, CHECK 0, one read, CHECK 1-4

`probe.py kill` refuses (`STOP`, signals nothing) unless the dispatch's member ended its turn, its child is a
`running` Pi child owned by the member's last Worker, the record has `tool_marker` and `tool_descendants`, the
record lists a live `sleep 1461`, and the recorded `runtime_pid` (if alive) is not readable without the marker.
It prints the live tree below the Runtime, the recorded chain and the running `sleep 1200`. Then it:

1. SIGKILLs the recorded owner Worker, then the Runtime's process group (only when the Runtime leads it), each only
   if its pid still has the start time read before;
2. `CHECK 0`: after the owner kill and before the reconciling read, the child's recorded `sleep 1461` is alive
   outside the Runtime group. Otherwise `NOT OBSERVED` and the summary is not ALL PASS;
3. starts three bystanders of its own (another marker, no marker, `/bin/sleep 901`), each in its own session;
4. one reconciling read (`GraphTrajAgents.reconcile_children`);
5. CHECK 1 (`failed`/`owner-exited`), 2 (`escaped_processes` lists `sleep 1461` and every recorded process alive
   after the kill as stopped, `remaining` empty), 3 (nothing recorded and no `sleep 1461` alive), 4 (bystanders
   alive); stops its bystanders.

## Rehearsal without a model (sandbox)

`VERIFY461_NO_MODEL=1 VERIFY461_BASE=$TMPDIR/rh461r2 VERIFY461_OUT=$TMPDIR/rh461r2-out`, then `S 00` and `S 02`.
02 runs `probe.py stub` first: an older task-1 member, the dispatch record, then the current member with a Pi child
record; a stand-in owner Worker runs the real sampler on a stand-in Runtime that runs 01's two bash calls as Pi does
(`/bin/bash -c`, own session). `VERIFY461_STUB_CASE=ingroup` puts call 1 in the Runtime's group, so the group kill
also stops the orphan: 02 must print `NOT OBSERVED` and no ALL PASS. `VERIFY461_STUB_CASE=ambiguous` adds two
members after a new dispatch with no alias: `member: NONE: 2 match` and `STOP`. In the stub the stand-in Python
processes contain the text `sleep 1461`, so the read-only ps listing shows them too; the CHECKs use the record. Not
rehearsed: 00's connection, sandbox, model, Pi and plugin lines, 00u, 01, the real Pi chain, and 03.
