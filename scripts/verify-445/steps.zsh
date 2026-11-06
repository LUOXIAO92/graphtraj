#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 445 real-host check: an idle timed Leader's planned end reaches its root parent (Main)
# without any new execution. Main runs every step; the user does nothing.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/445-budget-notice-idle-timed-leader/scripts/verify-445/steps.zsh <00|01|02>
# 00 preflight: scratch venv from COMMIT, isolated project, one-line model/login answer, probe Task ready.
# 01 probe: a `claude -p` Main in the isolated project dispatches the Leader (1-minute budget). The
#    Leader replies one line and ends its turn; Main then only runs `sleep` (no message to the Leader)
#    until past the planned end plus a margin. Then 02 runs automatically.
# 02 observe: execution-budget.yml notices, the Leader's last execution end, Main inbox records.
# Native dialogs: none (claude -p shows no folder-trust or MCP dialog with --strict-mcp-config).
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only),
# the user's dotfiles, ~/.claude or ~/.codex. No key value is read or printed.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/445-budget-notice-idle-timed-leader
SD=${0:A:h}
COMMIT=${VERIFY445_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY445_BASE:-$HOME/graphtraj-verify-445}
OUT=${VERIFY445_OUT:-$H/.graphtraj/core/state/tasks/445-budget-notice-idle-timed-leader/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
SRC=$BASE/src
VV=$BASE/venv
P=$BASE/project
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> 下一步 / next (Main pastes): $*"; }
claude_bin() { command -v claude || print -r -- $HOME/.local/bin/claude; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  print "commit under test: $COMMIT"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  git -C $WT rev-parse $COMMIT > $BASE/src-commit
  $CONDA -m venv --system-site-packages $VV || return 1
  local S=($RT/lib/python*/site-packages(N)) D
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  D=($VV/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $VV/bin/python -I -c 'import graphtraj.execution.budget_idle_timer as t; print("timer module:", t.__file__)') || return 1
  say "isolated project $P (git, graphtraj setup, Claude host configuration)"
  # Same path every run (trust is per path); keep any per-project approval Claude Code wrote there.
  [[ -f $P/.claude/settings.local.json ]] && cp -p $P/.claude/settings.local.json $BASE/settings.local.json.keep
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 445 probe" > README.md && git add README.md \
      && git -c user.name=445 -c user.email=445@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  (cd $P && clean $VV/bin/python -I $SD/probe.py prepare $P $MODEL) || { print "STOP: probe Task is not ready (text above)"; return 1; }
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
  say "plugin check: the init record must list graphtraj-claude-host (it prepares each call's association)"
  if ! $VV/bin/python -I $SD/probe.py plugins $OUT/00-model-stream.jsonl -; then
    print "STOP: graphtraj-claude-host is not loaded in $P. Claude Code loads project plugins only in a trusted folder."
    print "Run step 00u (USER, once), then rerun 00. The project path stays $P, so the trust carries over."
    next "USER: zsh $SD/steps.zsh 00u   (then Main: zsh $SD/steps.zsh 00)"
    return 1
  fi
  print "Success: timer module from $SRC, 'roles OK', 'task 1 ready', result 'MODEL OK' with $MODEL in models,"
  print "and 'graphtraj-claude-host loaded: YES'."
  next "zsh $SD/steps.zsh 01 2>&1 | tee $OUT/01.txt"
}

step_00u() {
  say "[00u] USER (once; Main cannot do this: it needs a terminal and a dialog). Plain macOS Terminal:"
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'."
  print "If a second dialog asks about the project's MCP server 'agents' or the plugin, approve it for this project."
  print "Then type /exit and press Enter. Send no message. Any other dialog: press Esc and tell Main its title."
  print "Why USER: Claude Code records folder trust in ~/.claude.json only through this dialog; claude -p never"
  print "asks, and the only other way is editing ~/.claude.json, which Main must not touch. No supported"
  print "non-interactive trust exists inside the probe project (393 step Vc needed the same start)."
  next "Main: zsh $SD/steps.zsh 00"
}

step_01() {
  say "[01] Main. probe: dispatch the Leader, then stay idle toward it past the planned end. Dialog: none. ~4 min."
  [[ -x $VV/bin/graphtraj && -f $P/.mcp.json ]] || { print "STOP: run 00 first"; return 1; }
  local C=$(claude_bin)
  local swarm='{"action":"execute","feature":"swarm","arguments":{"tasks":[{"task_id":"1","role":"team_leader","instruction":"Reply with exactly one line, PROBE DONE, and end your turn. Call no tool."}]}}'
  print "dispatch at $(date +%T)"
  (cd $P && print -r -- "Call mcp__agents__tasks once with exactly these arguments: $swarm
Then send nothing to any Agent. Run this exact Bash command three times, one after another (each waits at most 100 s):
$VV/bin/python $SD/probe.py wait $P 100
Then print DONE and stop." \
    | clean $C -p --model $MODEL --output-format stream-json --verbose --mcp-config $P/.mcp.json --strict-mcp-config \
        --allowedTools "mcp__agents__tasks,Bash($VV/bin/python $SD/probe.py wait $P 100)" > $OUT/01-main-stream.jsonl 2> $OUT/01-main-stderr.txt)
  print "claude -p rc=$? at $(date +%T); Main stream: $OUT/01-main-stream.jsonl"
  grep -c '"execution-budget-exceeded"\|planned budget of' $OUT/01-main-stream.jsonl | sed 's/^/Main stream lines naming the budget notice: /'
  step_02
}

step_02() {
  say "[02] Main. observe (read only). Dialog: none."
  (cd $P && clean $VV/bin/python -I $SD/probe.py observe $P $MODEL) | tee $OUT/02.txt
  local rc=${pipestatus[1]}
  print ""
  print "Success: 'CRITERION PASS': elapsed_minutes:1 delivered=True observer=<...team_leader>, its occurred_at later than"
  print "the Leader's last execution end, and a Main inbox or Main stream record of execution-budget-exceeded."
  print "If 'delivered= False' with the Main stream count 0: Main had ended; rerun 01 (it re-creates nothing) and report both."
  print "If 'NO execution-budget.yml': the dispatch failed; read $OUT/01-main-stream.jsonl for the swarm result."
  print "Receiver: Main is the claude -p root in $P; the Runner writes its received events to"
  print "  $P/.graphtraj/runner/main-sessions/inbox/*.jsonl (and pushes them into the running Main's input)."
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. ~15-20 min (6 shards)."
  local head=$(git -C $WT rev-parse HEAD) built=$(cat $BASE/src-commit 2>/dev/null)
  [[ $built == $head ]] || { print "STOP: scratch venv was built from '${built:-unknown}', not HEAD $head; rerun 00 first"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: the Worktree has uncommitted changes"; return 1; }
  (cd /tmp && $VV/bin/python -I -c 'import graphtraj; print("graphtraj.__file__ =", graphtraj.__file__)') | tee $OUT/03-suite.txt
  # The suite runs from the Worktree (HEAD); the editable venv resolves $SRC, an archive of the same commit.
  (cd $WT && nohup $VV/bin/python scripts/run_test_shards.py --shards 6 --log-dir $OUT/03-shards >> $OUT/03-suite.txt 2>&1 &)
  print "started at $(date +%T). Status (Main, any time):"
  print "  tail -n 25 $OUT/03-suite.txt"
  print "Done when it shows a line like 'N failed, N passed, N skipped'; failing IDs are in $OUT/03-shards/failures.txt."
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  01) step_01 ;;
  02) step_02 ;;
  00u) step_00u ;;
  03) step_03 ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
