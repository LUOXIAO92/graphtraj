#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 554 Main-run steps (modelled on verify-547 and verify-531 G/Gt/GR). Docs-only change; no base comparison.
# One step at a time:
#   zsh <this file> <STEP>
#   0   Main. Preflight: zsh, Harness, Worktree HEAD, graftling commit, pytest temp line; builds the candidate
#       venv (no network). Dialog: none. ~1 min.
#   Gt  Main. Focused tests (backup behaviour, manual description, packaged manuals) through the candidate venv,
#       foreground. Uses the fake gh only; no GitHub request. Dialog: none. ~1-2 min.
#   G   Main. GraphTraj full suite of this Worktree's HEAD (6 shards, --timeout 1500, -rA, background ~25 min).
#       Dialog: none.
#   GR  Main. Read only: newest G and Gt; every FAILED/ERROR line classed known (listed in 516) or NEW; prints the
#       accepted 547 full-suite summary on dev as prior evidence. Dialog: none.
# graftling: wheel built from `git archive` of <Harness>/graftling at 6794ce02 (graftling dev, paired with GraphTraj
# dev). click/yaml/websockets copied from <Harness>/.venv-runtime (read only). Venvs under $T (<Harness>/tmp/554);
# pytest temp under TMPDIR=${TMPDIR:-/tmp}, refused inside the Harness. Step output kept under $OUT (the Task state
# dir's realhost). No step signals a process it did not start.
# Rehearsal-only overrides: VERIFY554_T, VERIFY554_OUT, VERIFY554_TESTS (limited plain pytest run for G).
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY554_T:-$H/tmp/554}
OUT=${VERIFY554_OUT:-$H/.graphtraj/core/state/tasks/554-task-sync-manual-and-retire-harness-duplicate/realhost}
GSRC=$H/graftling                                      # read only (git archive)
GCOMMIT=6794ce02b6210ec88837437affb8d7b525612804       # graftling dev paired with GraphTraj dev
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: click, yaml, websockets
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
PRIOR547=$H/.graphtraj/core/state/tasks/547-backup-cross-repository-sub-issues/realhost/GR.txt
FOCUSED=(tests/test_github_backup.py tests/test_gateway.py tests/test_wheel_installation.py)
path=(/opt/homebrew/bin $HOME/.local/bin $path)

