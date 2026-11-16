#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 490: the idle budget timer ends when its work ends and collects the Worker its delivery starts;
# cleanup does not count an ended (zombie) Worker as executing; tests leave no timer behind.
#   zsh <this file> <00|A|B|SUITE>      order: 00 -> A -> B -> SUITE (from any directory)
# ISOLATED project under the Harness tmp/490 (own git and .graphtraj); candidate commit archived and installed into
# tmp/490/venv; production .venv-runtime only read (dependencies linked). The steps never signal a process they did
# not start. pytest temp: ${TMPDIR:-/tmp}, refused if inside the Harness.
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY490_BASE:-$H/tmp/490}
P=$BASE/project
V=$BASE/venv
PY=$V/bin/python
DEPS=$BASE/deps
OUT=${VERIFY490_OUT:-$H/.graphtraj/core/state/tasks/490-budget-idle-timer-reaps-worker/realhost}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
DEV=1524730b
CAND=${VERIFY490_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
MODEL=claude-opus-5-5
STEP=${1:-help}
TMPB=${TMPDIR:-/tmp}
# VERIFY490_STUB_BIN (rehearsal only) puts stub claude/ps first.
path=(${VERIFY490_STUB_BIN:+$VERIFY490_STUB_BIN} /opt/homebrew/bin $HOME/.local/bin /usr/bin /bin /usr/sbin /sbin)
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): zsh $THIS $1 2>&1 | tee $OUT/$1.txt"; }
# No GraphTraj/Graftling Session variables of Main leak in.
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$TMPB \
  LANG=${LANG:-en_US.UTF-8} "$@"; }
