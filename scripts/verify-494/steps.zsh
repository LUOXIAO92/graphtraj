#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 494: the Claude host's wait/queue double delivery and the member-hold join race, under 491's
# loaded repetition, and the full suite compared with dev.
#   zsh <this file> <P|R1|SUITE>      (in this order, one at a time; from the Harness root or this Worktree)
# Dialog: none in every step (no model, no native host, no Claude Code). Run on a quiet host, not alongside
# another Task's suite.
# P:  preflight: TMPDIR outside the Harness, versions, CPU count, load; builds the candidate clone (tmp/494/R1).
#     ~2 min.
# R1: the candidate (this checkout's HEAD, or VERIFY494_CANDIDATE) with 491's method: 6 repeat workers running
#     the target set (one pytest per pass) up to VERIFY494_PASSES (default 30) times each, plus VERIFY494_SPIN
#     (default: the CPU count, 8 on this host) CPU-spinning processes; loadavg logged every 15 s. A pass takes
#     ~11 s on a quiet host (rehearsal), so the limit is 900 s (+20 s stop; unfinished passes are not counted;
#     counts.txt shows how many ran). Counts double deliveries and `cannot join thread` failures separately
#     (classify.py). PASS only when both are 0 and nothing else failed. <= 18 min.
# SUITE: candidate full suite, 6 shards (scripts/run_test_shards.py) from a git clone; failing ids once on
#     dev ad1ccabc (tmp/494/R0, built only then). Limits 1500 s + 600 s: plan 35 min.
# Each step: a fresh git clone of the exact commit under Harness tmp/494, its own test venv (dependencies linked
# read-only from production .venv-runtime, as verify-491), pytest temp in ${TMPDIR:-/tmp} (refused if inside
# the Harness). Reuses verify-487's repeat.py/devcheck.py and verify-491's load.py unchanged.
set -u
setopt no_bg_nice   # the background load runs at normal priority
H=${VERIFY494_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
V487=${SD:h}/verify-487
V491=${SD:h}/verify-491
BASE=${VERIFY494_BASE:-$H/tmp/494}
OUT=${VERIFY494_OUT:-$H/.graphtraj/core/state/tasks/494-wait-result-and-push-double-delivery/realhost}
DEV=ad1ccabc
CAND=${VERIFY494_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=${VERIFY494_RT:-$H/.venv-runtime}
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
STEP=${1:-help}
TARGETS=(
  tests/test_dsh_standalone_child.py::test_claude_host_routes_a_dsh_child_with_its_own_choices
  tests/test_dsh_standalone_child.py::test_dsh_child_runs_with_graphtraj_unimportable
  tests/test_dsh_standalone_child.py::test_a_wait_while_the_host_queues_the_end_is_its_only_delivery
  tests/test_wait_handover_477.py::test_wait_and_push_racing_deliver_the_reply_exactly_once
  tests/test_wait_handover_477.py::test_a_turn_end_join_racing_a_hold_being_started_never_fails
)
[[ -n ${VERIFY494_TESTS:-} ]] && TARGETS=(${(s:,:)VERIFY494_TESTS})   # rehearsal only
mkdir -p $OUT $BASE
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
TMPB=${TMPDIR:-/tmp}
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8} "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
load() { print -r -- "$(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null || uptime)"; }
cpus() { sysctl -n hw.ncpu 2>/dev/null || print 8; }

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

# Reuse tmp/494/<name> when its clone is at <commit> and its venv exists; else build it.
ensure() {
  local name=$1 commit=$2 D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
}

step_P() {
  say "[P] preflight: TMPDIR, versions, CPUs, load; builds candidate $CAND (tmp/494/R1). Dialog: none. No model, no host. ~2 min."
  check_tmp || return 1
  print "zsh $ZSH_VERSION | git $(git --version | cut -d' ' -f3) | runtime python $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0])') | conda $($CONDA -I -c 'import sys, yaml; print(sys.version.split()[0], "yaml", yaml.__version__)')"
  print "CPUs: $(cpus) | $(load)"
  print "dev $DEV = $(git -C $SRC rev-parse $DEV) | candidate $CAND | candidate changes vs dev:"
  git -C $SRC diff --stat $DEV $CAND -- tests src scripts | tail -n 8
  ensure R1 $CAND || return 1
  print "PASS P (candidate clone and venv ready under $BASE/R1)"
  next "VERIFY494_CANDIDATE=$CAND zsh $THIS R1 2>&1 | tee $OUT/R1.txt"
}

step_R1() {
  local limit=${VERIFY494_LIMIT:-900} spin=${VERIFY494_SPIN:-$(cpus)} res=$OUT/R1-repeat
  say "[R1] ${#TARGETS} targets x${VERIFY494_PASSES:-30} passes on each of ${VERIFY494_WORKERS:-6} workers, plus $spin CPU spinners, on $CAND. Dialog: none. Limit $limit s (+20 s stop)."
  print -l -- "  "$^TARGETS
  check_tmp || return 1
  ensure R1 $CAND || return 1
  rm -rf $res; mkdir -p $res
  print "CPUs: $(cpus) | start $(load)" | tee $res/loadavg.txt
  # Background load (verify-491 load.py): spinners and a loadavg log, bounded by the limit + 30 s, stopped
  # right after the run. env execs Python, so $! is load.py itself; its output never reaches this step's pipe.
  env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=$TMPB $BASE/R1/venv/bin/python -I $V491/load.py $spin $(( limit + 30 )) $res/loadavg.txt \
    < /dev/null > /dev/null 2>&1 &
  local loader=$!
  print "== start $(date +%T)"
  (cd $BASE/R1/src && clean $BASE/R1/venv/bin/python -I $V487/repeat.py $BASE/R1/src $res \
     --tests ${(j:,:)TARGETS} --workers ${VERIFY494_WORKERS:-6} --fast ${VERIFY494_PASSES:-30} --limit $limit)
  kill -TERM $loader 2>/dev/null; wait $loader 2>/dev/null
  print "end $(load)" >> $res/loadavg.txt
  print "== end $(date +%T); loadavg (start, every 15 s, end) $res/loadavg.txt:"
  cat $res/loadavg.txt
  print "counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
  say "classification (double deliveries, cannot join thread, others)"
  $CONDA -I $SD/classify.py $res
  if (( $? == 0 )); then print "PASS R1 (0 double deliveries, 0 cannot join thread, no other failure)"
  else print "FAIL R1 (counts above; raw texts in $res/failures/)"; fi
  next "VERIFY494_CANDIDATE=$CAND zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), then its failing ids once on dev $DEV. Dialog: none. Limits: suite 1500 s, dev recheck 600 s."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc
  if [[ -n ${VERIFY494_FAILURES:-} ]]; then
    # Rehearsal of the dev comparison only (Main never sets it): no suite, the given failures file.
    print "REHEARSAL: suite not run; failures from $VERIFY494_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY494_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
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
    sys.exit(124)' ${VERIFY494_SUITE_LIMIT:-1500} $VT/bin/python $src/scripts/run_test_shards.py --shards 6 --log-dir $L
             ${VERIFY494_SUITE_ARGS:+--} ${(s: :)${VERIFY494_SUITE_ARGS:-}})
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
    say "dev comparison: the failing ids' files once on dev $DEV (tmp/494/R0), same TMPDIR $TMPB; limit 600 s (stops the run's process group)"
    ensure R0 $DEV || return 1
    (cd $BASE/R0/src && clean $BASE/R0/venv/bin/python -I $V487/devcheck.py $L/failures.txt 600)
    local dc=$?
    if [[ $dc == 0 && $abnormal == 0 ]]; then print "PASS SUITE no NEW failures (every failing id fails on dev too)"
    else print "FAIL SUITE: NEW or unclassified failures (above) or ABNORMAL shard output ($abnormal)"; fi
  fi
  next "report $OUT/P.txt, R1.txt, SUITE.txt to the 494 Leader"
}

case $STEP in
  P|R1|SUITE) step_$STEP ;;
  *) print "usage: zsh $THIS <P|R1|SUITE>   e.g. zsh $THIS P 2>&1 | tee $OUT/P.txt" ;;
esac
exit $?