say() { print -r -- "== $*"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}
quiet() {
  local listing
  listing=$(ps -axww -o pid=,command= 2>&1) || { print "NOTE: ps is not permitted here ($listing); check by hand that no other test run is running"; return 0; }
  local others=$(print -r -- $listing | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun later: zsh $THIS $STEP"; print -r -- $others; return 1; }
}
deps() {  # click, yaml, websockets from production's runtime into venv $1 (read only; no PyPI)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
t_venv() {  # candidate venv. Sets V (venv) and S (this Worktree).
  local N=$T/wheels-gl-${GCOMMIT[1,8]}
  S=$WT; V=$T/venv-cand
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $GSRC"; return 1; }
  if [[ -x $V/bin/python && -f $V/installed && $(<$V/installed) == "$S $GCOMMIT" ]]; then
    print "reusing $V ($S editable; graftling ${GCOMMIT[1,8]} wheel)"; return 0; fi
  rm -rf $V; mkdir -p $T
  if [[ ! -f $N/installed ]]; then
    local src=$N/src; rm -rf $N; mkdir -p $src
    git -C $GSRC archive $GCOMMIT src/graftling | tar -x -C $src || { print "STOP: cannot extract graftling"; return 1; }
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $src/src/graftling >/dev/null || { print "STOP: graftling wheel did not build"; return 1; }
    touch $N/installed
  fi
  $CONDA -m venv --system-site-packages $V && deps $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $N/graftling-*.whl || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -e $S 2>&1 | grep -vi cache
  print -r -- "$S $GCOMMIT" > $V/installed
  print "built $V: $S editable + graftling wheel from git archive ${GCOMMIT[1,10]}"
}
# A new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above it. Sets RUNTMP.
new_runtmp() {
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-554-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
prepare() {  # guard + venv + imports. Sets V S RUNTMP.
  local dirty=$(git -C $WT status --porcelain -- src tests plugins manuals)
  print "uncommitted in src/tests/plugins/manuals: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  new_runtmp $1 || return 1
  t_venv || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  print -r -- "cand: $(git -C $S rev-parse HEAD) | graftling wheel from git archive $GCOMMIT"
}
failures() { grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u; }
classify() {  # candidate files: known (516) or NEW
  local line any=0
  for line in ${(f)"$(failures $@)"}; do
    any=1
    if grep -qF -- "${${${line#* }%%\[*}##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
    else print -r -- "NEW: $line"; fi
  done
  (( any )) || print "(no FAILED/ERROR lines)"
}

run_step() {
case $STEP in
0)
  say "[0] Main. Preflight + candidate venv. Dialog: none. ~1 min."
  print "zsh: $ZSH_VERSION ($THIS)"
  print "Harness: $H | Worktree: $WT | HEAD $(git -C $WT rev-parse HEAD) (branch $(git -C $WT branch --show-current))"
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: $GSRC lacks graftling $GCOMMIT"; return 1; }
  print "graftling: $(git -C $GSRC log -1 --format='%H %s' $GCOMMIT) (from $GSRC, git archive)"
  print "no Runtime is started and no GitHub request is made (backup tests use the fake gh)"
  check_tmp || return 1
  local V S; t_venv || return 1
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__)') || return 1
  print "Success: 'pytest temp: TMPDIR=... (outside the Harness)', the graphtraj line under $WT/src, a graftling line under $T."
  print -r -- "next: zsh $THIS Gt"
  ;;
Gt)
  say "[Gt] Main. Focused tests via the candidate venv, foreground. Dialog: none. ~1-2 min."
  local V S RUNTMP; prepare cand || return 1
  local R=$OUT/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt $FOCUSED > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  tail -3 $R/suite.txt; classify $R/suite.txt
  print -r -- $R > $OUT/Gt-latest
  print "Success: 'N passed' with exit=0 and '(no FAILED/ERROR lines)'."
  print -r -- "next: zsh $THIS G   (background ~25 min; then, after it ends: zsh $THIS GR)"
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  quiet || return 1
  local V S RUNTMP; prepare cand || return 1
  local R=$OUT/G-$(git -C $S rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "cand: $S at $(git -C $S rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY554_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY554_TESTS (plain pytest, same venv, temp root and exit file); foreground" | tee -a $R/run.txt
    (cd $S && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY554_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
    tail -3 $R/suite.txt
  else
    (cd $S && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
    print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends, ~25 min)"
  fi
  print -r -- $R > $OUT/G-latest
  print "Success: the graphtraj line under $WT/src, 'graftling ...' under $T, 'started in the background'."
  print -r -- "next: after $R/suite.txt ends with exit=: zsh $THIS GR"
  ;;
GR)
  say "[GR] Main. Read only. Newest G and Gt; FAILED/ERROR lines classed known (516) or NEW. Dialog: none. <10 s."
  local g=$(cat $OUT/G-latest 2>/dev/null) t=$(cat $OUT/Gt-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- $g"; cat $g/run.txt; tail -4 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "still running (no exit= line yet); rerun later: zsh $THIS GR"
  print -r -- "---- candidate G classification"; classify $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify $t/suite.txt; }
  print -r -- "---- prior evidence: accepted 547 full suite on dev ($PRIOR547)"
  grep -E 'passed|^exit=' $PRIOR547 2>/dev/null | head -2 || print "(not readable)"   # its G (candidate) lines
  print "Success: G 'exit=0' or only 'known (516)' lines; no 'NEW' line in G or Gt."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS 0|Gt|G|GR"; return 2 ;;
esac
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
mkdir -p $T $OUT
# Every step's output also goes to $OUT/<STEP>.txt; an earlier one is kept as <STEP>-<time>.txt.
[[ -f $OUT/$STEP.txt ]] && mv $OUT/$STEP.txt $OUT/$STEP-$(date -r $OUT/$STEP.txt +%Y%m%dT%H%M%S).txt
{ print "Dialog: none"; run_step; } 2>&1 | tee $OUT/$STEP.txt
local rc=$?
print -r -- "(output kept in $OUT/$STEP.txt; rc=$rc)"
return $rc
