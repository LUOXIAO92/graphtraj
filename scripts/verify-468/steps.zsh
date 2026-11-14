#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 468 real-host check: the Runner Worker of an actively working real Claude Task member, before and after.
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/468-runner-worker-busy-cpu/scripts/verify-468/steps.zsh <00|00u|01|02|03>
# 00  Main. preflight: claude --version, scratch venvs BEFORE (cfd7f688) and AFTER (the candidate), one isolated
#     project each (own git, own .graphtraj, Claude settings without the Harness instruction files), probe Task 1
#     ready in each, one-line host answer.
# 00u USER, only if 01 or 02 reports a folder-trust or login refusal.
# 01  Main. BEFORE: a member works several minutes (many short Bash calls with output); its Worker's CPU is
#     sampled with ps every ~10 s.
# 02  Main. AFTER: the same with the candidate, then BEFORE and AFTER side by side with the verdict.
# 03  Main. full suite at the Worktree HEAD in the background (self-stopping after 25 min; ends with '== totals:').
# Never touches production .venv-runtime (only copies click, yaml and websockets out of it, read only), the user's
# dotfiles, ~/.claude, ~/.codex or the Claude install. No key value is read or printed. No step signals a process
# it did not start.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
WT=$H/.graphtraj/core/worktrees/468-runner-worker-busy-cpu
SD=${0:A:h}
THIS=${0:A}
BEFORE_COMMIT=cfd7f688
AFTER_COMMIT=${VERIFY468_COMMIT:-$(git -C $WT rev-parse HEAD)}
BASE=$H/tmp/468/verify
OUT=$BASE/out
RT=$H/.venv-runtime
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
MODEL=claude-opus-5-5
EXPECT_CLAUDE=2.1.325
SV=$BASE/suite-venv
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
# $1 label (before|after): its venv, source and project.
venv() { print -r -- $BASE/venv-$1; }
src() { print -r -- $BASE/src-$1; }
project() { print -r -- $BASE/project-$1; }
probe() { local L=$1; shift; (cd $(project $L) && clean $(venv $L)/bin/python -I $SD/probe.py "$@") }

