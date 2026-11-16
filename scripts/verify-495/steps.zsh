#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 495: the 459 redaction test (and the rest of the 459 and 495 test files) under 491's parallel-load method
# on the candidate, then the candidate's full suite with a dev comparison.
#   zsh <this file> <P|R1|SUITE>      (in this order, one at a time; from any directory)
# Dialog: none in every step (no model, no native host, no Claude Code). Run on a quiet host, not alongside
# another Task's suite.
# P:     preflight: TMPDIR outside the Harness (printed), versions, CPU count, load; builds the dev ad1ccabc clone
#        (tmp/495/dev) and the candidate clone (tmp/495/R1). ~3 min.
# R1:    candidate: tests/test_tool_descendants_459.py + tests/test_tool_descendant_argv_refresh_495.py, 6 repeat
#        workers (scripts/verify-487/repeat.py) x VERIFY495_PASSES (default 30) passes, plus VERIFY495_SPIN (default:
#        the CPU count) CPU spinners (scripts/verify-491/load.py), loadavg logged every 15 s. ~5.5 s per pass on a
#        quiet host. Limit 780 s (+20 s stop; unfinished passes are not counted): <= 15 min. PASS only on 0 failures
#        of the redaction test. Prints 491's R0 (dev) and R1 counts of it for comparison; dev is not repeated again.
# SUITE: candidate full suite, 6 shards (scripts/run_test_shards.py) from a fresh git clone, then its failing files
#        once on dev ad1ccabc (scripts/verify-487/devcheck.py). Limits 1500 s + 600 s: plan 35 min.
# Each clone: the exact commit under Harness tmp/495, its own test venv (dependencies linked read-only from
# production .venv-runtime into the venv's own site-packages, as verify-487/491), pytest temp in ${TMPDIR:-/tmp}
# (refused if inside the Harness).
set -u
setopt no_bg_nice   # the background load runs at normal priority
H=${VERIFY495_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
V487=${SD:h}/verify-487
V491=${SD:h}/verify-491
BASE=${VERIFY495_BASE:-$H/tmp/495}
OUT=${VERIFY495_OUT:-$H/.graphtraj/core/state/tasks/495-tool-descendant-argv-refresh/realhost}
R491=${VERIFY495_R491:-$H/.graphtraj/core/state/tasks/491-test-stability-follow-up/realhost}
DEV=ad1ccabc
CAND=${VERIFY495_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=${VERIFY495_RT:-$H/.venv-runtime}
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
STEP=${1:-help}
REDACTION=tests/test_tool_descendants_459.py::test_recorded_and_reported_command_lines_are_redacted
REFRESH=tests/test_tool_descendant_argv_refresh_495.py
TARGETS=(tests/test_tool_descendants_459.py $REFRESH)
[[ -n ${VERIFY495_TESTS:-} ]] && TARGETS=(${(s:,:)VERIFY495_TESTS})   # rehearsal only
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
TMPB=${TMPDIR:-/tmp}
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8} "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
load() { print -r -- "$(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null || uptime)"; }

check_tmp() {
  print "pytest temp base: ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != $H* ]] && print YES || print NO)"
  [[ ${TMPB:A} != $H* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}

# build <commit> <dir>: clone the exact commit to <dir>/src and make <dir>/venv importing it (verify-491 build).
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
  clean $venv/bin/python -I -c 'import os, sys, graphtraj, graftling
ok = all(os.path.realpath(m.__file__).startswith(os.path.realpath(sys.argv[1])) for m in (graphtraj, graftling))
print("test venv imports the checkout:", "OK" if ok else "NO", graphtraj.__file__, graftling.__file__); sys.exit(0 if ok else 1)' $src/src \
    || { print "STOP: the test venv does not import the checkout"; return 1; }
}

# Reuse tmp/495/<name> when its clone is at <commit> and its venv exists; else build it.
ensure() {
  local name=$1 commit=$2 D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
}

step_P() {
  say "[P] preflight: TMPDIR, versions, CPUs, load; builds dev $DEV ($BASE/dev) and candidate $CAND ($BASE/R1). Dialog: none. No model, no host. ~3 min."
  check_tmp || return 1
  print "zsh $ZSH_VERSION | git $(git --version | cut -d' ' -f3) | runtime python $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0])')"
  print "CPUs: $(sysctl -n hw.ncpu 2>/dev/null || print unknown) | $(load)"
  print "dev $DEV = $(git -C $SRC rev-parse $DEV) | candidate $CAND | candidate changes vs dev:"
  git -C $SRC diff --stat $DEV $CAND -- src tests scripts | tail -n 6
  ensure dev $DEV || return 1
  ensure R1 $CAND || return 1
  print "PASS P (clones and venvs ready under $BASE)"
  next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"
}

step_R1() {
  local limit=${VERIFY495_LIMIT:-780} spin=${VERIFY495_SPIN:-$(sysctl -n hw.ncpu 2>/dev/null || print 8)}
  local workers=${VERIFY495_WORKERS:-6} passes=${VERIFY495_PASSES:-30}
  say "[R1] ${#TARGETS} targets x$passes passes on each of $workers workers, plus $spin CPU spinners, on candidate $CAND (491's method). Dialog: none. Limit $limit s (+20 s stop)."
  print -l -- "  "$^TARGETS
  check_tmp || return 1
  ensure R1 $CAND || return 1
  local res=$OUT/R1-repeat
  rm -rf $res; mkdir -p $res
  print "CPUs: $(sysctl -n hw.ncpu 2>/dev/null || print unknown) | start $(load)" | tee $res/loadavg.txt
  # Background load (verify-491/load.py): spinners and a loadavg log, bounded by the limit + 30 s, stopped right
  # after the run. env execs Python, so $! is load.py itself; its output never reaches this step's pipe.
  env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=$TMPB $BASE/R1/venv/bin/python -I $V491/load.py $spin $(( limit + 30 )) $res/loadavg.txt \
    < /dev/null > /dev/null 2>&1 &
  local loader=$!
  print "== start $(date +%T)"
  (cd $BASE/R1/src && clean $BASE/R1/venv/bin/python -I $V487/repeat.py $BASE/R1/src $res \
     --tests ${(j:,:)TARGETS} --workers $workers --fast $passes --limit $limit)
  kill -TERM $loader 2>/dev/null; wait $loader 2>/dev/null
  print "end $(load)" >> $res/loadavg.txt
  print "== end $(date +%T); loadavg (start, every 15 s, end) $res/loadavg.txt:"
  cat $res/loadavg.txt
  print "counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
  say "491 counts of the redaction test for comparison (dev baseline reused from 491, not repeated)"
  for name in R0 R1; do
    print -r -- "491 $name: $(grep -F -- $REDACTION $R491/$name-repeat/counts.txt 2>/dev/null || print 'not found')"
  done
  # PASS needs 0 failures (and >0 passes) for the redaction test and for every test of the 495 file;
  # the other rows are printed above as they are.
  local ids=($REDACTION ${(f)"$(grep -o -- "$REFRESH::[A-Za-z0-9_]*" $res/counts.txt 2>/dev/null)"})
  (( ${#ids} >= 3 )) || print "FAIL R1: the 495 file's tests are missing from $res/counts.txt"
  local ok=$(( ${#ids} >= 3 )) id row failed passed
  for id in $ids; do
    row=$(grep -F -- "$id" $res/counts.txt 2>/dev/null | head -1)
    failed=${${(z)row}[1]:-} passed=${${(z)row}[2]:-}
    print -r -- "495 R1: ${row:-not found: $id}"
    [[ -n $row && $failed == 0 && ${passed:-0} -gt 0 ]] || ok=0
  done
  if (( ok )); then
    print "PASS R1: 0 failures for the redaction test (491: dev 16/180, 491 candidate 13/180) and every 495 test"
  else
    print "FAIL R1: a failing or missing redaction/495 test above (raw text in $res/failures/)"
  fi
  next "zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), then its failing files once on dev $DEV. Dialog: none. Limits: suite 1500 s, dev recheck 600 s."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc
  if [[ -n ${VERIFY495_FAILURES:-} ]]; then
    # Rehearsal of the dev comparison only (Main never sets it): no suite, the given failures file.
    print "REHEARSAL: suite not run; failures from $VERIFY495_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY495_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
  else
  build $CAND $BASE/suite || return 1
  local src=$BASE/suite/src VT=$BASE/suite/venv
  local cmd=(env -i HOME=$HOME USER=${USER:-luoxiao} PATH=$VT/bin:/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8}
             $VT/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[2:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=float(sys.argv[1])))
except subprocess.TimeoutExpired:
    print("== limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' ${VERIFY495_SUITE_LIMIT:-1500} $VT/bin/python $src/scripts/run_test_shards.py --shards 6 --log-dir $L
             ${VERIFY495_SUITE_ARGS:+--} ${(s: :)${VERIFY495_SUITE_ARGS:-}})
  rm -rf $L; mkdir -p $L
  print "== start $(date +%T) commit $(git -C $src rev-parse HEAD); $(load)"
  (cd $src && $cmd) > $OUT/SUITE-suite.txt 2>&1
  rc=$?
  fi
  print "== shards exit $rc at $(date +%T); output $OUT/SUITE-suite.txt, shard logs $L/"
  tail -n 4 $OUT/SUITE-suite.txt
  touch $L/failures.txt
  print "== failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  local abnormal=$(grep -c "ABNORMAL" $OUT/SUITE-suite.txt)
  (( abnormal )) && { print "== ABNORMAL lines in the shard output:"; grep "ABNORMAL" $OUT/SUITE-suite.txt; }
  if [[ ! -s $L/failures.txt ]]; then
    if [[ $rc == 0 ]]; then print "PASS SUITE no failures"
    else print "FAIL SUITE shards exit $rc with no failing id (ABNORMAL above or a stopped run)"; fi
  else
    say "dev comparison: the failing ids' files once on dev $DEV, same TMPDIR $TMPB; limit 600 s (stops the run's process group)"
    ensure dev $DEV || return 1
    (cd $BASE/dev/src && clean $BASE/dev/venv/bin/python -I $V487/devcheck.py $L/failures.txt 600)
    local dc=$?
    if [[ $dc == 0 && $abnormal == 0 ]]; then print "PASS SUITE no NEW failures (every failing id fails on dev too)"
    else print "FAIL SUITE: NEW or unclassified failures (above) or ABNORMAL shard output ($abnormal)"; fi
  fi
  next "report $OUT/P.txt, R1.txt, SUITE.txt to the 495 Leader"
}

case $STEP in
  P|R1|SUITE) step_$STEP ;;
  *) print "usage: zsh $THIS <P|R1|SUITE>   e.g. zsh $THIS P 2>&1 | tee $OUT/P.txt" ;;
esac
exit $?
