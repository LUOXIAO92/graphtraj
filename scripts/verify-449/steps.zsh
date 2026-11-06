#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 449 real-host check: the swarm result names the member's Agent, each end notice of one
# agents-tool child names its execution, and the member's task_sessions node lists that child.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/449-agent-identity-in-status-notice-swarm/scripts/verify-449/steps.zsh <00|00u|01|02|03>
# 00  Main. preflight: scratch venv from COMMIT, isolated project, one-line model/login answer, probe Task ready.
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust.
# 01  Main. starts a `claude -p` Main in the background: swarm -> member creates one child, sends it once more,
#     reports its parent inputs and `agents status`; Main then reads status and retires by the swarm's `agent`.
# 02  Main. waits (<= 9 min) for that Main to end, then prints PASS/FAIL per criterion.
# 03  Main. full suite at HEAD in the background (self-terminating after 25 min).
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/449-agent-identity-in-status-notice-swarm
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY449_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY449_BASE:-$HOME/graphtraj-verify-449}
OUT=${VERIFY449_OUT:-$H/.graphtraj/core/state/tasks/449-agent-identity-in-status-notice-swarm/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
# VERIFY449_CLAUDE names a stub host for a rehearsal without a model.
claude_bin() { [[ -n ${VERIFY449_CLAUDE:-} ]] && { print -r -- $VERIFY449_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
# click 8.5.0, yaml and websockets from production, copied (never changed there) into a venv's site-packages.
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
  [[ $(cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print(m.version("click"))') == 8.5.0 ]] \
    || { print "STOP: click in $1 is not production's 8.5.0"; return 1; }
}

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import graphtraj.interfaces.agents as a; print("agents module:", a.__file__, "| 449 view:", hasattr(a, "_list_agent_children"))') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  # Same path every run (trust is per path); keep any per-project approval Claude Code wrote there.
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 449 probe" > README.md && git add README.md \
      && git -c user.name=449 -c user.email=449@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  (cd $P && clean $VV/bin/python -I $SD/probe.py prepare $P $MODEL) || { print "STOP: probe Task is not ready (text above)"; return 1; }
  [[ -n ${VERIFY449_NO_MODEL:-} ]] && { print "VERIFY449_NO_MODEL set: stopping before Claude Code (rehearsal)."; return 0; }
  local C=$(claude_bin)
  [[ -f $BASE/settings.local.json.keep ]] && mkdir -p $P/.claude && cp -p $BASE/settings.local.json.keep $P/.claude/settings.local.json
  (cd $P && clean $VV/bin/python -m graphtraj.runtimes.claude.host configuration --project $P --claude $C --write) || return 1
  say "host answers one line with $MODEL (login check; no tool)"
  (cd $P && clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      <<< 'Reply with exactly: MODEL OK' > $OUT/00-model-stream.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  $VV/bin/python -I -c 'import json,sys
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d.get("type") == "result": print("result:", d.get("result"), "| is_error:", d.get("is_error"), "| models:", list((d.get("modelUsage") or {}).keys()))' $OUT/00-model-stream.jsonl \
      || { print "STOP: claude -p gave no stream. stderr:"; head -c 300 $OUT/00-model-stderr.txt; print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  say "plugin check: the init record must list graphtraj-claude-host"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    next "USER: zsh $THIS 00u   (then Main: zsh $THIS 00)"
    return 1
  fi
  print "Success: '449 view: True', deps click 8.5.0, 'roles OK', 'task 1 ready', result 'MODEL OK' with $MODEL,"
  print "and 'graphtraj-claude-host loaded: YES'."
  next "zsh $THIS 01"
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: folder trust is recorded only through this dialog; claude -p never asks, and Main must not edit ~/.claude.json."
  next "Main: zsh $THIS 00"
}

step_01() {
  say "[01] Main. starts the probe Main in the background. Dialog: none. Returns at once; then run 02 (~6-9 min)."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  local C=$(claude_bin) S=$OUT/01-main-stream.jsonl
  local member='Use only the agents tool (mcp__agents__agents). Step A: execute feature create with arguments {"runtime": "claude", "instruction": "Reply with exactly PONG-449-A and nothing else. Call no tool."}. Note the agent and execution of its result. Do not call wait or status. End your turn with the one line WAITING-A. Step B: when an input arrives whose JSON has source graphtraj and alias equal to that agent, execute feature send with arguments {"agent": "<that agent>", "message": "Reply with exactly PONG-449-B and nothing else. Call no tool."}, note the execution of its result, call nothing else and end your turn with the one line WAITING-B. Step C: when the second such input arrives, execute feature status with empty arguments once. Then end with a final reply holding, each on its own line: PARENT-INPUTS; every input you received that starts with {"source", verbatim, in order; CREATE <agent> <execution>; SEND <execution>; STATUS-BEGIN; the raw status result text; STATUS-END; '$END_MARK'. Read no files and run no shell command.'
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  print -r -- "$swarm" > $OUT/01-swarm-arguments.json
  local W="$VV/bin/python $SD/probe.py wait $P 100"
  print -r -- "1. Call mcp__agents__tasks once with exactly these arguments: $swarm
Print its raw result text on one line starting with SWARM-RESULT.
2. Send nothing to the member. Ignore any notice from it. Run this exact Bash command, one call after another, until one prints MEMBER-DONE, at most 5 times: $W
3. Take the value of the field agent in the swarm result. Call mcp__agents__agents with {\"action\": \"execute\", \"feature\": \"status\", \"arguments\": {\"agent\": \"<that value>\"}} and print its raw result starting with STATUS-BY-AGENT. Then call mcp__agents__agents with {\"action\": \"execute\", \"feature\": \"retire\", \"arguments\": {\"agent\": \"<that value>\"}} and print its raw result starting with RETIRE-BY-AGENT. If the swarm result has no field agent, print NO-AGENT instead and skip step 3.
4. Print DONE and stop." > $OUT/01-main-prompt.txt
  print "dispatch at $(date +%T); prompt: $OUT/01-main-prompt.txt"
  (cd $P && clean nohup $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      --allowedTools "mcp__agents__tasks,mcp__agents__agents,Bash($W)" < $OUT/01-main-prompt.txt > $S 2> $OUT/01-main-stderr.txt &
   print $! > ${S:r}.pid)
  print "Main claude -p pid $(cat ${S:r}.pid), stream $S"
  print "Fallback: if 02 says the swarm call is missing, read $S and $OUT/01-main-stderr.txt (head -c 2000)."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. observe (read only, waits up to 9 min for the probe Main to end). Dialog: none."
  (cd $P && clean $VV/bin/python -I $SD/probe.py observe $P $OUT/01-main-stream.jsonl)
  local rc=$?
  print ""
  print "Success: 'summary: ALL PASS'. Criteria: 1 swarm result has agent (= member mapping agent) and the member's"
  print "task_sessions node lists its child; 2 each of the child's two executions has one distinct end notice naming"
  print "that execution, core notification delivered, and the member's own inputs name them in order; 3 Main's"
  print "agents status and retire by the swarm agent id succeed."
  print "Fallbacks: 'still running after 9 min' -> rerun 02. 'exactly one agents-tool child' FAIL -> read the member"
  print "report printed above (it may have refused or called wait). Swarm FAIL -> grep SWARM-RESULT $OUT/01-main-stream.jsonl."
  [[ $rc == 0 ]] && next "zsh $THIS 03" || next "send $OUT/02.txt to the Leader; 03 may still run: zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  # The suite needs a venv that resolves this Worktree (tests/conftest.py checks it), built like 00's: same Conda
  # Python, click/yaml/websockets copied from production (click 8.5.0, not Conda's 8.2.1).
  rm -rf $SV; $CONDA -m venv --system-site-packages $SV || return 1
  $SV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT/src/graftling -e $WT 2>&1 | grep -vi cache
  copy_deps $SV > $OUT/03-suite.txt 2>&1 || { cat $OUT/03-suite.txt; return 1; }
  cat $OUT/03-suite.txt
  (cd /tmp && $SV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee -a $OUT/03-suite.txt
  rm -rf $OUT/03-shards
  (cd $WT && nohup zsh $THIS _03run >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time): tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows '== totals:'; failing IDs are in $OUT/03-shards/failures.txt."
}

step__03run() {
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD)"
  # Its own process group, stopped as a whole at the 25-minute limit.
  clean $SV/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $SV/bin/python $WT/scripts/run_test_shards.py --shards 6 --log-dir $OUT/03-shards
  print "== shards exit $?"
  print "== totals: $(grep -hE '^[0-9]+ (failed|errors|passed)' $OUT/03-suite.txt | tail -1)"
  print "== baseline: 448's run at 2be27dd6 and its recheck (448 adoption/raw/S-suite.txt, S-rerun.txt)"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

END_MARK=REPORT-449-END
case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
