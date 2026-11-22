#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 566 Main-run steps (modelled on verify-563, itself on verify-531 G/GR). Run one step at a time:  zsh <this file> <STEP>
#   pre   Main. Preflight: shell, paths, graftling commit, TMPDIR outside the Harness, clean candidate. Dialog: none. <10 s.
#   G     Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a venv with the
#         graftling wheel built from git archive of <Harness>/graftling at GCOMMIT (graftling v0.6.3, paired with
#         this GraphTraj base); new pytest temp root under TMPDIR=${TMPDIR:-/tmp}, outside the Harness.
#         VERIFY566_PYTEST_ARGS='<args>' only appends pytest args after `-- -rA` to the same run_test_shards.py call
#         (e.g. '-k <filter>' for a rehearsal; the whole suite is still collected).
#   Gt    Main. Foreground: tests/test_child_env_own_key.py alone, in G's venv. Dialog: none. <1 min.
#   GR    Main. Read only: newest G and Gt; every FAILED/ERROR line classed known (516's CURRENT definition read
#         through 516's task.yml current_definition) or NEW. <10 s.
# No step raises a native review dialog. Production is only read. Venvs are under <Harness>/tmp/566; step output
# under OUT. VERIFY566_T / VERIFY566_OUT are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY566_T:-$H/tmp/566}
OUT=${VERIFY566_OUT:-$H/.graphtraj/core/state/tasks/566-child-env-own-key-test-expects-pre-555-response/realhost}
G=$H/graftling
# graftling v0.6.3 (tag in <Harness>/graftling), adopted by this GraphTraj base (dev 4c701316, Task 560).
GCOMMIT=ef7c37db15f4e6318fd5b6bf5bd79321b876eac5
THIS=${0:A}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
TESTFILE=tests/test_child_env_own_key.py
# 516's CURRENT definition, read through its task.yml (never a guessed filename).
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN516=$D516/${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
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
copy_deps() {  # production's click, yaml, websockets into venv $1 when the base Python lacks them (read only)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $1/bin/python -I -c "import $m" 2>/dev/null && continue
    print -r -- "$m: copied read only from $RT"
    case $m in
      yaml) cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RT/$m $RT/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
g_venv() {  # sets V: venv with the graftling wheel built at GCOMMIT and this Worktree editable
  local GS=${GCOMMIT[1,8]}
  local SRC=$T/graftling-$GS N=$T/wheels-gl-$GS
  V=$T/venv-g-gl-$GS
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V (graftling $GS; this Worktree editable)"
  else
    rm -rf $SRC $N $V && mkdir -p $SRC && git -C $G archive $GCOMMIT | tar -x -C $SRC || { print "STOP: cannot extract graftling"; return 1; }
    $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $SRC >/dev/null || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $WT 2>&1 | grep -vi cache
    print -r -- $GCOMMIT > $V/installed
  fi
}
# A new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-566-$1-$(date +%Y%m%dT%H%M%S)
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
classify() {  # FAILED/ERROR lines of files $@ as known (516's current definition) or NEW
  local line t any=0
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${${line#* }%%\[*}
    if grep -qF -- "${t##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight. Dialog: none. <10 s."
  print "zsh: $ZSH_VERSION ($THIS)"
  print -r -- "Harness: $H | Worktree: $WT ($(git -C $WT rev-parse --short HEAD)) | T=$T | OUT=$OUT"
  check_tmp || return 1
  case ${T:A}/ in ${H:A}/tmp/*|${PYTEST_TMP:A}/*) ;; *) print "STOP: T $T is neither under <Harness>/tmp nor TMPDIR"; return 1 ;; esac
  print -r -- "516 current definition (from task.yml): $KNOWN516"; [[ -f $KNOWN516 ]] || { print "STOP: 516 current definition missing"; return 1; }
  git -C $G cat-file -e $GCOMMIT^{commit} && print -r -- "graftling $GCOMMIT present in $G ($(git -C $G describe --tags --exact-match $GCOMMIT 2>/dev/null || print untagged))" || { print "STOP: graftling commit missing"; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests plugins scripts)
  print "uncommitted in src/tests/plugins/scripts: ${dirty:-none}"
  print "Success: 'pytest temp: ... outside the Harness', the 516 path ends in definitions/<time>.md, graftling ... (v0.6.3), 'uncommitted ...: none'."
  print -r -- "next: zsh $THIS G  (background ~25 min; meanwhile nothing else; then zsh $THIS Gt and zsh $THIS GR)"
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V RUNTMP; g_common G || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP)"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY566_PYTEST_ARGS:-}}})   # shell words, so a quoted -k expression stays one arg
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra (same shard entry; whole suite collected)" | tee -a $R/run.txt
  # `&!` disowns the run and all output is redirected; nohup is not used (without a console it exits 127).
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.3 ...' built from $GCOMMIT, 'started in the background'."
  print -r -- "next (after G ends, i.e. $R/suite.txt ends in exit=N): zsh $THIS Gt"
  ;;
Gt)
  say "[Gt] Main. Foreground: $TESTFILE in G's venv (graftling $GCOMMIT). Dialog: none. <1 min."
  local V RUNTMP; g_common Gt || return 1
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -rA $TESTFILE); local rc=$?
  print "pytest rc=$rc"
  print "Success: 'pytest rc=0' and 'PASSED $TESTFILE::test_a_model_cannot_ask_for_a_key' above."
  print -r -- "next: zsh $THIS GR"
  return $rc
  ;;
GR)
  say "[GR] Main. Read only. Newest G and Gt; FAILED/ERROR lines classed known (516 current definition) or NEW. Dialog: none. <10 s."
  print -r -- "516 current definition: $KNOWN516"
  local g=$(cat $OUT/G-latest 2>/dev/null)
  if [[ -n $g && -f $g/suite.txt ]]; then
    print -r -- "---- G $g"; cat $g/run.txt; tail -6 $g/suite.txt
    grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
    classify $g/suite.txt $g/shards/*(N.)
  else print -r -- "no G result yet; run: zsh $THIS G"; fi
  if [[ -f $OUT/Gt.txt ]]; then
    print -r -- "---- Gt $OUT/Gt.txt"; grep -E '^(PASSED|FAILED|ERROR) |^pytest rc=|^=+ .* in [0-9.]+s' $OUT/Gt.txt
    classify $OUT/Gt.txt
  else print -r -- "no Gt result yet; run: zsh $THIS Gt"; fi
  print "Success: G 'exit=0' or only 'known' lines; Gt 'pytest rc=0'; no 'NEW' line."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|G|Gt|GR" ; return 2 ;;
esac
}

[[ -d $H/graphtraj/.git && -d $H/.graphtraj/core ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
run_step 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
