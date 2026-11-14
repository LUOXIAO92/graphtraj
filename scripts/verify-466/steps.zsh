#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 466 real-host check: a real Claude member reads another Task member's Session through the agents tool
# (feature session_read): a default read, one page back with a negative slice and one keyword search, each within
# Claude Code's tool output limit, with no credential value.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/466-session-read-in-agents/scripts/verify-466/steps.zsh <00|00u|01|01c|02|02c|03>
# 00  Main. preflight: claude --version, scratch venv from COMMIT, the fix line, isolated project (own git, own
#     .graphtraj, Claude settings without the Harness instruction files), probe Tasks, one-line host answer.
# 00u USER, only if 01 or 02 reports a folder-trust or login refusal.
# 01  Main. Task 1 member (claude-opus-5-5, permission_mode auto) writes a conversation long enough to page.
# 01c Main. collect-only for Task 1's existing member (01 refused or its wait ran out).
# 02  Main. Task 2 member reads Task 1's member Session with agents session_read: default, page back, search.
# 02c Main. collect-only for Task 2's existing member.
# 03  Main. full suite at HEAD in the background (self-stopping after 25 min; ends with '== totals:').
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only), the user's
# dotfiles, ~/.claude, ~/.codex or the Claude install. No key value is read or printed. No step signals a process
# it did not start.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/466-session-read-in-agents
SD=${0:A:h}
THIS=${0:A}
COMMIT=${VERIFY466_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=${VERIFY466_BASE:-$H/tmp/466}
OUT=${VERIFY466_OUT:-$H/.graphtraj/core/state/tasks/466-session-read-in-agents/realhost}
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
EXPECT_CLAUDE=2.1.325
SRC=$BASE/src
VV=$BASE/venv
SV=$BASE/suite-venv
P=$BASE/project
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next ($1 pastes): $2"; }
# Child commands run without this shell's GraphTraj Session variables (a Main's own would leak in).
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=${TMPDIR:-/tmp} LANG=${LANG:-en_US.UTF-8} "$@"; }
claude_version() {
  local C=${$(command -v claude):-none} V=$(claude --version 2>&1 | head -1)
  print -r -- "claude --version: $V ($C) | expected $EXPECT_CLAUDE: $([[ $V == $EXPECT_CLAUDE* ]] && print yes || print NO)"
}
copy_deps() {
  local S=($RT/lib/python*/site-packages(N)) D=($1/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/pyyaml-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $1/bin/python -I -c 'import importlib.metadata as m; print("deps: click", m.version("click"), "| pyyaml", m.version("pyyaml"), "| websockets", m.version("websockets"))')
}
probe() { (cd $P && clean $VV/bin/python -I $SD/probe.py "$@") }

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  claude_version
  print -r -- "launched via zsh: ${ZSH_VERSION:+yes ($ZSH_VERSION)} | script: $THIS"
  print "commit under test: $COMMIT | base: $BASE"
  git -C $WT cat-file -e $COMMIT^{commit} || { print "STOP: $COMMIT is not in $WT"; return 1; }
  say "scratch venv from $COMMIT (git archive; editable install; click/yaml/websockets copied read-only from production)"
  rm -rf $SRC $VV; mkdir -p $SRC; git -C $WT archive $COMMIT | tar -x -C $SRC || return 1
  $CONDA -m venv --system-site-packages $VV || return 1
  $VV/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $SRC/src/graftling -e $SRC 2>&1 | grep -vi cache
  copy_deps $VV || return 1
  (cd /tmp && $VV/bin/python -I $SD/probe.py fix $SRC/src -) || { print "STOP: the venv does not run the commit under test"; return 1; }
  say "isolated project $P (own git init, own .graphtraj from graphtraj setup)"
  rm -rf $P; mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 466 probe" > README.md && git add README.md \
      && git -c user.name=466 -c user.email=466@invalid commit -qm "Initial source") || return 1
  (cd $P && print y | clean $VV/bin/graphtraj setup | tail -2) || return 1
  probe prepare $P $MODEL || { print "STOP: probe Tasks are not ready (text above)"; return 1; }
  probe isolation $P - || { print "STOP: the project is not isolated"; return 1; }
  say "Claude settings of the project: no Harness CLAUDE.md/AGENTS.md (claudeMdExcludes) and no cc-plugin-agents-md (as verify-462)"
  $VV/bin/python -I -c 'import json, sys
from pathlib import Path
harness, path = sys.argv[1], Path(sys.argv[2])
settings = json.loads(path.read_text()) if path.is_file() else {}
settings["claudeMdExcludes"] = sorted({*settings.get("claudeMdExcludes", []), harness + "/CLAUDE.md",
    harness + "/CLAUDE.local.md", harness + "/.claude/CLAUDE.md", harness + "/**/CLAUDE.md", harness + "/**/CLAUDE.local.md",
    harness + "/AGENTS.md", harness + "/**/AGENTS.md"})
