# verify-455: full suite and one real-host child created with `configuration`

Main runs these steps. Each step prints ready-to-paste next commands, returns within
10 minutes or runs in the background, prints no key value and leaves nothing running.
Output: `/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/state/tasks/455-agents-child-preset-not-recorded/realhost/`.

```zsh
T=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/455-agents-child-preset-not-recorded/scripts/verify-455/steps.zsh
zsh $T S      # full suite of this Worktree's HEAD in the background (6 shards, --timeout 1500)
zsh $T 00     # preflight: scratch venv, isolated project ~/graphtraj-verify-455/project, login, plugin, roles, Task
zsh $T 00u    # USER, only if 00 printed 'graphtraj-claude-host loaded: NO' (folder trust)
zsh $T 01     # background claude -p Main: swarm one team_leader that creates a child with configuration advisor
zsh $T 02 2>&1 | tee .../realhost/02.txt   # one CHECK PASS/FAIL per criterion
```

## S: full suite

- Refuses while another `run_test_shards` runs, or when `src`/`tests` have uncommitted changes.
- Builds `~/graphtraj-verify-455/suite-venv` editable from this Worktree with Conda Python
  3.13; click, yaml and websockets are **copied** from production `.venv-runtime`
  (read only; it is never changed). Checks `graphtraj` imports from this Worktree.
- Runs `scripts/run_test_shards.py --shards 6 --timeout 1500` with `nohup`, so S returns at
  once. Poll with `tail -n 25 .../realhost/S-suite.txt`; done at `== DONE`.
- Baseline 0e099ac3 (453 `adoption/raw/S-suite.txt`): 3972 passed, 71 skipped, 0 failed.
  Every failure is therefore listed as `NEW <id>` and rerun alone.

## 00 to 02: real host

- 00 reuses verify-449's machinery: `git archive` of `VERIFY455_COMMIT` (default HEAD) into
  `~/graphtraj-verify-455/src`, a scratch venv, `graphtraj setup` in a fresh Git project,
  `probe.py prepare` (roles below, Task 1 ready, `roles OK`), Claude host configuration, and
  one `claude -p` line (`MODEL OK`, login check) whose init record must list
  `graphtraj-claude-host`. If not: USER runs 00u once, then Main reruns 00.
- Roles: `team_leader` (claude, `claude-opus-5-5`) and `advisor` (claude, the same model,
  `reasoning_effort: high`); `role_tree: {team_leader: {}}`.
- 01 starts a background `claude -p` Main. It dispatches one `team_leader` member, which
  creates one child with `configuration: advisor` (`PONG-455`), waits for its end, reads its
  status, retires it and replies with the raw create, wait, status and retire results.
  Main polls with `probe.py wait`, then retires the member by the swarm's `agent`.
- 02 waits up to 9 minutes for that Main to end, then checks:
  1. CREATE, STATUS and RETIRE results show `configuration=advisor`,
     `model=claude-opus-5-5`, `reasoning_effort=high`;
  2. the child's stored record shows the same in `selection`, and its `settings` hold no
     `applied`;
  3. the child's native Claude Session (`~/.claude/projects/*/<session>.jsonl`, read only)
     names only `claude-opus-5-5` and effort `high`.
  It also lists any process still naming the project (expected: none).

Rehearsal without a model: `VERIFY455_NO_MODEL=1 VERIFY455_BASE=$TMPDIR/... VERIFY455_OUT=$TMPDIR/...
zsh $T 00` stops before Claude Code. `probe.py check REPORT RECORD SESSION` runs the 02
criteria on given files.
