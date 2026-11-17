#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 500: does 498 end the host test's surviving Runtime under load, and who ends it?
#   zsh <this file> <STEP> [variant]      (one at a time; from any directory; no tee needed)
# Derived from scripts/verify-498/run.zsh (same repeat.py, load.py, busy497.py, devcheck.py, run_test_shards.py).
# Each step writes its own output to $OUT/<STEP>[-variant].txt (the script creates $OUT) as well as to the terminal.
# Dialog: none in every step (no model, no native host, no Claude Code). Every pytest uses TMPDIR=${TMPDIR:-/tmp}
# (refused if inside the Harness). No step signals a process it did not start (the load spinners, repeat workers
# and shards are its own; nothing else).
# Variants (clones under $BASE): old = 3eb312e7 (before 498), new = 871aaaa9 (496 + 498, production),
#   oldt = old + 498's test file (498's tests without 498's product code), cand = the candidate (uninstrumented).
#   old/new/oldt are DIAGNOSTIC clones: instrument.py adds a logging audit hook to their venv and a survivor
#   watcher to their copy of the host test (never committed; never in src/ of this Worktree).
# P:        preflight: shell, Python, CPUs, load, running suites; prints the next commands. Seconds.
# B:        builds old, new and oldt (clone + venv + instrumentation). ~4 min.
# R <v>:    instrumented loaded repetition on variant v (old|new|oldt): the host shutdown file + the 459/495/496/498
#           files present, 6 workers x VERIFY500_PASSES (default 4) passes each + CPU spinners, then AN. Same pass
#           count for every variant. <= 25 min (limit VERIFY500_LIMIT, default 1500 s).
# AN <v>:   analysis only (reads the last R's kill log and counts). Seconds.
# SI <v>:   instrumented FULL suite on variant v (6 shards, background after a quiet-host wait); SIR <v> reads it.
# Racc:     uninstrumented loaded repetition of the same files on the candidate; PASS only on 0 failures.
# S / SR:   candidate full suite from a fresh git checkout (6 shards, background, quiet host), failing files once
#           on new (871aaaa9, uninstrumented clone base) for the comparison; SR reads the verdict.
set -u
setopt no_bg_nice   # the background load runs at normal priority
H=${VERIFY500_H:-/Users/luoxiao/workspace/you-are-a-product-architect-delivery}
SD=${0:A:h}
THIS=${0:A}
SRC=${SD:h:h}
V487=${SD:h}/verify-487
V491=${SD:h}/verify-491
BUSY=${SD:h}/adopt-497/busy497.py
BASE=${VERIFY500_BASE:-$H/tmp/500}
OUT=${VERIFY500_OUT:-$H/.graphtraj/core/state/tasks/500-host-shutdown-survivor-death-after-498/realhost}
OLD=3eb312e7
NEW=871aaaa9
CAND=${VERIFY500_CANDIDATE:-$(git -C $SRC rev-parse HEAD)}
RT=${VERIFY500_RT:-$H/.venv-runtime}
RTSP=$RT/lib/python3.13/site-packages
DEPS=$BASE/deps
STEP=${1:-help}
VAR=${2:-}
FILES=(tests/test_claude_codex_host_shutdown.py tests/test_tool_descendants_459.py
       tests/test_tool_descendant_argv_refresh_495.py tests/test_tool_descendants_496.py tests/test_tool_descendants_498.py)
[[ -n ${VERIFY500_TESTS:-} ]] && FILES=(${(s:,:)VERIFY500_TESTS})   # rehearsal only
mkdir -p $OUT $BASE
TMPB=${TMPDIR:-/tmp}
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main pastes): $*"; }
clean() { env -i HOME=$HOME USER=${USER:-luoxiao} PATH=/opt/homebrew/bin:/usr/bin:/bin TMPDIR=$TMPB LANG=${LANG:-en_US.UTF-8} "$@"; }
base_python() { print -r -- "$($RT/bin/python -I -c 'import sys; print(sys.base_prefix)')/bin/python3"; }
ncpus() { sysctl -n hw.ncpu 2>/dev/null || print 8; }
load() { print -r -- "$(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null || uptime)"; }
load1() { local la=$(sysctl -n vm.loadavg 2>/dev/null); print ${${(s: :)${la//[\{\}]/}}[1]:-0}; }
load_limit() { print ${VERIFY500_LOADMAX:-$(( $(ncpus) / 2 ))}; }
commit_of() { case $1 in old|oldt) print $OLD;; new|base) print $NEW;; cand) print $CAND;; *) return 1;; esac; }
diagnostic() { [[ $1 == old || $1 == new || $1 == oldt ]]; }