build() {  # $1 label, $2 commit
  local S=$(src $1) V=$(venv $1) P=$(project $1)
  say "$1: scratch venv from $2 (git archive; editable install; click/yaml/websockets copied read-only from production)"
  git -C $WT cat-file -e $2^{commit} || { print "STOP: $2 is not in $WT"; return 1; }
  rm -rf $S $V; mkdir -p $S; git -C $WT archive $2 | tar -x -C $S || return 1
  $CONDA -m venv --system-site-packages $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $S/src/graftling -e $S 2>&1 | grep -vi cache
  copy_deps $V || return 1
  (cd /tmp && $V/bin/python -I $SD/probe.py fix $S/src -) || { print "STOP: the $1 venv does not run $2"; return 1; }
  say "$1: isolated project $P (own git init, own .graphtraj from graphtraj setup)"
  rm -rf $P; mkdir -p $P
  print "Claude settings: no Harness CLAUDE.md/AGENTS.md (claudeMdExcludes) and no cc-plugin-agents-md, in the project's"
  print ".claude/settings.local.json and in a tracked .claude/settings.json committed before setup (so the member's"
  print "Task Worktree carries it), as verify-462 and verify-466."
  $V/bin/python -I -c 'import json, sys
from pathlib import Path
harness = sys.argv[1]
for path in map(Path, sys.argv[2:]):
    settings = json.loads(path.read_text()) if path.is_file() else {}
    settings["claudeMdExcludes"] = sorted({*settings.get("claudeMdExcludes", []), harness + "/CLAUDE.md",
        harness + "/CLAUDE.local.md", harness + "/.claude/CLAUDE.md", harness + "/**/CLAUDE.md", harness + "/**/CLAUDE.local.md",
        harness + "/AGENTS.md", harness + "/**/AGENTS.md"})
    settings["enabledPlugins"] = {**settings.get("enabledPlugins", {}), "cc-plugin-agents-md@builtin": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print("written:", path)' $H $P/.claude/settings.json $P/.claude/settings.local.json || return 1
  (cd $P && git init -q -b main && print -r -- "# 468 probe" > README.md && git add README.md .claude/settings.json \
      && git -c user.name=468 -c user.email=468@invalid commit -qm "Initial source with Claude settings") || return 1
  (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  probe $1 prepare $P $MODEL || { print "STOP: the $1 probe Task is not ready (text above)"; return 1; }
  probe $1 isolation $P - || { print "STOP: the $1 project is not isolated"; return 1; }
}

step_00() {
  say "[00] Main. preflight. Dialog: none. Output also in $OUT/00.txt"
  claude_version
  print -r -- "launched via zsh: ${ZSH_VERSION:+yes ($ZSH_VERSION)} | script: $THIS"
  print "BEFORE commit: $BEFORE_COMMIT | AFTER commit: $AFTER_COMMIT | base: $BASE"
  build before $BEFORE_COMMIT || return 1
  build after $AFTER_COMMIT || return 1
  say "host answers one line with $MODEL in the AFTER project (model and login source from the init record; no tool, no MCP)"
  (cd $(project after) && clean claude -p --model $MODEL --output-format stream-json --verbose --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
      <<< 'Reply with exactly two lines. Line 1: MODEL OK. Line 2: MEMORY: then the absolute path of every CLAUDE.md or AGENTS.md file whose contents were given to you as instructions, separated by spaces, or NONE. Use no tool.' \
      > $OUT/00-model.jsonl 2> $OUT/00-model-stderr.txt)
  print "claude -p rc=$?"
  probe after init $OUT/00-model.jsonl $H \
      || { print "STOP: no MODEL OK, no init record, or a Harness instruction file was loaded (above). stderr:"; head -c 300 $OUT/00-model-stderr.txt
           print "\nIf it says 'login' or 'API key': USER logs in with 'claude' in Terminal, then rerun 00."; return 1; }
  print ""
  print "Success: 'expected $EXPECT_CLAUDE: yes', 'launched via zsh: yes', '468 fix loaded: NO' for BEFORE and 'YES' for"
  print "AFTER, deps click 8.5.0, 'roles OK' and 'probe Task ready: YES' twice, 'isolation: OK' twice,"
  print "'init: ... model $MODEL | apiKeySource <name>', 'cc-plugin-agents-md loaded: NO', 'Harness instruction files"
  print "loaded: none' and 'result: MODEL OK | MEMORY: NONE'."
  next Main "zsh $THIS 01 2>&1 | tee $OUT/01.txt"
}

step_00u() {
  say "[00u] USER, only if 01 or 02 reports a folder-trust or login refusal. Plain macOS Terminal:"
  claude_version
  print "  cd $(project before) && claude      (for 01; for 02 use $(project after))"
  print "Dialog: 'Do you trust the files in this folder?' (it names the project). Choose 'Yes, proceed'. Then /exit."
  print "If it asks to log in instead, log in, then /exit. Send no message. Any other dialog: Esc, and tell Main its title."
  next Main "the step that refused, again"
}

member() {  # $1 label
  [[ -x $(venv $1)/bin/agent-runner ]] || { print "STOP: run 00 first"; return 1; }
  local F=$OUT/$1-facts.json
  $(venv $1)/bin/python -I -c 'import json, sys; json.dump({"label": sys.argv[2], "out": sys.argv[3]}, open(sys.argv[1], "w"))' \
      $F ${(U)1} $OUT/$1.json || return 1
  probe $1 run $(project $1) $F
}

step_01() {
  say "[01] Main. BEFORE ($BEFORE_COMMIT): one member works <= 9 min; its Worker sampled every ~10 s. Dialog: none (00u if refused)."
  claude_version
  member before
  local rc=$?
  print ""
  if (( rc == 2 )); then print "Task 1 of the BEFORE project already has a member: rerun 00 for fresh projects."; return $rc; fi
  print "Success: raw ps lines of the Worker every ~10 s while the member works, then"
  print "'Worker CPU while the member worked: ... = <ratio> CPU-s per wall-s' and '== BEFORE: <ratio>'."
  next Main "zsh $THIS 02 2>&1 | tee $OUT/02.txt"
  return $rc
}

step_02() {
  say "[02] Main. AFTER ($AFTER_COMMIT): the same member work; then BEFORE vs AFTER. Dialog: none (00u if refused)."
  claude_version
  [[ -f $OUT/before.json ]] || { print "STOP: run 01 first"; return 1; }
  member after
  local rc=$?
  print ""
  if (( rc == 2 )); then print "Task 1 of the AFTER project already has a member: rerun 00 for fresh projects."; return $rc; fi
  say "BEFORE vs AFTER"
  probe after compare $OUT/before.json $OUT/after.json
  rc=$?
  print ""
  print "Success: '== verdict: PASS': AFTER below 0.25 CPU-s per wall-s and below BEFORE."
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
  02) step_02 ;;
  03) step_03 ;;
  _03run) step__03run ;;
  *) print "usage: zsh ${0:A} <00|00u|01|02|03>" ;;
esac