# x490 <command> [args]: the helper with the candidate venv, inside the project.
x490() { local command=$1; shift; (cd $P && clean $PY -I $SD/x490.py $command $P "$@"); }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
check_tmp() {
  print "pytest temp base: ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != $H* ]] && print YES || print NO)"
  [[ ${TMPB:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}
link_deps() {
  [[ -d $DEPS ]] || { mkdir -p $DEPS; for x in $RTSP/*(N); do case ${x:t} in
      graphtraj*|graftling*|__editable__*|*.pth|pip|pip-*|_distutils_hack|__pycache__) ;; *) ln -s $x $DEPS/ ;; esac; done; }
}
# venv <dir> <pip args...>: base Python; dependencies linked into the venv's own purelib (484).
make_venv() {
  local dir=$1; shift
  link_deps
  rm -rf $dir && $(base_python) -m venv --system-site-packages $dir || return 1
  local site=$($dir/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  clean $dir/bin/python -m pip install -q --no-deps --no-build-isolation --no-index "$@" 2>&1 | grep -vi cache
  return ${pipestatus[1]}
}
# launch <task id> <name> <role> <instruction>: one root member through agent-runner; prints its alias.
launch() {
  local batch=$P/.graphtraj/probe-490/batch-$1.yml
  print -r -- "tasks:
  - task_id: \"$1\"
    task_name: $2
    role: $3
    instruction: \"$4\"" > $batch
  (cd $P && clean $V/bin/agent-runner --swarm-input $batch) > $OUT/$STEP-launch-$1.yml 2>&1
  local rc=$?
  grep -m1 "alias:" $OUT/$STEP-launch-$1.yml | awk '{print $NF}'
  return $rc
}
# wait_end <alias> <seconds>: the Session's execution.yml shows a terminal outcome.
wait_end() {
  local f=$P/.graphtraj/runner/sessions/$1/execution.yml i=0
  while (( i < $2 )); do [[ -f $f ]] && grep -q "outcome:" $f && { print "$1 ended: $(grep -m1 'outcome:' $f)"; return 0; }
    sleep 2; (( i += 2 )); done
  print "STOP: $1 did not end within $2 s"; return 1
}
cleanup() { (cd $P && clean $V/bin/agent-runner cleanup --task-id $1) > $OUT/$STEP-cleanup-$1.yml 2>&1; local rc=$?
  print "cleanup $1: rc $rc | $(grep -m1 -E 'cleanup_status|code:' $OUT/$STEP-cleanup-$1.yml)"; return $rc; }

step_00() {
  say "[00] preflight via /bin/zsh. Dialog: none. Waits: claude <= 120 s."
  print "ZSH_VERSION=${ZSH_VERSION:-not-zsh}; candidate $CAND (uncommitted paths in $SRC: $(git -C $SRC status --porcelain | wc -l | tr -d ' ')); BASE=$BASE"
  check_tmp || return 1
  say "candidate venv $V: commit archived to $BASE/candidate and installed editable from there"
  if [[ $(cat $V/.candidate 2>/dev/null) != $CAND ]]; then
    rm -rf $BASE/candidate && mkdir -p $BASE/candidate && git -C $SRC archive $CAND | tar -x -C $BASE/candidate || return 1
    make_venv $V -e $BASE/candidate/src/graftling -e $BASE/candidate || { print "STOP: candidate install failed (text above)"; return 1; }
    print -r -- $CAND > $V/.candidate
  else print "venv already holds $CAND: install skipped (rerun)"; fi
  clean $PY -I -c 'import sys, graphtraj, graftling
from pathlib import Path
ok = all(Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()) for m in (graphtraj, graftling))
print("candidate imports:", graphtraj.__file__, "| from the archived commit:", ok); sys.exit(0 if ok else 1)' $BASE/candidate \
    || { print "STOP: the venv does not import the candidate"; return 1; }
  say "isolated project $P (own git and .graphtraj)"
  if [[ -d $P/.git ]]; then print "existing project: git init and setup skipped (rerun)"; else
    mkdir -p $P; (cd $P && git init -q -b main && print -r -- "# 490 probe" > README.md && git add README.md \
      && git -c user.name=490 -c user.email=490@invalid commit -qm "Initial source") || return 1
    (cd $P && print y | clean $V/bin/graphtraj setup | tail -2) || return 1
  fi
  (cd $P && clean $PY -I -c 'import sys
from pathlib import Path
from graphtraj.workspace.runner_project import discover_runner_directory
found = Path(discover_runner_directory(Path.cwd())).resolve(); own = (Path.cwd() / ".graphtraj/runner").resolve()
print("graphtraj runner directory:", found, "| project own:", found == own); sys.exit(0 if found == own else 1)') \
    || { print "STOP: GraphTraj does not resolve the project's own .graphtraj"; return 1; }
  x490 prepare || { print "STOP: roles or probe Tasks not ready (text above)"; return 1; }
  say "host the steps use, one read-only call: claude -p --model $MODEL (limit 120 s)"
  (cd $P && clean /usr/bin/perl -e 'alarm 120; exec @ARGV' claude -p --model $MODEL "Reply with exactly one line: CLAUDE-OK $MODEL. Use no tool." > $OUT/00-claude.txt 2>&1)
  local line=$(grep -v '^\s*$' $OUT/00-claude.txt | tail -1)
  [[ $line == CLAUDE-OK* ]] && print "claude answer: OK | $line (logged in)" || { print "STOP 00: claude did not answer: ${line:-none}"; return 1; }
  say "timers of this project before A (expected 0)"; x490 timers
  next A
}

step_A() {
  say "[A] Task 2 (30-minute budget): a root member ends -> its idle timer waits; the Task is accepted, integrated and cleaned -> the timer is gone within ~10 s and sent nothing. Dialog: none (the member uses no tool). Waits: member <= 300 s, timer <= 30 s."
  local alias=$(launch 2 timer-a member "Reply with one line DONE. Use no tool.")
  [[ -n $alias ]] || { print "STOP: launch failed:"; cat $OUT/A-launch-2.yml; return 1; }
  print "member alias: $alias"
  wait_end $alias 300 || return 1
  sleep 2; x490 timers | tee $OUT/A-timers-before.txt
  grep -q "session $alias" $OUT/A-timers-before.txt || { print "STOP A: no timer was started for $alias (nothing to observe)"; return 1; }
  say "accept + integrate + cleanup Task 2"
  x490 accept 2 || return 1
  local t0=$(date +%s) gone=""
  while (( $(date +%s) - t0 < 30 )); do
    x490 timers | grep -q "session $alias" || { gone=$(( $(date +%s) - t0 )); break; }; sleep 1; done
  [[ -n $gone ]] && print "timer of $alias: gone ${gone} s after integration" || print "timer of $alias: STILL RUNNING 30 s after integration"
  cleanup 2
  local crc=$?
  say "budget notices recorded in this project (expected none for $alias)"; x490 notices | tee $OUT/A-notices.txt
  if [[ -n $gone && $crc == 0 ]] && ! grep -q " $alias " $OUT/A-notices.txt; then print "PASS A"; else print "FAIL A (above)"; fi
  next B
}

step_B() {
  say "[B] Task 1 (1-minute budget): a Leader launches one Engineer; both end. The steps remove the Leader's own timer record (its exit without a signal) so the Engineer's timer is the observer. At the planned end it delivers to the idle Leader, starting the Leader's Worker as the timer's child. The Worker must be collected (no <defunct>), and the Task then cleans up. Dialog: none expected (the Leader's agents launch is inside role_tree). Waits: Leader <= 300 s, delivery <= 180 s, watch 240 s."
  local alias=$(launch 1 timer-b leader "Use your GraphTraj agents tool to launch exactly one child with role engineer for this Task and the instruction: Reply with one line DONE. Use no tool. Wait for its result, then reply with one line DONE.")
  [[ -n $alias ]] || { print "STOP: launch failed:"; cat $OUT/B-launch-1.yml; return 1; }
  print "Leader alias: $alias"
  wait_end $alias 300 || return 1
  local eng=$(ls $P/.graphtraj/runner/sessions | grep -m1 "engineer")
  [[ -n $eng ]] && wait_end $eng 120 || { print "STOP B: no Engineer Session was launched (Leader output in $P/.graphtraj/runner/sessions/$alias)"; return 1; }
  sleep 2; x490 timers | tee $OUT/B-timers.txt
  rm -f $P/.graphtraj/runner/sessions/$alias/budget-timer.yml && print "removed the Leader's own timer record"
  say "watching the Leader for the Worker the Engineer's timer starts"
  x490 watch $alias 180; local wrc=$?
  x490 notices | tee $OUT/B-notices.txt
  say "accept + integrate + cleanup Task 1"
  x490 accept 1 && cleanup 1; local crc=$?
  sleep 8; x490 timers
  [[ $wrc == 0 && $crc == 0 ]] && print "PASS B" || print "FAIL B (watch $wrc, cleanup $crc)"
  next SUITE
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), failing files once on dev $DEV (verify-487 devcheck); then timers left by the suite. Dialog: none. Limits: suite 1500 s, dev recheck 600 s."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc D=$BASE/suite
  if [[ -n ${VERIFY490_FAILURES:-} ]]; then
    print "REHEARSAL: suite not run; failures from $VERIFY490_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY490_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
  else
    rm -rf $D; mkdir -p $D
    git clone -q --no-checkout $SRC $D/src && git -C $D/src checkout -q --detach $CAND || return 1
    make_venv $D/venv -e $D/src/src/graftling -e $D/src || { print "STOP: suite venv install failed"; return 1; }
    rm -rf $L; mkdir -p $L
    print "== start $(date +%T) commit $(git -C $D/src rev-parse HEAD)"
    (cd $D/src && env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$D/venv/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB \
       LANG=${LANG:-en_US.UTF-8} /usr/bin/perl -e 'alarm 1500; exec @ARGV' $D/venv/bin/python $D/src/scripts/run_test_shards.py \
       --shards 6 --log-dir $L) > $OUT/SUITE-suite.txt 2>&1
    rc=$?
  fi
  print "== shards exit $rc at $(date +%T); output $OUT/SUITE-suite.txt, shard logs $L/"
  tail -n 4 $OUT/SUITE-suite.txt
  touch $L/failures.txt
  print "== failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  if [[ -s $L/failures.txt ]]; then
    say "dev comparison: failing files once on dev $DEV"
    local DD=$BASE/dev
    if [[ $(git -C $DD/src rev-parse HEAD 2>/dev/null) != $(git -C $SRC rev-parse $DEV) || ! -x $DD/venv/bin/python ]]; then
      rm -rf $DD; mkdir -p $DD
      git clone -q --no-checkout $SRC $DD/src && git -C $DD/src checkout -q --detach $DEV || return 1
      make_venv $DD/venv -e $DD/src/src/graftling -e $DD/src || return 1
    else print "dev clone reused: $DD/src"; fi
    (cd $DD/src && clean $DD/venv/bin/python -I $SRC/scripts/verify-487/devcheck.py $L/failures.txt 600)
    [[ $? == 0 ]] && print "SUITE failures: none NEW (each fails on dev too)" || print "SUITE failures: NEW or unclassified (above)"
  else
    [[ $rc == 0 ]] && print "SUITE failures: none" || print "SUITE: shards exit $rc with no failing id"
  fi
  say "timers the suite left: session-end reclaim lines per shard, then a process scan for this run id"
  local run=$(grep -m1 -o "test run id: [0-9a-f]*" $OUT/SUITE-suite.txt | awk '{print $4}')
  print "test run id: ${run:-none}"
  local found=$(cat $L/shard-*.log(N) 2>/dev/null | grep -c "graphtraj.execution.budget_idle_timer")
  grep -h "leftover test processes" $L/shard-*.log(N)
  print "budget timers the shards' session-end reclaim had to stop: $found"
  local left=$(ps -Eww -x -o pid=,command= | grep "graphtraj.execution.budget_idle_timer" | grep -c "PYTEST_GRAPHTRAJ_RUN=${run:-none}-")
  print "budget timers of run ${run:-none} still running now: $left"
  [[ $left == 0 ]] && print "PASS SUITE-timers (none left)" || print "FAIL SUITE-timers ($left left)"
  next "report $OUT/*.txt to the 490 Leader"
}

case $STEP in
  00|A|B|SUITE) step_$STEP ;;
  *) print "usage: zsh $THIS <00|A|B|SUITE>   e.g. zsh $THIS 00 2>&1 | tee $OUT/00.txt" ;;
esac
