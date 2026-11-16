#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 487: failure rates of the suite's intermittent tests, before (dev) and after (candidate), and the full suite.
#   zsh <this file> <R0|R1|SUITE>      (from any directory; Harness root or this Worktree)
# R0: dev 5a451267; R1: the candidate commit (this checkout's HEAD, or VERIFY487_CANDIDATE); SUITE: candidate full suite.
# Each step: a fresh git clone of the exact commit under Harness tmp/487, its own test venv (dependencies linked
# read-only from production .venv-runtime into the venv's own site-packages, as verify-482/484), pytest temp in
# ${TMPDIR:-/tmp} (refused if inside the Harness). Dialog: none (no model, no native host). Run one at a time,
# not alongside another Task's suite. Bounded waits: R0/R1 900 s + 20 s stop (about 15 min with setup); SUITE 1500 s.
# R0/R1 runs: 6 workers x (core set x6 = 36 runs each, slow D/G x2 = 12 each, observe-only files x1 = 6 each, last).
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY487_BASE:-$H/tmp/487}
OUT=${VERIFY487_OUT:-$H/.graphtraj/core/state/tasks/487-suite-intermittent-failures/realhost}
DEV=5a451267
CAND=${VERIFY487_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
STEP=${1:-help}
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
TMPB=${TMPDIR:-/tmp}
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8} "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }

check_tmp() {
  print "pytest temp base: ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != $H* ]] && print YES || print NO)"
  [[ ${TMPB:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}

# build <commit> <dir>: clone the exact commit to <dir>/src and make <dir>/venv importing it (verify-484 S).
build() {
  local commit=$1 dir=$2
  local src=$dir/src venv=$dir/venv
  rm -rf $dir && mkdir -p $dir || return 1
  git clone -q --no-checkout $SRC $src && git -C $src checkout -q --detach $commit || { print "STOP: checkout of $commit failed"; return 1; }
  print "checkout: $src at $(git -C $src rev-parse HEAD)"
  [[ -d $DEPS ]] || { mkdir -p $DEPS; for x in $RTSP/*(N); do case ${x:t} in
      graphtraj*|graftling*|__editable__*|*.pth|pip|pip-*|_distutils_hack|__pycache__) ;; *) ln -s $x $DEPS/ ;; esac; done; }
  $(base_python) -m venv --system-site-packages $venv || return 1
  local site=$($venv/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  # Dependencies in the venv's own purelib: the suite's nested venv reads only that directory (484).
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  clean $venv/bin/python -m pip install -q --no-deps --no-build-isolation --no-index -e $src/src/graftling -e $src 2>&1 | grep -vi cache
  (( ${pipestatus[1]} == 0 )) || { print "STOP: test venv install failed (text above)"; return 1; }
  local nest=$dir/nested-check
  $venv/bin/python -m venv --system-site-packages $nest \
    && print -r -- $site > $($nest/bin/python -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/graphtraj_test_dependencies.pth \
    && clean $nest/bin/python -I -c 'import websockets, click, yaml' \
    && print "nested venv imports: OK" || { print "STOP: nested venv imports failed (error above)"; return 1; }
  rm -rf $nest
  clean $venv/bin/python -I -c 'import sys, graphtraj, graftling
ok = all(m.__file__.startswith(sys.argv[1]) for m in (graphtraj, graftling))
print("test venv imports the checkout:", "OK" if ok else "NO", graphtraj.__file__, graftling.__file__); sys.exit(0 if ok else 1)' $src/src \
    || { print "STOP: the test venv does not import the checkout"; return 1; }
}

run_repeat() {
  local name=$1 commit=$2
  say "[$name] scoped intermittent tests repeated under 6 parallel workers on $commit. Dialog: none. Limit 900 s (+20 s stop)."
  check_tmp || return 1
  build $commit $BASE/$name || return 1
  local res=$OUT/$name-repeat
  rm -rf $res; mkdir -p $res
  print "== start $(date +%T)"
  (cd $BASE/$name/src && clean $BASE/$name/venv/bin/python -I $SD/repeat.py $BASE/$name/src $res \
     --workers ${VERIFY487_WORKERS:-6} --fast ${VERIFY487_FAST:-6} --slow ${VERIFY487_SLOW:-2} --observe ${VERIFY487_OBSERVE:-1} --limit 900)
  print "== end $(date +%T); counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
}

step_R0() { run_repeat R0 $DEV; next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"; }
step_R1() {
  run_repeat R1 $CAND
  [[ -f $OUT/R0-repeat/counts.txt ]] && { say "R0 (dev $DEV) counts for comparison"; cat $OUT/R0-repeat/counts.txt; }
  next "zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py). Dialog: none. Limit 1500 s."
  check_tmp || return 1
  build $CAND $BASE/suite || return 1
  local src=$BASE/suite/src VT=$BASE/suite/venv L=$OUT/SUITE-shards
  local cmd=(env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$VT/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8}
             $VT/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 1500 s limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $VT/bin/python $src/scripts/run_test_shards.py --shards 6 --log-dir $L)
  rm -rf $L; mkdir -p $L
  print "== start $(date +%T) commit $(git -C $src rev-parse HEAD)"
  (cd $src && $cmd) > $OUT/SUITE-suite.txt 2>&1
  local rc=$?
  print "== shards exit $rc at $(date +%T); output $OUT/SUITE-suite.txt, shard logs $L/"
  tail -n 4 $OUT/SUITE-suite.txt
  touch $L/failures.txt
  print "== failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  print "== dev comparison: 478/484 suites on dev ancestors had 0 failed (484 S); dev $DEV's intermittent set is R0 above."
  print "   Any failure listed here that is not one of R0's intermittent tests is NEW. Totals: $(grep -E '[0-9]+ (passed|failed)' $OUT/SUITE-suite.txt | tail -1)"
  if [[ $rc == 0 && ! -s $L/failures.txt ]]; then print "PASS SUITE no failures"
  else print "CHECK SUITE (shards exit $rc): compare the failures above with $OUT/R0-repeat/counts.txt"; fi
  next "report $OUT/R0.txt, R1.txt, SUITE.txt to the 487 Leader"
}

dispatch() {
case $STEP in
  R0) step_R0 ;;
  R1|SUITE) step_$STEP ;;
  *) print "usage: zsh $THIS <R0|R1|SUITE>   e.g. zsh $THIS R0 2>&1 | tee $OUT/R0.txt" ;;
esac
}
dispatch; exit $?
