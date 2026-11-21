#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 556 Main-run steps (modelled on verify-547 and verify-531 G/GR). One step at a time:
#   zsh <this file> <STEP>
#   0   Main. Preflight: zsh, Harness, Worktree HEAD, base, graftling commit, pytest temp line; builds the candidate
#       venv (no network). Dialog: none. ~1 min.
#   Gt  Main. Focused 556 tests (FOCUSED below) through the candidate venv, foreground. Dialog: none. <1 min.
#   D   Main. Demonstration through the real graphtraj-mcp entry of the candidate venv, in a new scratch project
#       under $T: one call with several errors returned at once, the same call after fixing only the JSON file,
#       and refused files. Starts no Runtime; writes nothing in the Harness project. Dialog: none. <1 min.
#   G   Main. GraphTraj full suite of this Worktree's HEAD (6 shards, --timeout 1500, -rA, background ~25 min).
#   B   Main. The same full suite on base e3eb7649 (a git checkout under $T), background ~25 min, after G ends.
#   GR  Main. Read only: newest G, B and Gt; every candidate FAILED/ERROR line classed known (fails on base B too,
#       or listed in 516) or NEW.
# graftling: wheel built from `git archive` of <Harness>/graftling at aea5962d (555, graftling dev). click/yaml/
# websockets copied from <Harness>/.venv-runtime (read only). Venvs, the base checkout and demo projects under $T
# (<Harness>/tmp/556); pytest temp under TMPDIR=${TMPDIR:-/tmp}, refused inside the Harness.
# Step output kept under $OUT (the Task state dir's realhost). No step signals a process it did not start.
# Rehearsal-only overrides: VERIFY556_T, VERIFY556_OUT, VERIFY556_TESTS (limited plain pytest run for G/B).
emulate -L zsh
setopt pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree
H=${WT:h:h:h:h}                                        # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY556_T:-$H/tmp/556}
OUT=${VERIFY556_OUT:-$H/.graphtraj/core/state/tasks/556-graphtraj-mcp-full-validation-json-file-arguments/realhost}
GSRC=$H/graftling                                      # read only (git archive)
GCOMMIT=aea5962d118aa785f32878ada095862d5ec545a3       # graftling dev with 555
BASE_COMMIT=e3eb76493716edb61a50258cbdb4ef9cb0c90d45   # GraphTraj dev base of 556
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages      # read only: click, yaml, websockets
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
KNOWN516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests/task.md
FOCUSED=(tests/test_arguments_file_556.py tests/test_gateway.py tests/test_shared_tools.py tests/test_local_tool.py
         tests/test_cli_projection.py tests/test_graphtraj_public_agents_api.py)
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
# venv for $1 cand|base. Sets V (venv) and S (source: this Worktree, or a git checkout of base under $T).
t_venv() {
  local N=$T/wheels-gl-${GCOMMIT[1,8]}
  if [[ $1 == cand ]]; then S=$WT; else S=$T/base-src-${BASE_COMMIT[1,8]}; fi
  V=$T/venv-$1
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $GSRC"; return 1; }
  if [[ $1 == base && ! -f $S/pyproject.toml ]]; then   # a Git checkout: the test fixtures run git ls-files in it
    rm -rf $S; mkdir -p $T
    git clone -q --shared --no-checkout $WT $S && git -C $S checkout -q --detach $BASE_COMMIT \
      || { print "STOP: cannot check out $BASE_COMMIT into $S"; return 1; }
  fi
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
  RUNTMP=${PYTEST_TMP:A}/verify-556-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
prepare() {  # $1 cand|base: guard + venv + imports. Sets V S RUNTMP.
  if [[ $1 == cand ]]; then
    local dirty=$(git -C $WT status --porcelain -- src tests plugins scripts/verify-556)
    print "uncommitted in src/tests/plugins/scripts/verify-556: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  fi
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  new_runtmp $1 || return 1
  t_venv $1 || return 1
  (cd $RUNTMP && $V/bin/python -I -c 'import graphtraj, graftling, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| pytest", pytest.__version__)') || return 1
  print -r -- "$1: $(git -C $S rev-parse HEAD) | graftling wheel from git archive $GCOMMIT"
}
suite() {  # $1 cand|base: full suite in the background (or VERIFY556_TESTS in the foreground)
  setopt local_options no_bg_nice
  quiet || return 1
  local V S RUNTMP; prepare $1 || return 1
  local R=$OUT/$([[ $1 == cand ]] && print G || print B)-$(git -C $S rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "$1: $S at $(git -C $S rev-parse HEAD) | graftling $GCOMMIT"; } > $R/run.txt
  if [[ -n ${VERIFY556_TESTS:-} ]]; then
    print "REHEARSAL: tests limited to $VERIFY556_TESTS (plain pytest, same venv, temp root and exit file); foreground" | tee -a $R/run.txt
    (cd $S && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE ${=VERIFY556_TESTS} > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
    tail -3 $R/suite.txt
  else
    (cd $S && TMPDIR=$RUNTMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
    print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends, ~25 min)"
  fi
  print -r -- $R > $OUT/$([[ $1 == cand ]] && print G || print B)-latest
}
failures() { grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u; }
classify() {  # $1 base run dir or '', then candidate files: known (fails on base B too / 516) or NEW
  local b=$1; shift
  local base_fail="" line any=0
  [[ -n $b ]] && base_fail=$(failures $b/suite.txt $b/shards/*(N.))
  for line in ${(f)"$(failures $@)"}; do
    any=1
    if [[ -n $base_fail ]] && print -r -- $base_fail | grep -qxF -- $line; then print -r -- "known (fails on base B too): $line"
    elif grep -qF -- "${${${line#* }%%\[*}##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
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
  print "base: $(git -C $WT log -1 --format='%H %s' $BASE_COMMIT)"
  git -C $GSRC cat-file -e $GCOMMIT^{commit} || { print "STOP: $GSRC lacks graftling $GCOMMIT"; return 1; }
  print "graftling: $(git -C $GSRC log -1 --format='%H %s' $GCOMMIT) (from $GSRC, git archive)"
  print "no Runtime is started and no GitHub request is made"
  check_tmp || return 1
  local V S; t_venv cand || return 1
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__); from graftling import read_envelope_arguments, ValidationErrors, schema_errors') || return 1
  print "Success: 'pytest temp: TMPDIR=... (outside the Harness)', the graphtraj line under $WT/src, a graftling line under $T."
  print -r -- "next: zsh $THIS Gt"
  ;;
Gt)
  say "[Gt] Main. Focused 556 tests via the candidate venv, foreground. Dialog: none. <1 min."
  local V S RUNTMP; prepare cand || return 1
  local R=$OUT/Gt-$(git -C $WT rev-parse --short HEAD)-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "files: $FOCUSED" | tee $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE --basetemp=$RUNTMP/bt $FOCUSED > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt)
  tail -3 $R/suite.txt; classify "" $R/suite.txt
  print -r -- $R > $OUT/Gt-latest
  print "Success: 'N passed' with exit=0 and '(no FAILED/ERROR lines)'."
  print -r -- "next: zsh $THIS D"
  ;;
D)
  say "[D] Main. Real graphtraj-mcp entry demonstration in a new scratch project under $T. Dialog: none. <1 min."
  local V S; t_venv cand || return 1
  local P=$T/demo-$(date +%Y%m%dT%H%M%S)
  [[ -x $V/bin/graphtraj-mcp ]] || { print "STOP: $V/bin/graphtraj-mcp is missing"; return 1; }
  print -r -- "entry: $V/bin/graphtraj-mcp (candidate $(git -C $WT rev-parse HEAD)); project: $P"
  (cd $T && $V/bin/python -I $SD/demo556.py $V/bin/graphtraj-mcp $P) || { print "STOP: an expectation failed (above)"; return 1; }
  print "Success: step 1 isError true with 4 errors, step 2 isError false with an event_id, step 3 four refusals naming only the path, and 'RESULT: all expectations held'."
  print -r -- "next: zsh $THIS G   (background ~25 min; then, after it ends: zsh $THIS B, then zsh $THIS GR)"
  ;;
G)
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. Run nothing else meanwhile."
  suite cand || return 1
  print "Success: the graphtraj line under $WT/src, 'graftling ...' under $T, 'started in the background'."
  print -r -- "next: after G's suite.txt ends with exit=: zsh $THIS B"
  ;;
B)
  say "[B] Main. The same full suite on base ${BASE_COMMIT[1,8]} for comparison (background ~25 min). Dialog: none. Run nothing else meanwhile."
  suite base || return 1
  print "Success: the graphtraj line under $T/base-src-${BASE_COMMIT[1,8]}/src, 'started in the background'."
  print -r -- "next: after B's suite.txt ends with exit=: zsh $THIS GR"
  ;;
GR)
  say "[GR] Main. Read only. Newest G, B and Gt; candidate FAILED/ERROR lines classed known (fails on base B too, 516) or NEW. Dialog: none. <10 s."
  local g=$(cat $OUT/G-latest 2>/dev/null) b=$(cat $OUT/B-latest 2>/dev/null) t=$(cat $OUT/Gt-latest 2>/dev/null) r
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  [[ -n $b && -f $b/suite.txt ]] || { print -r -- "no B result yet (classification uses 516 only); run: zsh $THIS B"; b=; }
  for r in $g $b; do print -r -- "---- $r"; cat $r/run.txt; tail -4 $r/suite.txt; grep -q '^exit=' $r/suite.txt || print "still running (no exit= line yet)"; done
  print -r -- "---- candidate G classification"; classify "$b" $g/suite.txt $g/shards/*(N.)
  [[ -n $t ]] && { print -r -- "---- Gt $t"; tail -2 $t/suite.txt; classify "" $t/suite.txt; }
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line in G or Gt."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS 0|Gt|D|G|B|GR"; return 2 ;;
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
