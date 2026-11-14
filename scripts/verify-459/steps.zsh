#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 459 real-host check: a member's agents-tool Claude child runs `sleep 459` in its Bash tool (/bin/zsh, /bin/sleep:
# macOS hides their environment); its owner Worker and Runtime group are SIGKILLed; one reconciling read must stop the
# escaped tool shell and sleep through the recorded descendants (tool_descendants), and nothing else.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/459-reclaim-platform-binary-tool-descendants/scripts/verify-459/steps.zsh <00|00u|01|02|03>
# 00  Main. preflight: scratch venv from COMMIT, isolated project, one-line model/login answer, probe Task ready,
#     and a line proving the fix is in the venv ('tool_descendants' is an allowed process fact).
# 00u USER, once, only when 00 prints 'graphtraj-claude-host loaded: NO': folder trust.
# 01  Main. background `claude -p` Main: swarm -> member creates a Claude child whose Bash runs exactly `sleep 459`
#     and ends its turn; Main polls until CHILD-RUNNING and stops.
# 02  Main. waits (<= 9 min) for 01's Main; refuses unless the child's descendants record lists a live `sleep 459`;
#     SIGKILLs only the child's recorded owner Worker and Runtime group (after checking they are this project's),
#     starts three bystanders, one reconciling read, CHECK 1-4, stops the bystanders.
# 03  Main. full suite at HEAD in the background (self-terminating after 25 min).
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
# Rehearsal without a model: VERIFY459_NO_MODEL=1 (00 stops before Claude Code; 02 runs on a stub from 'probe.py stub').
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/459-reclaim-platform-binary-tool-descendants
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY459_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY459_BASE:-$HOME/graphtraj-verify-459}
OUT=${VERIFY459_OUT:-$H/.graphtraj/core/state/tasks/459-reclaim-platform-binary-tool-descendants/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
PID01=$OUT/01-main.pid
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
claude_bin() { [[ -n ${VERIFY459_CLAUDE:-} ]] && { print -r -- $VERIFY459_CLAUDE; return; }; command -v claude || print -r -- $HOME/.local/bin/claude; }
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
# Wait (<= 9 min) for a background claude -p started by this script; never a standalone sleep.
main_wait() {
  $VV/bin/python -I -c 'import os, sys, time
try:
    pid = int(open(sys.argv[1]).read().strip())
except (OSError, ValueError):
    print("STOP: no pid file", sys.argv[1] + "; run the previous step first"); sys.exit(2)
deadline = time.time() + 540
while time.time() < deadline:
    try: os.kill(pid, 0)
    except ProcessLookupError: print("Main claude -p", pid, "ended"); sys.exit(0)
    time.sleep(5)
print("Main claude -p", pid, "still running after 9 min"); sys.exit(1)' $1
}
# 471: PROBE_OUT lets the probe find 01's Main stream (which member this dispatch created).
probe() { (cd $P && clean PROBE_OUT=$OUT $VV/bin/python -I $SD/probe.py "$@") }
# STOP, changing nothing, while an earlier run's Main or a 'sleep 459' still lives. Signals nothing.
guard() { clean $CONDA -I $SD/probe.py idle $OUT - }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  guard || return 1
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I -c 'import inspect, graftling.control as c, graphtraj.execution.agent_driver as d
import graftling.claude.execution as e
print("control:", c.__file__)
print("459 fix: tool_descendants allowed:", "\"tool_descendants\"" in inspect.getsource(c.ExecutionEvents.process),
      "| reconcile reads it:", "read_sidecar" in inspect.getsource(c._stop_escaped),
      "| owner samples:", "DescendantSampler" in inspect.getsource(e.ClaudeExecution.__init__),
      "| agents driver records it:", "tool_descendants" in inspect.getsource(d.AdapterDriver.start))') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 459 probe" > README.md && git add README.md \
      && git -c user.name=459 -c user.email=459@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  probe prepare $P $MODEL || { print "STOP: probe Task is not ready (text above)"; return 1; }
  [[ -n ${VERIFY459_NO_MODEL:-} ]] && { print "VERIFY459_NO_MODEL set: stopping before Claude Code (rehearsal)."; return 0; }
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
  print "Success: '459 fix: tool_descendants allowed: True | reconcile reads it: True | owner samples: True | agents driver records it: True',"
  print "deps click 8.5.0, 'roles OK', 'task 1 ready', result 'MODEL OK' with $MODEL, 'graphtraj-claude-host loaded: YES'."
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
  say "[01] Main. starts the probe Main in the background. Dialog: none. Returns at once; then run 02."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  guard || return 1
  [[ $(cat $BASE/src-commit 2>/dev/null) == $(git -C $WT rev-parse HEAD) ]] || print "NOTE: venv commit $(cat $BASE/src-commit) is not HEAD; rerun 00 if HEAD is the commit under test."
  local C=$(claude_bin) S=$OUT/01-main-stream.jsonl
  rm -f $PID01 $S  # 471: a fresh stream; its creation time is this dispatch's time (probe.py member)
  local member='Use only the agents tool (mcp__agents__agents). Execute feature create with arguments {"runtime": "claude", "instruction": "Use the Bash tool once to run exactly: sleep 459 . Then reply DONE-459."}. Reply with the one line CREATE <agent> <execution> from its result and end your turn at once. Do not call wait or status. Read no files and run no shell command yourself.'
  local swarm=$($VV/bin/python -I -c 'import json,sys; print(json.dumps({"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":sys.argv[1]}]}}))' "$member")
  print -r -- "$swarm" > $OUT/01-swarm-arguments.json
  local W="env PROBE_OUT=$OUT $VV/bin/python $SD/probe.py child $P 100"
  print -r -- "1. Call mcp__agents__tasks once with exactly these arguments: $swarm
Print its raw result text on one line starting with SWARM-RESULT.
2. Send nothing to the member. Run this exact Bash command, one call after another, until one prints CHILD-RUNNING (the member's turn ended and its child's sleep 459 runs), at most 5 times: $W
3. Print CHILD-RUNNING (or CHILD-NOT-RUNNING after 5 calls) and stop. Do not retire, interrupt or message anything." > $OUT/01-main-prompt.txt
  print "dispatch at $(date +%T); prompt: $OUT/01-main-prompt.txt"
  (cd $P && clean nohup $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
      --allowedTools "mcp__agents__tasks,Bash($W)" < $OUT/01-main-prompt.txt > $S 2> $OUT/01-main-stderr.txt &
   print $! > $PID01)
  print "Main claude -p pid $(cat $PID01) (in $PID01), stream $S"
  print "The child's 'sleep 459' ends by itself about 7.6 min after it starts: run 02 right after 01's Main ends."
  next "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
}