settings["enabledPlugins"] = {**settings.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + "\n")
print("claudeMdExcludes in", path, ":", settings["claudeMdExcludes"])
print("enabledPlugins in", path, ":", settings["enabledPlugins"])' $H $P/.claude/settings.local.json || return 1
  say "host answers one line with $MODEL (model and login source from the init record; no tool, no MCP)"
  (cd $P && clean claude -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' \
      > $OUT/00-model.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  probe init $OUT/00-model.jsonl $H \
      || { print "STOP: no MODEL OK, no init record, or a Harness instruction file was loaded (above). stderr:"; head -c 300 $OUT/00-model-stderr.txt
           print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  print ""
  print "Success: 'expected $EXPECT_CLAUDE: yes', 'launched via zsh: yes', '466 fix loaded: YES', deps click 8.5.0, 'roles OK',"
  print "ready tasks ['1', '2'], 'isolation: OK', 'init: ... model $MODEL | apiKeySource <name>', 'cc-plugin-agents-md loaded: NO',"
  print "'instruction files from the Harness: none', and 'result: MODEL OK | MEMORY: NONE'."
  next Main "zsh $THIS 01 2>&1 | tee $OUT/01.txt"
}

step_00u() {
  say "[00u] USER, only if 01 or 02 reports a folder-trust or login refusal. Plain macOS Terminal:"
  claude_version
  print "  cd $P && claude"
  print "Dialog: 'Do you trust the files in this folder?' (it names $P). Choose 'Yes, proceed'. Then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message. Any other dialog: Esc, and tell Main its title."
  next Main "the step that refused, again"
}

facts() {  # $1 task, $2 label; Task 2 also names Task 1's member from 01's output
  local F=$OUT/$2-facts.json
  if [[ $1 == 2 ]]; then
    $VV/bin/python -I -c 'import json, sys
source = json.load(open(sys.argv[2]))
json.dump({"task": "2", "out": sys.argv[3], "source_alias": source["alias"], "source_native": source["native"]}, open(sys.argv[1], "w"))
print("Task 1 member:", source["alias"], "| Session:", source["native"])' $F $OUT/01-facts.out.json $OUT/$2-facts.out.json || return 1
  else
    $VV/bin/python -I -c 'import json, sys; json.dump({"task": "1", "out": sys.argv[2]}, open(sys.argv[1], "w"))' $F $OUT/$2-facts.out.json
  fi
  print -r -- $F
}

step_01() {
  say "[01] Main. Task 1 member writes a conversation long enough to page; waits <= 9 min. Dialog: none (00u if refused)."
  claude_version
  [[ -x $VV/bin/agent-runner ]] || { print "STOP: run 00 first"; return 1; }
  local F=$(facts 1 01 | tail -1)
  probe run $P $F
  local rc=$?
  print ""
  if (( rc == 2 )); then next Main "zsh $THIS 01c 2>&1 | tee $OUT/01c.txt"; return $rc; fi
  print "Success: '== summary: ALL PASS' (CHECK 1-4): at least 12 text events and 10 tool calls, the marker before the last page,"
  print "the fake credential in the raw archive, DONE-466-T1."
  next Main "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
  return $rc
}

step_01c() {
  say "[01c] Main. collect-only for Task 1's existing member; dispatches nothing. Dialog: none."
  claude_version
  [[ -f $OUT/01-facts.json ]] || { print "STOP: no $OUT/01-facts.json; run 01 first"; return 1; }
  probe collect $P $OUT/01-facts.json
  local rc=$?
  print ""
  print "Success: '== summary: ALL PASS' (CHECK 1-4)."
  next Main "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
  return $rc
}

step_02() {
  say "[02] Main. Task 2 member reads Task 1's member Session with agents session_read; waits <= 9 min. Dialog: none (00u if refused)."
  claude_version
  [[ -f $OUT/01-facts.out.json ]] || { print "STOP: run 01 (or 01c) first"; return 1; }
  local F=$(facts 2 02 | tail -1)
  print -r -- "facts: $(cat $F)"
  probe run $P $F
  local rc=$?
  print ""
  if (( rc == 2 )); then next Main "zsh $THIS 02c 2>&1 | tee $OUT/02c.txt"; return $rc; fi
  print "Success: '== summary: ALL PASS': calls A, B, C each with a complete JSON tool_result, not is_error, no over-limit"
  print "notice; A indices == [-5:], B == [-10:-5], C's first hit == the probe's own; the fake credential redacted; no"
  print "credential value in Task 2's transcript; the member reports no Harness instruction file."
  next Main "zsh $THIS 03"
  return $rc
}

step_02c() {
  say "[02c] Main. collect-only for Task 2's existing member; dispatches nothing. Dialog: none."
  claude_version
  [[ -f $OUT/02-facts.json ]] || { print "STOP: no $OUT/02-facts.json; run 02 first"; return 1; }
  probe collect $P $OUT/02-facts.json
  local rc=$?
  print ""
  print "Success: as 02, '== summary: ALL PASS'."
  next Main "zsh $THIS 03"
  return $rc
}

step_03() {
  say "[03] Main. full suite at $(git -C $WT rev-parse --short HEAD) in the background. Dialog: none. <= 25 min."
  claude_version
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
  claude_version
  # Its own process group, stopped as a whole at the 25-minute limit (only what this step started).
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
  print "== baseline: compare with the dev full-suite run Main last used"
  print "== failures:"; cat $OUT/03-shards/failures.txt 2>/dev/null
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  00u) step_00u ;;
  01) step_01 ;;
  01c) step_01c ;;
  02) step_02 ;;
  02c) step_02c ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|01c|02|02c|03>" ;;
esac
