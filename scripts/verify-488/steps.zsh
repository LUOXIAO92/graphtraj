#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 488: pre-Runtime stop with exiting/zombie current-user processes, before (dev) and after (candidate).
#   zsh <this file> <00|R1|SUITE> (R0 optional)  (from any directory; Harness root or this Worktree), one at a time.
# 00: preflight and the host's current-user process-identity probe; R1: the candidate (this checkout's HEAD, or
# VERIFY488_CANDIDATE) against 487's dev R0 baseline (reused: the stop's code and test are unchanged from 5a451267
# to dev 1524730b, checked live by R1); R0 (optional): a fresh dev 1524730b baseline; SUITE: candidate full
# suite, failing files rechecked on dev.
# R0/R1/SUITE: a fresh git clone of the exact commit under Harness tmp/488, its own test venv (dependencies
# linked read-only from production .venv-runtime into the venv's own site-packages, as verify-482/487),
# pytest temp in ${TMPDIR:-/tmp} (refused if inside the Harness). Dialog: none in every step (no model, no
# native host). Not alongside another Task's suite.
# R0/R1: 487's repetition method unchanged (scripts/verify-487 sets and load): 6 workers x (core set x6 = 36 runs
# each, slow x2, observe-only files x1), limit 900 s (+20 s stop), about 15 min with the build. R1's verdict is on
# test_native_interrupt_confirms_only_pre_runtime_allocations; the other tests are listed for information.
# Rehearsal only (Main never sets them): VERIFY488_COUNTS=<counts.txt> (R1 verdict without a run),
# VERIFY488_FAILURES=<failures.txt> (SUITE dev comparison without the suite).
set -u
H=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
BASE=${VERIFY488_BASE:-$H/tmp/488}
OUT=${VERIFY488_OUT:-$H/.graphtraj/core/state/tasks/488-pre-runtime-stop-process-identity/realhost}
DEV=1524730b
CAND=${VERIFY488_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=$H/.venv-runtime
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
STEP=${1:-help}
NATIVE=tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations
R487=$H/.graphtraj/core/state/tasks/487-suite-intermittent-failures/realhost/R0-repeat/counts.txt
BASEDEV=5a451267  # 487 R0's dev
STOPFILES=(src/graphtraj/execution/runner_process.py src/graftling/process.py src/graphtraj/execution/runner_control.py tests/test_agent_runner_cleanup.py)
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

step_00() {
  say "[00] preflight: commits, pytest temp, .venv-runtime python, and the host's current-user process-identity probe on candidate code. Dialog: none. Limit 60 s."
  print "No model or native host is used in Task 488: no model-answer or isolated-project check is needed."
  print "dev:       $DEV = $(git -C $SRC rev-parse $DEV 2>&1)"
  print "candidate: $CAND ($(git -C $SRC log -1 --format=%s $CAND 2>&1 | cut -c1-90))"
  check_tmp || return 1
  [[ -x $RT/bin/python ]] || { print "STOP: $RT/bin/python is missing"; return 1; }
  print ".venv-runtime python: $RT/bin/python -> $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0], sys.executable)')"
  # The candidate's source tree, exported read-only to tmp/488/00-src (not the installed runtime package).
  local P=$BASE/00-src
  rm -rf $P && mkdir -p $P && git -C $SRC archive $CAND src | tar -x -C $P || { print "STOP: export of $CAND failed"; return 1; }
  clean $RT/bin/python -I -c '
import ctypes, os, sys
sys.path.insert(0, sys.argv[1])
from graphtraj.execution import runner_process as rp
print("probe module:", rp.__file__)
if not hasattr(rp, "_short_bsd_info"):
    print("STOP: this source has no 488 classifier (is the candidate right?)"); sys.exit(1)
if sys.platform != "darwin":
    print("non-Darwin host: the Darwin identity probe does not apply"); sys.exit(1)
library = rp._libproc()
size = library.proc_listpids(4, os.getuid(), None, 0)
pids = (ctypes.c_int * (size // 4 + 128))()
written = library.proc_listpids(4, os.getuid(), pids, ctypes.sizeof(pids))
live = ended = unreadable = 0
for pid in pids[:max(written, 0) // 4]:
    info = rp._short_bsd_info(pid)
    if info is None:
        unreadable += 1
    elif rp._has_ended(info):
        ended += 1
    else:
        live += 1
print(f"current-user pids: {written // 4}; live {live}; left out as ended (zombie or exiting) {ended}; unreadable {unreadable}")
try:
    rows = rp._current_user_processes()
except OSError as error:
    print(f"_current_user_processes RAISES: {error!r}")
    print("FAIL 00: the cleanup precheck would skip [absent]/[waiting] on this host (process identity is denied)")
    sys.exit(1)
print(f"_current_user_processes returns {len(rows)} identities without raising")
print("PASS 00: the precheck (tests/test_agent_runner_cleanup.py::_process_identity_unavailable) will not skip")
' $P/src || { next "report $OUT/00.txt to the 488 Leader before R1 (R1 would skip or cannot run)"; return 1; }
  next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"
}

run_repeat() {
  local name=$1 commit=$2
  say "[$name] 487's intermittent sets repeated under 6 parallel workers (core x6 = 36 runs each, slow x2, observe x1) on $commit. Dialog: none. Limit 900 s (+20 s stop); about 15 min with the build."
  check_tmp || return 1
  build $commit $BASE/$name || return 1
  local res=$OUT/$name-repeat
  rm -rf $res; mkdir -p $res
  print "== start $(date +%T)"
  (cd $BASE/$name/src && clean $BASE/$name/venv/bin/python -I $SD/repeat.py $BASE/$name/src $res \
     --workers 6 --fast 6 --slow 2 --observe 1 --limit 900)
  print "== end $(date +%T); counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
}

# verdict <counts.txt> <name>: PASS only when [absent]/[waiting] ran 36 times each with none failed or skipped,
# and [foreign-group]/[runtime-artifact] (identity mismatch still refused under load) have none failed.
# Every other test is listed for information only.
verdict() {
  $RT/bin/python -I -c '
import sys
native, name = sys.argv[2], sys.argv[3]
rows, limited = {}, False
for line in open(sys.argv[1]):
    parts = line.split()
    limited |= "(limit reached)" in line
    if len(parts) == 4 and parts[0].isdigit():
        rows[parts[3]] = tuple(map(int, parts[:3]))
bad = 0
for case in ("absent", "waiting", "foreign-group", "runtime-artifact"):
    row = rows.get(f"{native}[{case}]")
    if row is None:
        print(f"VERDICT [{case}]: no results"); bad += 1; continue
    failed, passed, skipped = row
    strict = case in ("absent", "waiting")
    ok = failed == 0 and (not strict or (skipped == 0 and passed >= 36))
    bad += not ok
    word = ("ok" if ok else "NOT ok" if failed or skipped else "NOT ok (fewer than 36 runs)")
    rule = "36 runs, 0 failed, 0 skipped" if strict else "0 failed"
    print(f"VERDICT [{case}] ({rule}): {failed} failed, {passed} passed, {skipped} skipped of {sum(row)} -> {word}")
others = [(node, row) for node, row in sorted(rows.items()) if not node.startswith(native + "[")]
noted = [(node, row) for node, row in others if row[0] or row[2]]
print(f"information only, not in the verdict: {len(others)} other tests, {len(others) - len(noted)} with no failure or skip; with one:")
for node, (failed, passed, skipped) in noted:
    print(f"  {failed:>3} failed {passed:>3} passed {skipped:>3} skipped  {node}")
if limited:
    print("NOTE: the run limit was reached; only completed passes are counted")
print(f"PASS {name}: [absent]/[waiting] 36 runs each, 0 failed, 0 skipped; [foreign-group]/[runtime-artifact] 0 failed" if not bad
      else f"FAIL {name}: {bad} native param(s) failed the rule above or are missing")
sys.exit(1 if bad else 0)
' $1 $NATIVE $2
}

step_R0() {
  say "R0 is optional: a fresh dev baseline; not needed when R1 prints SAME (R1 reuses 487's R0)."
  run_repeat R0 $DEV || return 1
  say "R0 (dev $DEV) verdict shape for the record (expected to fail or skip)"
  verdict $OUT/R0-repeat/counts.txt R0
  next "zsh $THIS R1 2>&1 | tee $OUT/R1.txt"
}

step_R1() {
  local counts
  say "dev baseline: 487's R0 (dev $BASEDEV) is reused when the stop's code and test are unchanged to dev $DEV"
  if git -C $SRC diff --quiet $BASEDEV $DEV -- $STOPFILES; then
    print "SAME: git diff $BASEDEV $DEV -- ${STOPFILES[*]} is empty"
  else
    print "DIFFERENT: git diff $BASEDEV $DEV -- ${STOPFILES[*]} is not empty; 487's R0 is not this dev's baseline (run the optional R0)"
  fi
  if [[ -n ${VERIFY488_COUNTS:-} ]]; then
    print "REHEARSAL: repetition not run; counts from $VERIFY488_COUNTS"; counts=$VERIFY488_COUNTS
  else
    run_repeat R1 $CAND || return 1; counts=$OUT/R1-repeat/counts.txt
  fi
  say "native params: 487 R0 (dev $BASEDEV, $R487) | R1 (candidate $CAND)"
  local case
  for case in absent waiting foreign-group runtime-artifact; do
    print -r -- "[$case]"
    print -r -- "  487 R0: $(grep -F -- "${NATIVE}[$case]" $R487 2>/dev/null || print 'missing')"
    print -r -- "  R1:     $(grep -F -- "${NATIVE}[$case]" $counts 2>/dev/null || print 'missing')"
  done
  [[ -f $OUT/R0-repeat/counts.txt ]] && { say "optional R0 (dev $DEV) counts"; cat $OUT/R0-repeat/counts.txt; }
  say "R1 verdict (all counts: $counts)"
  verdict $counts R1
  next "zsh $THIS SUITE 2>&1 | tee $OUT/SUITE.txt"
}

step_SUITE() {
  say "[SUITE] full suite of candidate $CAND from a fresh clone, 6 shards (scripts/run_test_shards.py), then its failing files once on dev $DEV. Dialog: none. Limits: suite 1500 s, dev recheck 600 s (+ dev build if R0's clone is missing): plan 35 min."
  check_tmp || return 1
  local L=$OUT/SUITE-shards rc
  if [[ -n ${VERIFY488_FAILURES:-} ]]; then
    # Rehearsal of the dev comparison only (Main never sets it): no suite, the given failures file.
    print "REHEARSAL: suite not run; failures from $VERIFY488_FAILURES"
    rm -rf $L; mkdir -p $L; cp $VERIFY488_FAILURES $L/failures.txt; rc=1; : > $OUT/SUITE-suite.txt
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
  next "report $OUT/00.txt, R1.txt, SUITE.txt (and R0.txt if the optional R0 ran) to the 488 Leader"
}

case $STEP in
  00|R0|R1|SUITE) step_$STEP ;;
  *) print "usage: zsh $THIS <00|R1|SUITE>   one at a time, in this order. Dialog: none in every step."
     print "  00 preflight + host process-identity probe (60 s); R1 candidate repetition + verdict (900 s + build, about 15 min);"
     print "  SUITE full suite + dev recheck (about 35 min). R0 (optional, about 15 min): a fresh dev baseline;"
     print "  not needed when R1 prints SAME (487's R0 is reused)."
     next "zsh $THIS 00 2>&1 | tee $OUT/00.txt" ;;
esac
