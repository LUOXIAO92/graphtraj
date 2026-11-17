#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 487: failure rates of the suite's intermittent tests, before (dev) and after (candidate), and the full suite.
#   zsh <this file> <R0|R1|SUITE|R463>      (from any directory; Harness root or this Worktree)
# R0: dev 5a451267; R1: the candidate commit (this checkout's HEAD, or VERIFY487_CANDIDATE); SUITE: candidate full suite.
# Each step: a fresh git clone of the exact commit under Harness tmp/487, its own test venv (dependencies linked
# read-only from production .venv-runtime into the venv's own site-packages, as verify-482/484), pytest temp in
# ${TMPDIR:-/tmp} (refused if inside the Harness). Dialog: none (no model, no native host). Run one at a time,
# not alongside another Task's suite. Bounded waits: R0/R1 900 s + 20 s stop (about 15 min with setup);
# R463: tests/test_dsh_tool_reclaim_463.py on dev and candidate at once, 3 workers x10 each, 300 s (+20 s) + builds if missing.
# SUITE 1500 s + a 600 s rerun of its failing files on dev (+ a dev build if R0's clone is missing): plan 35 min.
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
  clean $venv/bin/python -I -c 'import os, sys, graphtraj, graftling
ok = all(os.path.realpath(m.__file__).startswith(os.path.realpath(sys.argv[1])) for m in (graphtraj, graftling))
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

step_R0() { run_repeat R0 $DEV || return 1; next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"; }
step_R1() {
  run_repeat R1 $CAND || return 1
  [[ -f $OUT/R0-repeat/counts.txt ]] && { say "R0 (dev $DEV) counts for comparison"; cat $OUT/R0-repeat/counts.txt; }
  next "zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), then its failing files once on dev $DEV. Dialog: none. Limits: suite 1500 s, dev recheck 600 s (+ dev build if R0's clone is missing)."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc
  if [[ -n ${VERIFY487_FAILURES:-} ]]; then
    # Rehearsal of the dev comparison only (Main never sets it): no suite, the given failures file.
    print "REHEARSAL: suite not run; failures from $VERIFY487_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY487_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
  else
  build $CAND $BASE/suite || return 1
  local src=$BASE/suite/src VT=$BASE/suite/venv
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
    local D=$BASE/R0
    if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $DEV) && -x $D/venv/bin/python ]]; then
      print "dev clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
    else build $DEV $D || return 1; fi
    (cd $D/src && clean $D/venv/bin/python -I $SD/devcheck.py $L/failures.txt 600)
    local dc=$?
    if [[ $dc == 0 && $abnormal == 0 ]]; then print "PASS SUITE no NEW failures (every failing id fails on dev too)"
    else print "FAIL SUITE: NEW or unclassified failures (above) or ABNORMAL shard output ($abnormal)"; fi
  fi
  next "report $OUT/R0.txt, R1.txt, SUITE.txt to the 487 Leader"
}

# Reuse tmp/487/<name> when its clone is at <commit> and its venv exists; else build it.
ensure() {
  local name=$1 commit=$2 D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
}

step_R463() {
  # The candidate is the commit SUITE ran on (its R1 clone is reused); src/ and tests/ are unchanged after it.
  local T=tests/test_dsh_tool_reclaim_463.py CAND=${VERIFY487_CANDIDATE:-3d748267ca71d6d1242450c58eeb56b61bc2edc3}
  say "[R463] $T on dev $DEV and candidate $CAND at the same time (3 workers each, x${VERIFY487_R463_PASSES:-10} passes per worker). Dialog: none. Limit 300 s (+20 s stop) per side."
  check_tmp || return 1
  ensure R0 $DEV || return 1
  ensure R1 $CAND || return 1
  local side
  for side in dev cand; do rm -rf $OUT/R463-$side; mkdir -p $OUT/R463-$side; done
  print "== start $(date +%T)"
  (cd $BASE/R0/src && clean $BASE/R0/venv/bin/python -I $SD/repeat.py $BASE/R0/src $OUT/R463-dev \
     --tests $T --workers 3 --fast ${VERIFY487_R463_PASSES:-10} --limit 300 > $OUT/R463-dev/run.txt 2>&1) &
  local dev_pid=$!
  (cd $BASE/R1/src && clean $BASE/R1/venv/bin/python -I $SD/repeat.py $BASE/R1/src $OUT/R463-cand \
     --tests $T --workers 3 --fast ${VERIFY487_R463_PASSES:-10} --limit 300 > $OUT/R463-cand/run.txt 2>&1) &
  local cand_pid=$!
  wait $dev_pid $cand_pid
  print "== end $(date +%T); logs $OUT/R463-dev/run.txt, $OUT/R463-cand/run.txt"
  grep -h "limit reached" $OUT/R463-dev/run.txt $OUT/R463-cand/run.txt
  say "counts: dev $DEV (left) | candidate $CAND (right)"
  touch $OUT/R463-dev/counts.txt $OUT/R463-cand/counts.txt
  paste -d '|' $OUT/R463-dev/counts.txt $OUT/R463-cand/counts.txt | awk -F'|' '{printf "%-110s | %s\n", $1, $2}'
  clean $BASE/R0/venv/bin/python -I -c '
import sys
def rows(path):
    out = {}
    for line in open(path):
        parts = line.split()
        if len(parts) == 4 and parts[0].isdigit():
            out[parts[3]] = (int(parts[0]), int(parts[1]), int(parts[2]))
    return out
dev, cand = rows(sys.argv[1]), rows(sys.argv[2])
worse = 0
for node in sorted(set(dev) | set(cand)):
    d, c = dev.get(node), cand.get(node)
    if d is None or c is None:
        side = "dev" if c is None else "candidate"
        print(f"VERDICT {node}: only on {side}"); worse += c is not None and c[0] > 0; continue
    word = "candidate MORE failures" if c[0] > d[0] else "candidate fewer failures" if c[0] < d[0] else "same failures"
    worse += c[0] > d[0]
    print(f"VERDICT {node}: dev {d[0]}/{sum(d)} failed, candidate {c[0]}/{sum(c)} failed -> {word}")
print("PASS R463 the candidate fails no test more often than dev" if dev and cand and not worse
      else "CHECK R463 (no results on a side)" if not (dev and cand) else f"FAIL R463 {worse} test(s) fail more often on the candidate")
' $OUT/R463-dev/counts.txt $OUT/R463-cand/counts.txt
  print "raw failures: $OUT/R463-dev/failures/, $OUT/R463-cand/failures/"
  next "report $OUT/R463.txt to the 487 Leader"
}

dispatch() {
case $STEP in
  R0) step_R0 ;;
  R1|SUITE|R463) step_$STEP ;;
  *) print "usage: zsh $THIS <R0|R1|SUITE|R463>   e.g. zsh $THIS R0 2>&1 | tee $OUT/R0.txt" ;;
esac
}
dispatch; exit $?
