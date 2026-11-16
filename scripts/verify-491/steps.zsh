#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 491: failure rates of 463 / hook_diagnostics / 459-redaction and the item-1 answered() tests under suite-like
# parallel load (dev, then candidate), the full suite, and an offline replay of the fixed adopt-492 nr492.py.
#   zsh <this file> <P|NR|R0|R1|SUITE>      (in this order; from any directory: Harness root or this Worktree)
# Dialog: none in every step (no model, no native host, no Claude Code). Run one at a time on a quiet host,
# not alongside another Task's suite.
# P:  preflight: TMPDIR outside the Harness, versions, CPU count, load; builds the dev and candidate clones. ~3 min.
# R0: dev; R1: the candidate (this checkout's HEAD, or VERIFY491_CANDIDATE). Each: 6 repeat workers (the suite's
#     6 shards) running the target set (one pytest per pass, ~8.4 s per pass on a quiet host) up to
#     VERIFY491_PASSES (default 30) times each, plus VERIFY491_SPIN (default: the CPU count) CPU-spinning
#     processes as background load, aiming at 492's suite load (1-min loadavg ~21-37); loadavg logged every 15 s.
#     Limit 780 s (+20 s stop; passes unfinished at the limit are not counted): <= 15 min with the build.
# SUITE: candidate full suite, 6 shards (scripts/run_test_shards.py) from a git clone, failing files once on dev.
#     Limits 1500 s + 600 s (as verify-487): plan 35 min.
# NR: nr492.py (this commit) replayed read-only on 492's raw-9faa0274 and production records; ~1 min.
# Each step: a fresh git clone of the exact commit under Harness tmp/491, its own test venv (dependencies linked
# read-only from production .venv-runtime into the venv's own site-packages, as verify-487), pytest temp in
# ${TMPDIR:-/tmp} (refused if inside the Harness).
set -u
setopt no_bg_nice   # the background load runs at normal priority
H=${VERIFY491_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
V487=${SD:h}/verify-487
BASE=${VERIFY491_BASE:-$H/tmp/491}
OUT=${VERIFY491_OUT:-$H/.graphtraj/core/state/tasks/491-test-stability-follow-up/realhost}
DEV=1524730b
CAND=${VERIFY491_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=${VERIFY491_RT:-$H/.venv-runtime}
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
STEP=${1:-help}
TARGETS=(
  tests/test_dsh_tool_reclaim_463.py
  tests/test_parent_host_status.py::test_hook_diagnostics_preserve_native_events_and_do_not_answer_approvals
  tests/test_tool_descendants_459.py::test_recorded_and_reported_command_lines_are_redacted
  tests/test_claude_host_cross_runtime.py::test_claude_host_runs_a_codex_child_like_a_claude_child
  tests/test_dsh_standalone_child.py::test_dsh_child_runs_with_graphtraj_unimportable
  tests/test_dsh_standalone_child.py::test_claude_host_routes_a_dsh_child_with_its_own_choices
)
[[ -n ${VERIFY491_TESTS:-} ]] && TARGETS=(${(s:,:)VERIFY491_TESTS})   # rehearsal only
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

# build <commit> <dir>: clone the exact commit to <dir>/src and make <dir>/venv importing it (verify-487 build).
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

# Reuse tmp/491/<name> when its clone is at <commit> and its venv exists; else build it.
ensure() {
  local name=$1 commit=$2 D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
}

step_P() {
  say "[P] preflight: TMPDIR, versions, CPUs, load; builds dev $DEV (tmp/491/R0) and candidate $CAND (tmp/491/R1). Dialog: none. No model, no host. ~3 min."
  check_tmp || return 1
  print "zsh $ZSH_VERSION | git $(git --version | cut -d' ' -f3) | runtime python $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0])') | conda $($CONDA -I -c 'import sys, yaml; print(sys.version.split()[0], "yaml", yaml.__version__)')"
  print "CPUs: $(sysctl -n hw.ncpu 2>/dev/null || print unknown) | $(load)"
  print "dev $DEV = $(git -C $SRC rev-parse $DEV) | candidate $CAND | candidate tests changed vs dev:"
  git -C $SRC diff --stat $DEV $CAND -- tests src | tail -n 5
  ensure R0 $DEV || return 1
  ensure R1 $CAND || return 1
  print "PASS P (clones and venvs ready under $BASE)"
  next "zsh $THIS NR 2>&1 | tee $OUT/NR.txt"
}

# run_repeat <name> <commit>: the target set under 6 workers plus a spinning background load.
run_repeat() {
  local name=$1 commit=$2 limit=${VERIFY491_LIMIT:-780} spin=${VERIFY491_SPIN:-$(sysctl -n hw.ncpu 2>/dev/null || print 8)}
  say "[$name] ${#TARGETS} targets x${VERIFY491_PASSES:-30} passes on each of ${VERIFY491_WORKERS:-6} workers, plus $spin CPU spinners, on $commit. Dialog: none. Limit $limit s (+20 s stop)."
  print -l -- "  "$^TARGETS
  check_tmp || return 1
  ensure $name $commit || return 1
  local res=$OUT/$name-repeat
  rm -rf $res; mkdir -p $res
  print "CPUs: $(sysctl -n hw.ncpu 2>/dev/null || print unknown) | start $(load)" | tee $res/loadavg.txt
  # Background load (load.py): spinners and a loadavg log, bounded by the limit + 30 s, stopped right after the run.
  # env execs Python, so $! is load.py itself; its output never reaches this step's pipe.
  env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=$TMPB $BASE/$name/venv/bin/python -I $SD/load.py $spin $(( limit + 30 )) $res/loadavg.txt \
    < /dev/null > /dev/null 2>&1 &
  local loader=$!
  print "== start $(date +%T)"
  (cd $BASE/$name/src && clean $BASE/$name/venv/bin/python -I $V487/repeat.py $BASE/$name/src $res \
     --tests ${(j:,:)TARGETS} --workers ${VERIFY491_WORKERS:-6} --fast ${VERIFY491_PASSES:-30} --limit $limit)
  kill -TERM $loader 2>/dev/null; wait $loader 2>/dev/null
  print "end $(load)" >> $res/loadavg.txt
  print "== end $(date +%T); loadavg (start, every 15 s, end) $res/loadavg.txt:"
  cat $res/loadavg.txt
  print "counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
}

step_R0() { run_repeat R0 $DEV || return 1; next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"; }
step_R1() {
  run_repeat R1 $CAND || return 1
  [[ -f $OUT/R0-repeat/counts.txt ]] && { say "R0 (dev $DEV) counts for comparison"; cat $OUT/R0-repeat/counts.txt; }
  next "zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), then its failing files once on dev $DEV. Dialog: none. Limits: suite 1500 s, dev recheck 600 s."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc
  if [[ -n ${VERIFY491_FAILURES:-} ]]; then
    # Rehearsal of the dev comparison only (Main never sets it): no suite, the given failures file.
    print "REHEARSAL: suite not run; failures from $VERIFY491_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY491_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
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
    sys.exit(124)' ${VERIFY491_SUITE_LIMIT:-1500} $VT/bin/python $src/scripts/run_test_shards.py --shards 6 --log-dir $L
             ${VERIFY491_SUITE_ARGS:+--} ${(s: :)${VERIFY491_SUITE_ARGS:-}})
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
    ensure R0 $DEV || return 1
    (cd $BASE/R0/src && clean $BASE/R0/venv/bin/python -I $V487/devcheck.py $L/failures.txt 600)
    local dc=$?
    if [[ $dc == 0 && $abnormal == 0 ]]; then print "PASS SUITE no NEW failures (every failing id fails on dev too)"
    else print "FAIL SUITE: NEW or unclassified failures (above) or ABNORMAL shard output ($abnormal)"; fi
  fi
  next "report $OUT/P.txt, NR.txt, R0.txt, R1.txt, SUITE.txt to the 491 Leader"
}

step_NR() {
  # Read only: nr492.py opens files and never writes, signals or starts a process.
  local raw=${VERIFY491_NR_RAW:-$H/.graphtraj/core/state/tasks/492-production-adoption-480-487/adoption/raw-9faa0274}
  local task=${VERIFY491_NR_TASK:-492-production-adoption-480-487} nr=$SD:h/adopt-492/nr492.py
  local member=$(sed -n 's/^MEMBER //p' $raw/Nr.txt | tail -1) child=$(cat $raw/N-child-name)
  say "[NR] nr492.py of $(git -C $SRC rev-parse --short HEAD) ($nr) replayed read-only on $raw (child $child, member ${member:-none}). Dialog: none. ~1 min."
  rm -rf $OUT/NR; mkdir -p $OUT/NR
  $CONDA -I $nr $H $raw $child "${member:-none}" $task > $OUT/NR/replay.txt 2>&1
  print "nr492.py exit $? (output $OUT/NR/replay.txt)"
  grep -E '^487:|^CHECK 487' $OUT/NR/replay.txt
  $CONDA -I $SD/nrdiff.py $raw/Nr.txt $OUT/NR/replay.txt
  local rc=$?
  next "zsh $THIS R0 2>&1 | tee $OUT/R0.txt"
  return $rc
}

case $STEP in
  P|R0|R1|SUITE|NR) step_$STEP ;;
  *) print "usage: zsh $THIS <P|R0|R1|SUITE|NR>   e.g. zsh $THIS P 2>&1 | tee $OUT/P.txt" ;;
esac
exit $?
