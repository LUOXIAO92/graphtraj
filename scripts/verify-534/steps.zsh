#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 534 Main-run steps (modelled on the accepted verify-531 G/Gt/GR). Run one step at a time:  zsh <this file> <STEP>
#   G   Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min), graftling wheel built
#       from git archive of <Harness>/graftling at v0.6.2 (production's graftling); new pytest temp root outside the
#       Harness. VERIFY534_TESTS=<files> runs plain pytest on those files instead (rehearsal of the entry).
#   Gt  Main. The focused backup tests (tests/test_github_backup.py, tests/test_migration_mappings.py) through G's
#       venv, foreground (~1 min).
#   GR  Main. Read only: newest G and Gt; every FAILED/ERROR line classed known (latest accepted full suite, 516) or NEW.
# No production install: .venv-runtime is only read (click, yaml, websockets copied out). No real GitHub request:
# the backup tests use their own fake gh. Venvs under <Harness>/tmp/534.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY534_T:-$H/tmp/534}               # the VERIFY534_T/OUT overrides are for the Engineer's rehearsal only
OUT=${VERIFY534_OUT:-$H/.graphtraj/core/state/tasks/534-backup-detaches-sub-issue-on-reparent/realhost}
G=$H/graftling
GCOMMIT=4a002129f8b97f32980afd59e5a1a64c428fe684   # graftling v0.6.2 = production's (528, kept by 531/532)
THIS=${0:A}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
# Latest accepted full-suite result: 531's G when present, else 528's accepted G.
KNOWN_G=(${(f)"$(ls -1d $H/.graphtraj/core/state/tasks/531-*/realhost/G-*/suite.txt(N) 2>/dev/null | tail -1)"})
[[ -n ${KNOWN_G:-} ]] || KNOWN_G=$H/.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/G-8267f9e5-20261119T235550/suite.txt
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
FOCUSED=(tests/test_github_backup.py tests/test_migration_mappings.py)
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
quiet() {  # suites run on a quiet host, one Main step at a time
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS $STEP"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (read only; no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}

# G's venv (also Gt's): conda --system-site-packages + production's click/yaml/websockets + graftling wheel built
# from git archive $GCOMMIT (never the working tree) + this Worktree editable. Sets V.
g_venv() {
  local GS=${GCOMMIT[1,8]}
  local SRC=$T/graftling-$GS N=$T/wheels-gl-$GS
  V=$T/venv-g-gl-$GS
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V (graftling $GS; this Worktree editable)"
  else
    rm -rf $SRC $N $V && mkdir -p $SRC && git -C $G archive $GCOMMIT | tar -x -C $SRC || { print "STOP: cannot extract graftling"; return 1; }
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $SRC/src/graftling >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT 2>&1 | grep -vi cache
    print -r -- $GCOMMIT > $V/installed
  fi
}
# A new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-534-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
g_common() {  # guard + venv + imports
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  print "uncommitted in src/tests/plugins: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  new_runtmp $1 || return 1
  g_venv || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT"
}
classify() {  # FAILED/ERROR lines of files $@ as known (latest accepted G, 516) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "$t" $KNOWN_G 2>/dev/null; then print -r -- "known (accepted G ${KNOWN_G:h:t}): $line"
    elif grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

run_step() {
case $STEP in
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V RUNTMP; g_common G || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY534_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY534_TESTS (plain pytest, same venv, temp root and exit file)" | tee -a $R/run.txt
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY534_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  else
    (cd $WT && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  fi
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.2 ...', 'started in the background'."
  print -r -- "next: zsh $THIS Gt  (after G ends: zsh $THIS GR)"
  ;;
Gt)
  say "[Gt] Main. Focused backup tests via G's venv, foreground. Dialog: none. ~1 min."
  local V RUNTMP; g_common Gt || return 1
  local R=$OUT/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -v -rfE --basetemp=$RUNTMP/bt $FOCUSED > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  grep -E 'PASSED|FAILED|ERROR' $R/suite.txt | grep -E 'test_github_backup' | sed 's/ *\[.*%\]$//'
  tail -3 $R/suite.txt; classify $R/suite.txt
  print -r -- $R > $OUT/Gt-latest
  print "Success: the test_github_backup tests listed PASSED (including the three 534 tests: detached, moved once,"
  print "external only reported), 'N passed' with exit=0 and '(no FAILED/ERROR lines)'."
  print -r -- "next: zsh $THIS GR  (when G's suite.txt ends with exit=)"
  ;;
GR)
  say "[GR] Main. Read only. Newest G and Gt; FAILED/ERROR lines classed known (accepted G, 516) or NEW. Dialog: none. <10 s."
  print -r -- "known baseline: $KNOWN_G"
  local g=$(cat $OUT/G-latest 2>/dev/null) t=$(cat $OUT/Gt-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify $t/suite.txt; }
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line in G or Gt."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS G|Gt|GR" ; return 2 ;;
esac
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
