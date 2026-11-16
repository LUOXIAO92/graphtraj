#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 496: the 459, 495 and 496 test files under 491/495's parallel-load method on dev and on the candidate, then the
# candidate's full suite (background, after a quiet-host wait) with a dev comparison.
#   zsh <this file> <P|R0|R1|S|SR|CHECK>      (in this order, one at a time; from any directory; no tee needed)
# Each step writes its own output to $OUT/<STEP>.txt (the script creates $OUT) as well as to the terminal.
# Dialog: none in every step (no model, no native host, no Claude Code).
# P:     preflight: pytest temp outside the Harness, versions, CPU count, load, running suites (argv tokens); builds the
#        dev ee812afa clone (tmp/496/dev) and the candidate clone (tmp/496/R1). ~3 min.
# R0:    dev clone: 459 + 495 files, 6 repeat workers (verify-487/repeat.py) x VERIFY496_PASSES (default 30) plus
#        VERIFY496_SPIN (default the CPU count) spinners (verify-491/load.py). Prints dev's owner_killed rate. <= 14 min.
# R1:    candidate clone: the same plus tests/test_tool_descendants_496.py. PASS only on 0 failures (and > 0 passes) of
#        every test in the three files. <= 14 min.
# S:     candidate full suite from a fresh git checkout, 6 shards, in a background job that first waits for a quiet
#        host (adopt-497 S method: no running suite by argv tokens, 1-minute load <= half the CPU count), then the
#        failing files once on dev (verify-487/devcheck.py). Foreground ~2 min; background quiet wait <= 20 min, suite
#        ~25 min, dev recheck <= 10 min.
# SR:    reads S's background output; prints RUNNING, or the verdict PASS S / FAIL S (no NEW failures vs dev).
# CHECK: S's failing files once on the candidate (quiet host), devcheck.py method. Limit 600 s.
# Every pytest uses TMPDIR=${TMPDIR:-/tmp} (refused if inside the Harness). Leftover processes are never matched by a
# 'pytest' path substring, and no step signals a process it did not start.
set -u
setopt no_bg_nice   # the background load runs at normal priority
H=${VERIFY496_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
V487=${SD:h}/verify-487
V491=${SD:h}/verify-491
BUSY=${SD:h}/adopt-497/busy497.py
BASE=${VERIFY496_BASE:-$H/tmp/496}
OUT=${VERIFY496_OUT:-$H/.graphtraj/core/state/tasks/496-tool-descendant-owner-killed-and-pre-exec-boundary/realhost}
DEV=ee812afa
CAND=${VERIFY496_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=${VERIFY496_RT:-$H/.venv-runtime}
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
STEP=${1:-help}
OWNER=tests/test_tool_descendants_459.py::test_owner_killed_then_reconciliation_stops_the_recorded_shell_and_sleep
DEVFILES=(tests/test_tool_descendants_459.py tests/test_tool_descendant_argv_refresh_495.py)
NEWFILE=tests/test_tool_descendants_496.py
[[ -n ${VERIFY496_TESTS:-} ]] && DEVFILES=(${(s:,:)VERIFY496_TESTS})   # rehearsal only
mkdir -p $OUT $BASE
TMPB=${TMPDIR:-/tmp}
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8} "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
ncpus() { sysctl -n hw.ncpu 2>/dev/null || print 8; }
load() { print -r -- "$(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null || uptime)"; }
load1() { local la=$(sysctl -n vm.loadavg 2>/dev/null); print ${${(s: :)${la//[\{\}]/}}[1]:-0}; }
load_limit() { print ${VERIFY496_LOADMAX:-$(( $(ncpus) / 2 ))}; }

check_tmp() {
  print "pytest temp base TMPDIR=\${TMPDIR:-/tmp} = ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != ${H:A}* ]] && print YES || print NO)"
  [[ ${TMPB:A} != ${H:A}* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}

# Running suites by argv tokens (adopt-497 busy497.py); leftovers under pytest-of-* are only listed.
# $1 = listing file; $2 = own root pid (excluded with its descendants); $3.. = patterns of our own S.
suites() {
  local file=$1; shift
  ps -axww -o pid=,ppid=,etime=,command= > $file 2>&1 || print "(ps failed: $(head -c 120 $file))"
  $(base_python) -I $BUSY $file "$@"
}

# build <commit> <dir>: clone the exact commit to <dir>/src and make <dir>/venv importing it (verify-495 build).
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

# Reuse tmp/496/<name> when its clone is at <commit> and its venv exists; else build it.
ensure() {
  local name=$1 commit=$2 D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
}

step_P() {
  say "[P] preflight; builds dev $DEV ($BASE/dev) and candidate $CAND ($BASE/R1). Expected dialog: none. Duration ~3 min."
  check_tmp || return 1
  print "zsh $ZSH_VERSION | git $(git --version | cut -d' ' -f3) | runtime python $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0])')"
  print "CPUs: $(ncpus) | $(load) | quiet limit for S: 1-minute load <= $(load_limit)"
  print "running suites (argv tokens; leftovers under pytest-of-* only listed, never signalled):"
  suites $OUT/P-ps.txt $$
  print "dev $DEV = $(git -C $SRC rev-parse $DEV) | candidate $CAND | candidate changes vs dev:"
  git -C $SRC diff --stat $DEV $CAND -- src tests scripts | tail -n 6
  ensure dev $DEV || return 1
  ensure R1 $CAND || return 1
  print "PASS P (clones and venvs ready under $BASE)"
  next "zsh $THIS R0"
}

# load_run <clone name> <label> <targets...>: 491/495's parallel-plus-load run; result under $OUT/<label>-repeat.
load_run() {
  local name=$1 label=$2; shift 2
  local targets=($@) limit=${VERIFY496_LIMIT:-780} spin=${VERIFY496_SPIN:-$(ncpus)}
  local workers=${VERIFY496_WORKERS:-6} passes=${VERIFY496_PASSES:-30} res=$OUT/$label-repeat
  print "${#targets} targets x$passes passes on each of $workers workers, plus $spin CPU spinners; limit $limit s (+20 s stop):"
  print -l -- "  "$^targets
  check_tmp || return 1
  local listing=$(suites $OUT/$label-ps.txt $$)
  print -r -- "$listing"
  if [[ $(print -r -- "$listing" | sed -n 's/^running suites: //p') != 0 ]]; then
    print "STOP: another test suite is running (listed above); rerun when it has ended: zsh $THIS $label"; return 1
  fi
  rm -rf $res; mkdir -p $res
  print "CPUs: $(ncpus) | start $(load)" | tee $res/loadavg.txt
  # Background load (verify-491/load.py): its own spinners only, bounded by the limit + 30 s, stopped after the run.
  env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=$TMPB $BASE/$name/venv/bin/python -I $V491/load.py $spin $(( limit + 30 )) $res/loadavg.txt \
    < /dev/null > /dev/null 2>&1 &
  local loader=$!
  print "== start $(date +%T) on $BASE/$name/src at $(git -C $BASE/$name/src rev-parse HEAD)"
  (cd $BASE/$name/src && clean $BASE/$name/venv/bin/python -I $V487/repeat.py $BASE/$name/src $res \
     --tests ${(j:,:)targets} --workers $workers --fast $passes --limit $limit)
  kill -TERM $loader 2>/dev/null; wait $loader 2>/dev/null
  print "end $(load)" >> $res/loadavg.txt
  print "== end $(date +%T); loadavg (start, every 15 s, end):"
  cat $res/loadavg.txt
  print "counts $res/counts.txt; failures $res/failures/; worker logs $res/worker-*.log"
}

step_R0() {
  say "[R0] dev $DEV: 459 + 495 files under the parallel-load method, to quantify dev's owner_killed rate. Expected dialog: none. Duration <= 14 min."
  ensure dev $DEV || return 1
  load_run dev R0 $DEVFILES || return 1
  local row=$(grep -F -- "$OWNER" $OUT/R0-repeat/counts.txt 2>/dev/null | head -1)
  if [[ -n $row ]]; then
    print "R0 dev owner_killed: failed ${${(z)row}[1]} of $(( ${${(z)row}[1]} + ${${(z)row}[2]} )) runs"
  else
    print "R0 dev owner_killed: not found in $OUT/R0-repeat/counts.txt"
  fi
  print "R0 failures by test (rows with failures):"
  awk 'NR > 1 && $1 > 0' $OUT/R0-repeat/counts.txt 2>/dev/null
  print "DONE R0 (information: dev's rate; no PASS/FAIL)"
  next "zsh $THIS R1"
}

step_R1() {
  say "[R1] candidate $CAND: 459 + 495 + 496 files under the parallel-load method. Expected dialog: none. Duration <= 14 min."
  ensure R1 $CAND || return 1
  load_run R1 R1 $DEVFILES $NEWFILE || return 1
  local res=$OUT/R1-repeat row ok=1 rows=0
  # PASS: every test of the three files has 0 failures and > 0 passes.
  for row in ${(f)"$(awk 'NR > 1 && $4 ~ /::/' $res/counts.txt 2>/dev/null)"}; do
    (( rows++ ))
    print -r -- "R1: $row"
    [[ ${${(z)row}[1]} == 0 && ${${(z)row}[2]} -gt 0 ]] || ok=0
  done
  local new=$(grep -c -- "$NEWFILE::" $res/counts.txt 2>/dev/null)
  (( rows > 0 && new >= 2 )) || { ok=0; print "FAIL R1: counts missing ($rows rows, $new rows of $NEWFILE)"; }
  print "R0 dev owner_killed for comparison: $(grep -F -- "$OWNER" $OUT/R0-repeat/counts.txt 2>/dev/null || print 'R0 not run')"
  if (( ok )); then print "PASS R1: 0 failures in every test of the 459, 495 and 496 files ($rows tests)"
  else print "FAIL R1: a failing or missing test above (raw text in $res/failures/)"; fi
  next "zsh $THIS S"
}

step_S() {
  say "[S] candidate $CAND full suite from a fresh checkout ($BASE/suite), started in a background job after a quiet-host wait; then the failing files once on dev $DEV. Expected dialog: none. Duration: foreground ~2 min; background quiet wait <= $(( ${VERIFY496_QUIET_SECONDS:-1200} / 60 )) min, suite ~25 min (shard limit 1500 s), dev recheck <= 10 min."
  check_tmp || return 1
  local listing=$(suites $OUT/S-ps.txt $$ "$THIS _Srun" "$BASE/suite/venv/bin/")
  print -r -- "$listing"
  if [[ $(print -r -- "$listing" | sed -n 's/^ours: //p') != 0 ]]; then
    print "STOP: another S of ours is running (listed under 'ours:'); follow it with: zsh $THIS SR"; return 1
  fi
  build $CAND $BASE/suite || return 1
  [[ -z $(git -C $BASE/suite/src status --porcelain) ]] || { print "STOP: $BASE/suite/src has local changes"; return 1; }
  ensure dev $DEV || return 1
  rm -rf $OUT/S-shards; : > $OUT/S-suite.txt
  (cd $BASE && nohup zsh $THIS _Srun >> $OUT/S-suite.txt 2>&1 < /dev/null &)
  print "started at $(date +%T) in the background; output $OUT/S-suite.txt"
  next "zsh $THIS SR"
}

step__Srun() {
  # Quiet wait in the background job (adopt-497 S), never in Main's foreground.
  local lim=$(load_limit) step=${VERIFY496_QUIET_STEP:-30} max=${VERIFY496_QUIET_SECONDS:-1200} waited=0 out n l1
  print "== quiet wait: every $step s, up to $max s: no running suite (argv tokens) and 1-minute load <= $lim (CPUs $(ncpus))"
  while true; do
    out=$(suites $OUT/S-quiet-ps.txt $$); n=$(print -r -- "$out" | sed -n 's/^running suites: //p'); l1=$(load1)
    print "quiet check $(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null) | running suites ${n:-?}"
    print -r -- "$out" | grep -E '^  running: '
    if [[ $n == 0 ]] && (( l1 <= lim )); then print "== quiet at $(date +%T)"; break; fi
    if (( waited >= max )); then
      print "== STOP not quiet within $max s; the suite was not run. FAIL S (not run). Rerun later: zsh $THIS S"; return 1
    fi
    sleep $step; (( waited += step ))
  done
  print -r -- "$out" | grep -E '^(leftover|  leftover: )'
  local src=$BASE/suite/src VT=$BASE/suite/venv L=$OUT/S-shards
  print "== start $(date +%T) commit $(git -C $src rev-parse HEAD) (expect $CAND); $(load)"
  print "== pytest TMPDIR $TMPB (outside the Harness $H: $([[ ${TMPB:A} == ${H:A}/* ]] && print NO || print YES))"
  (cd $src && clean $VT/bin/python scripts/run_test_shards.py --shards 6 --timeout ${VERIFY496_SUITE_LIMIT:-1500} --log-dir $L \
     ${VERIFY496_SUITE_ARGS:+--} ${(s: :)${VERIFY496_SUITE_ARGS:-}})
  local rc=$?
  print "== shards exit $rc at $(date +%T); $(load)"
  touch $L/failures.txt
  print "== failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  local abnormal=$(grep -c "ABNORMAL" $OUT/S-suite.txt)
  if [[ ! -s $L/failures.txt ]]; then
    if [[ $rc == 0 ]]; then print "PASS S: no failures"
    else print "FAIL S: shards exit $rc with no failing id (ABNORMAL lines or a stopped run above)"; fi
  else
    print "== dev comparison: the failing ids' files once on dev $DEV ($BASE/dev), TMPDIR $TMPB, limit 600 s"
    (cd $BASE/dev/src && clean $BASE/dev/venv/bin/python -I $V487/devcheck.py $L/failures.txt 600)
    local dc=$?
    if [[ $dc == 0 && $abnormal == 0 ]]; then print "PASS S: no NEW failures vs dev (every failing id fails on dev too)"
    else print "FAIL S: NEW or unclassified failures vs dev (above) or ABNORMAL shard output ($abnormal)"; fi
  fi
  print "== DONE $(date +%T)"
}

step_SR() {
  say "[SR] S's background result ($OUT/S-suite.txt). Expected dialog: none. Duration: seconds."
  [[ -s $OUT/S-suite.txt ]] || { print "no S output yet ($OUT/S-suite.txt)"; next "zsh $THIS S"; return 1; }
  if ! grep -q '^== DONE\|^== STOP' $OUT/S-suite.txt; then
    print "RUNNING (last lines below); rerun SR later."
    tail -n 6 $OUT/S-suite.txt
    next "zsh $THIS SR"; return 0
  fi
  grep -E '^== (quiet at|start|shards exit|failures|dev comparison|STOP)|^(PASS|FAIL) S|^[0-9]+ (failed|passed)|passes on dev|fails on dev|absent' $OUT/S-suite.txt
  if grep -q '^FAIL S\|^== STOP' $OUT/S-suite.txt; then next "zsh $THIS CHECK   (quiet recheck of S's failing files on the candidate), then report $OUT to the 496 Leader"
  else next "report $OUT (P.txt R0.txt R1.txt S.txt SR.txt S-suite.txt) to the 496 Leader"; fi
}

# CHECK: S's failing files once on the CANDIDATE (quiet host), as S's dev recheck.
step_CHECK() {
  local failures=${VERIFY496_CHECK_FAILURES:-$OUT/S-shards/failures.txt}
  say "[CHECK] the failing ids' files of $failures once on candidate $CAND ($BASE/R1), verify-487/devcheck.py. Expected dialog: none. Duration <= 10 min (limit 600 s)."
  check_tmp || return 1
  [[ -s $failures ]] || { print "STOP: no failures file $failures"; return 1; }
  ensure R1 $CAND || return 1
  print "NOTE: devcheck.py's 'dev' means THIS CANDIDATE CHECKOUT ($BASE/R1/src at $(git -C $BASE/R1/src rev-parse HEAD)) here:"
  print "      'passes on dev -> NEW' means 'passes on the candidate', 'fails on dev too' means 'fails on the candidate'."
  print "== start $(date +%T); $(load)"
  (cd $BASE/R1/src && clean $BASE/R1/venv/bin/python -I $V487/devcheck.py $failures 600) 2>&1 | tee $OUT/CHECK-devcheck.txt
  print "== devcheck exit ${pipestatus[1]} at $(date +%T) (exit 1 is expected when ids pass here)"
  local id failed=()
  for id in ${(f)"$(awk 'NF > 1 {print $2}' $failures | sort -u)"}; do
    grep -qF -- "  $id: passes on dev -> NEW" $OUT/CHECK-devcheck.txt || failed+=($id)
  done
  if (( ${#failed} == 0 )); then print "PASS CHECK: every id passes on the candidate"
  else print "FAIL CHECK: ${#failed} id(s) did not pass on the candidate (verdicts above):"; print -l -- "  "$^failed; fi
  next "report $OUT to the 496 Leader"
}

case $STEP in
  P|R0|R1|S|SR|CHECK)
    { step_$STEP } 2>&1 | tee $OUT/$STEP.txt
    exit ${pipestatus[1]} ;;
  _Srun) step__Srun; exit $? ;;
  *) print "usage: zsh $THIS <P|R0|R1|S|SR|CHECK>   e.g. zsh $THIS P" ;;
esac