step_02() {
  say "[02] Main. waits for 01's Main (<= 9 min); kills the child's owner and Runtime, one reconciling read, CHECK 1-4. Dialog: none."
  if [[ -n ${VERIFY459_NO_MODEL:-} ]]; then
    print "VERIFY459_NO_MODEL set: stub member and child instead of 01 (rehearsal)."
    probe stub $P - || return 1
  else
    main_wait $PID01
    case $? in
      0) ;;
      1) print "STOP: rerun 02 later (01's Main still runs)"; return 1 ;;
      *) return 1 ;;
    esac
    grep -o 'CHILD-RUNNING\|CHILD-NOT-RUNNING\|SWARM-RESULT[^"]*' $OUT/01-main-stream.jsonl | sort | uniq -c
  fi
  probe child $P 1
  probe kill $P $OUT/02-kill.json
  local rc=$?
  print ""
  print "Success: 'summary: ALL PASS'. 1 child failed/owner-exited; 2 escaped_processes lists the /bin/zsh tool shell and"
  print "'sleep 459' stopped, remaining []; 3 none of the recorded descendants and no 'sleep 459' alive; 4 the three"
  print "bystanders alive (then stopped by the probe). A STOP line means nothing was signalled."
  next "zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
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
  print "== baseline: compare with the dev full-suite run Main last used (459 base 51d13d46)"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