check_tmp() {
  print "pytest temp base TMPDIR=\${TMPDIR:-/tmp} = ${TMPB:A} | outside the Harness $H: $([[ ${TMPB:A} != ${H:A}* ]] && print YES || print NO)"
  [[ ${TMPB:A} != ${H:A}* ]] || { print "STOP: TMPDIR is inside the Harness"; return 1; }
}

# Running suites by argv tokens (adopt-497 busy497.py); leftovers under pytest-of-* are only listed.
suites() {
  local file=$1; shift
  ps -axww -o pid=,ppid=,etime=,command= > $file 2>&1 || print "(ps failed: $(head -c 120 $file))"
  $(base_python) -I $BUSY $file "$@"
}

# build <commit> <dir>: clone the exact commit to <dir>/src and make <dir>/venv importing it (verify-498 build).
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
  for x in $DEPS/*(N); do [[ -e $site/${x:t} ]] || ln -s ${x:A} $site/${x:t}; done
  clean $venv/bin/python -m pip install -q --no-deps --no-build-isolation --no-index -e $src/src/graftling -e $src 2>&1 | grep -vi cache
  (( ${pipestatus[1]} == 0 )) || { print "STOP: test venv install failed (text above)"; return 1; }
  clean $venv/bin/python -I -c 'import os, sys, graphtraj, graftling
ok = all(os.path.realpath(m.__file__).startswith(os.path.realpath(sys.argv[1])) for m in (graphtraj, graftling))
print("test venv imports the checkout:", "OK" if ok else "NO", graphtraj.__file__, graftling.__file__); sys.exit(0 if ok else 1)' $src/src \
    || { print "STOP: the test venv does not import the checkout"; return 1; }
}

# ensure <variant>: reuse $BASE/<v> when its clone is at the commit and its venv exists; else build (and instrument).
ensure() {
  local name=$1 commit=$(commit_of $1) D=$BASE/$1
  if [[ $(git -C $D/src rev-parse HEAD 2>/dev/null) == $(git -C $SRC rev-parse $commit) && -x $D/venv/bin/python ]]; then
    print "$name clone reused: $D/src at $(git -C $D/src rev-parse HEAD)"
  else build $commit $D || return 1; fi
  if [[ $name == oldt ]]; then
    git -C $SRC show ${NEW}:tests/test_tool_descendants_498.py > $D/src/tests/test_tool_descendants_498.py || return 1
    print "oldt: 498's test file from $NEW copied into the $OLD clone"
  fi
  if diagnostic $name; then
    $D/venv/bin/python -I $SD/instrument.py $D $D/killlog || { print "STOP: instrumentation failed"; return 1; }
  else
    [[ -z $(git -C $D/src status --porcelain) ]] || { print "STOP: $D/src has local changes (an uninstrumented clone must be clean)"; return 1; }
  fi
}

# fresh_log <variant> <label>: the hook writes to killlog/current; point it at an empty runs/<label>.
fresh_log() {
  local K=$BASE/$1/killlog
  rm -rf $K/runs/$2 && mkdir -p $K/runs/$2 && ln -sfn runs/$2 $K/current
  print "kill log for this run: $K/runs/$2"
}

analyse() {
  local v=$1 label=$2 res=${3:--}
  local K=$BASE/$v/killlog/runs/$label
  $(base_python) -I $SD/analyze.py $K $res "$v $label ($(commit_of $v))"
  (cd $BASE/$v/killlog/runs && tar czf $OUT/$label-$v-killlog.tgz $label) && print "kill log archived: $OUT/$label-$v-killlog.tgz"
}

step_P() {
  say "500 P preflight $(date '+%F %T %Z') | Expected dialog: none | seconds"
  print "script: $THIS (worktree $SRC at $(git -C $SRC rev-parse --short HEAD 2>/dev/null))"
  print "shell: $ZSH_VERSION | SHELL=${SHELL:-unset} | runtime python: $($RT/bin/python -I -c 'import sys; print(sys.version.split()[0], sys.executable)' 2>&1)"
  print "base python: $(base_python) | pytest $($(base_python) -I -c 'import pytest; print(pytest.__version__)' 2>&1)"
  print "CPUs: $(ncpus) | $(load) | quiet limit for SI/S: 1-minute load <= $(load_limit)"
  check_tmp
  print "running suites (argv tokens; leftovers under pytest-of-* only listed, never signalled):"
  suites $OUT/P-ps.txt $$
  print "old $OLD = $(git -C $SRC rev-parse $OLD) | new $NEW = $(git -C $SRC rev-parse $NEW) | candidate $CAND"
  print "output dir $OUT | clones under $BASE"
  next "zsh $THIS B"
}

step_B() {
  say "[B] build old $OLD, new $NEW and oldt (old + 498's test file) under $BASE, instrumented. Expected dialog: none. Duration ~4 min."
  check_tmp || return 1
  local v
  for v in old new oldt; do ensure $v || return 1; done
  print "PASS B (diagnostic clones ready under $BASE)"
  next "zsh $THIS R new    (then: zsh $THIS R old ; zsh $THIS R oldt)"
}

# load_run <variant> <label> <targets...>: 491/495's parallel-plus-load run; result under $OUT/<label>-repeat.
load_run() {
  local name=$1 label=$2; shift 2
  local targets=($@) limit=${VERIFY500_LIMIT:-1500} spin=${VERIFY500_SPIN:-$(ncpus)}
  local workers=${VERIFY500_WORKERS:-6} passes=${VERIFY500_PASSES:-4} res=$OUT/$label-repeat
  print "${#targets} files x$passes passes on each of $workers workers, plus $spin CPU spinners; limit $limit s (+20 s stop):"
  print -l -- "  "$^targets
  check_tmp || return 1
  local listing=$(suites $OUT/$label-ps.txt $$)
  print -r -- "$listing"
  [[ $listing != *'(ps failed'* || -n ${VERIFY500_NOPS:-} ]] || { print "STOP: ps failed, running suites unknown"; return 1; }
  if [[ $(print -r -- "$listing" | sed -n 's/^running suites: //p') != 0 ]]; then
    print "STOP: another test suite is running (listed above); rerun when it has ended"; return 1
  fi
  rm -rf $res; mkdir -p $res
  print "CPUs: $(ncpus) | start $(load)" | tee $res/loadavg.txt
  env -i HOME=$HOME PATH=/usr/bin:/bin TMPDIR=$TMPB $(base_python) -I $V491/load.py $spin $(( limit + 30 )) $res/loadavg.txt \
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

present_files() { local f; for f in $FILES; do [[ -f $BASE/$1/src/${f%%::*} ]] && print -r -- $f; done; }

step_R() {
  diagnostic $VAR || { print "usage: zsh $THIS R <old|new|oldt>"; return 1; }
  say "[R $VAR] instrumented loaded repetition on $VAR ($(commit_of $VAR)). Expected dialog: none. Duration <= $(( ${VERIFY500_LIMIT:-1500} / 60 + 1 )) min."
  ensure $VAR || return 1
  fresh_log $VAR R
  load_run $VAR R-$VAR ${(f)"$(present_files $VAR)"} || return 1
  analyse $VAR R $OUT/R-$VAR-repeat
  case $VAR in new) next "zsh $THIS R old";; old) next "zsh $THIS R oldt";; *) next "report $OUT (R-new.txt R-old.txt R-oldt.txt) to the 500 Engineer";; esac
}

step_AN() {
  diagnostic $VAR || { print "usage: zsh $THIS AN <old|new|oldt>"; return 1; }
  say "[AN $VAR] analysis of the last R on $VAR. Expected dialog: none. Seconds."
  analyse $VAR R $OUT/R-$VAR-repeat
}

step_SI() {
  diagnostic $VAR || { print "usage: zsh $THIS SI <old|new|oldt>"; return 1; }
  say "[SI $VAR] instrumented full suite on $VAR ($(commit_of $VAR)), 6 shards, in a background job after a quiet-host wait. Expected dialog: none. Duration: foreground ~1 min; background quiet wait <= $(( ${VERIFY500_QUIET_SECONDS:-1200} / 60 )) min, suite ~25 min."
  check_tmp || return 1
  local listing=$(suites $OUT/SI-$VAR-ps.txt $$ "$THIS _Srun" "$BASE/suite/venv/bin/" "$BASE/$VAR/venv/bin/")
  print -r -- "$listing"
  [[ $(print -r -- "$listing" | sed -n 's/^ours: //p') == 0 ]] || { print "STOP: a suite of ours is running (listed under 'ours:')"; return 1; }
  ensure $VAR || return 1
  fresh_log $VAR SI
  rm -rf $OUT/SI-$VAR-shards; : > $OUT/SI-$VAR-suite.txt
  (cd $BASE && trap '' HUP && zsh $THIS _Srun $VAR SI-$VAR >> $OUT/SI-$VAR-suite.txt 2>&1 < /dev/null &!)
  print "started at $(date +%T) in the background; output $OUT/SI-$VAR-suite.txt"
  next "zsh $THIS SIR $VAR"
}

step_SIR() {
  diagnostic $VAR || { print "usage: zsh $THIS SIR <old|new|oldt>"; return 1; }
  say "[SIR $VAR] the instrumented suite's result and analysis. Expected dialog: none. Seconds."
  local log=$OUT/SI-$VAR-suite.txt
  [[ -s $log ]] || { print "no SI output yet ($log)"; return 1; }
  if ! grep -q '^== DONE\|^== STOP' $log; then print "RUNNING (last lines below); rerun SIR later."; tail -n 6 $log; next "zsh $THIS SIR $VAR"; return 0; fi
  grep -E '^== (quiet at|start|shards exit|failures)|^(PASS|FAIL)|^[0-9]+ (failed|passed)|^ABNORMAL|FAILED' $log
  analyse $VAR SI -
  next "report $OUT (SI-$VAR.txt SIR-$VAR.txt) to the 500 Engineer"
}

# _Srun <variant> <label>: quiet wait, then 6 shards from $BASE/<variant>/src (S: the comparison on base).
step__Srun() {
  local v=$1 label=$2
  local lim=$(load_limit) step=${VERIFY500_QUIET_STEP:-30} max=${VERIFY500_QUIET_SECONDS:-1200} waited=0 out n l1
  print "== quiet wait: every $step s, up to $max s: no running suite (argv tokens) and 1-minute load <= $lim (CPUs $(ncpus))"
  while true; do
    out=$(suites $OUT/$label-quiet-ps.txt $$); n=$(print -r -- "$out" | sed -n 's/^running suites: //p'); l1=$(load1)
    print "quiet check $(date +%T) loadavg $(sysctl -n vm.loadavg 2>/dev/null) | running suites ${n:-?}"
    print -r -- "$out" | grep -E '^  running: '
    if [[ $n == 0 ]] && (( l1 <= lim )); then print "== quiet at $(date +%T)"; break; fi
    if (( waited >= max )); then print "== STOP not quiet within $max s; the suite was not run. FAIL $label (not run)."; return 1; fi
    sleep $step; (( waited += step ))
  done
  print -r -- "$out" | grep -E '^(leftover|  leftover: )'
  local src=$BASE/$v/src VT=$BASE/$v/venv L=$OUT/$label-shards rc
  print "== start $(date +%T) commit $(git -C $src rev-parse HEAD) ($v); $(load)"
  print "== pytest TMPDIR $TMPB (outside the Harness $H: $([[ ${TMPB:A} == ${H:A}/* ]] && print NO || print YES))"
  (cd $src && clean $VT/bin/python scripts/run_test_shards.py --shards 6 --timeout ${VERIFY500_SUITE_LIMIT:-1500} --log-dir $L \
     ${VERIFY500_SUITE_ARGS:+--} ${(s: :)${VERIFY500_SUITE_ARGS:-}})
  rc=$?
  print "== shards exit $rc at $(date +%T); $(load)"
  touch $L/failures.txt
  print "== failures ($(wc -l < $L/failures.txt | tr -d ' ')):"; cat $L/failures.txt
  if [[ $label == S ]]; then
    local abnormal=$(grep -c "ABNORMAL" $OUT/S-suite.txt)
    if [[ ! -s $L/failures.txt ]]; then
      [[ $rc == 0 ]] && print "PASS S: no failures" || print "FAIL S: shards exit $rc with no failing id"
    else
      print "== comparison: the failing ids' files once on $NEW ($BASE/base, the accepted 498/499 product), TMPDIR $TMPB, limit 600 s"
      (cd $BASE/base/src && clean $BASE/base/venv/bin/python -I $V487/devcheck.py $L/failures.txt 600)
      if [[ $? == 0 && $abnormal == 0 ]]; then print "PASS S: no NEW failures vs $NEW (every failing id fails there too)"
      else print "FAIL S: NEW or unclassified failures vs $NEW (above) or ABNORMAL shard output ($abnormal)"; fi
    fi
  fi
  print "== DONE $(date +%T)"
}

step_Racc() {
  say "[Racc] candidate $CAND, UNinstrumented ($BASE/cand): the same files under the parallel-load method. Expected dialog: none. Duration <= $(( ${VERIFY500_LIMIT:-1500} / 60 + 1 )) min."
  ensure cand || return 1
  load_run cand Racc ${(f)"$(present_files cand)"} || return 1
  local res=$OUT/Racc-repeat row ok=1 rows=0
  for row in ${(f)"$(awk 'NR > 1 && $4 ~ /::/' $res/counts.txt 2>/dev/null)"}; do
    (( rows++ )); print -r -- "Racc: $row"
    [[ ${${(z)row}[1]} == 0 && ${${(z)row}[2]} -gt 0 ]] || ok=0
  done
  (( rows > 0 )) || { ok=0; print "FAIL Racc: no counts"; }
  (( ok )) && print "PASS Racc: 0 failures in every test ($rows tests)" || print "FAIL Racc: a failing or missing test above (raw text in $res/failures/)"
  next "zsh $THIS S"
}

step_S() {
  say "[S] candidate $CAND full suite from a fresh checkout ($BASE/suite), background after a quiet-host wait; then failing files once on $NEW. Expected dialog: none. Duration: foreground ~2 min; quiet wait <= $(( ${VERIFY500_QUIET_SECONDS:-1200} / 60 )) min, suite ~25 min, comparison <= 10 min."
  check_tmp || return 1
  local listing=$(suites $OUT/S-ps.txt $$ "$THIS _Srun" "$BASE/suite/venv/bin/")
  print -r -- "$listing"
  [[ $(print -r -- "$listing" | sed -n 's/^ours: //p') == 0 ]] || { print "STOP: another S of ours is running; follow it with: zsh $THIS SR"; return 1; }
  build $CAND $BASE/suite || return 1
  [[ -z $(git -C $BASE/suite/src status --porcelain) ]] || { print "STOP: $BASE/suite/src has local changes"; return 1; }
  ensure base || return 1
  rm -rf $OUT/S-shards; : > $OUT/S-suite.txt
  (cd $BASE && trap '' HUP && zsh $THIS _Srun suite S >> $OUT/S-suite.txt 2>&1 < /dev/null &!)
  print "started at $(date +%T) in the background; output $OUT/S-suite.txt"
  next "zsh $THIS SR"
}

step_SR() {
  say "[SR] S's background result ($OUT/S-suite.txt). Expected dialog: none. Seconds."
  [[ -s $OUT/S-suite.txt ]] || { print "no S output yet"; next "zsh $THIS S"; return 1; }
  if ! grep -q '^== DONE\|^== STOP' $OUT/S-suite.txt; then print "RUNNING (last lines below); rerun SR later."; tail -n 6 $OUT/S-suite.txt; next "zsh $THIS SR"; return 0; fi
  grep -E '^== (quiet at|start|shards exit|failures|comparison|STOP)|^(PASS|FAIL) S|^[0-9]+ (failed|passed)|^ABNORMAL|passes on dev|fails on dev|absent' $OUT/S-suite.txt
  print "accepted results for comparison: 498 S $H/.graphtraj/core/state/tasks/498-tool-descendant-identification-design/realhost/S-suite.txt;"
  print "  499 S $H/.graphtraj/core/state/tasks/499-production-adoption-496-498/adoption/raw-871aaaa9/S-suite.txt"
  next "report $OUT (Racc.txt S.txt SR.txt S-suite.txt) to the 500 Engineer"
}

case $STEP in
  P|B|Racc|S|SR) { step_$STEP } 2>&1 | tee $OUT/$STEP.txt; exit ${pipestatus[1]} ;;
  R|AN|SI|SIR) { step_$STEP } 2>&1 | tee $OUT/$STEP-${VAR:-none}.txt; exit ${pipestatus[1]} ;;
  _Srun) step__Srun $VAR ${3:-S}; exit $? ;;
  *) print "usage: zsh $THIS <P|B|R v|AN v|SI v|SIR v|Racc|S|SR>   (v = old|new|oldt), e.g. zsh $THIS P" ;;
esac
