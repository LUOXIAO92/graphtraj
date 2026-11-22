#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 565 Main-run steps (modelled on verify-563 / verify-531 G and GR). Run one step at a time:  zsh <this file> <STEP>
#   pre   Main. Preflight: shell, paths, graftling commit, TMPDIR outside the Harness, 516's current definition,
#         clean candidate. Dialog: none. <10 s.
#   C     Main. The Pi collection-entry test file plus the other collector tests in two venvs under <Harness>/tmp/565:
#         c821 (Miniconda base click 8.2.1) and c850 (production .venv-runtime's click 8.5.0, copied read only).
#         Prints click.__version__ of each and PASS/FAIL per version. Also red before green: the same test file of
#         base BASE (git archive, its own pyproject pythonpath=src, so its own collector.py) under c821 must FAIL.
#         Dialog: none. ~1 min.
#   G     Main. GraphTraj full suite of this Worktree's HEAD (6 shards, background, ~25 min) in a venv with the
#         graftling wheel built from git archive of <Harness>/graftling at GCOMMIT (v0.6.3 = production's) and
#         production's click 8.5.0 (as 560's accepted G); `zsh <this file> G 821` uses Miniconda's click 8.2.1 instead.
#         VERIFY565_PYTEST_ARGS='<args>' only appends pytest args after `-- -rA` (e.g. '-k <filter>' for a rehearsal).
#   GR    Main. Read only: newest G; every FAILED/ERROR line classed known (560's accepted G on production's pair, or
#         516's CURRENT definition read through 516's task.yml current_definition) or NEW. <10 s.
# No step raises a native review dialog. Production is only read. Venvs under <Harness>/tmp/565; step output under OUT.
# VERIFY565_T / VERIFY565_OUT are for the Engineer's rehearsal only.
emulate -L zsh
setopt pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=${VERIFY565_T:-$H/tmp/565}
OUT=${VERIFY565_OUT:-$H/.graphtraj/core/state/tasks/565-pi-collector-stdin-eof-under-click-8-2/realhost}
G=$H/graftling
# graftling v0.6.3 = ef7c37db: what production uses (560: scripts/adopt-560/README.md "graftling 0.6.3 (v0.6.3 =
# ef7c37db)"; .venv-runtime's graftling-0.6.3 was installed from 560's wheels-8949caff built from it). From 0.6.3 the
# wheel builds from the archive ROOT.
GCOMMIT=ef7c37db15f4e6318fd5b6bf5bd79321b876eac5
BASE=4c701316                                       # GraphTraj dev this Task branched from (the old loop)
SD=${0:A:h}
THIS=${0:A}
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
STEP=${1:-}
GCLICK=${2:-850}
PYTEST_TMP=${TMPDIR:-/tmp}
TESTS=(tests/test_pi_attachment_private_paths.py tests/test_pi_sessions.py tests/test_pi_extension_command.py)
# 560's G on production's pair (8949caff + v0.6.3, click 8.5.0); 560 is integrated, so this G is accepted.
KNOWN560=$H/.graphtraj/core/state/tasks/560-graftling-0-6-3-release-and-production-adoption/adoption/G-8949caff-20261122T214834/suite.txt
# 516's CURRENT definition, read through its task.yml.
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
purelib() { $1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))'; }
copy_deps() {  # yaml, websockets from production into venv $1 when the base Python lacks them (read only)
  local D=$(purelib $1) m
  for m in yaml websockets; do
    $1/bin/python -I -c "import $m" 2>/dev/null && continue
    print -r -- "$m: copied read only from $RT"
    case $m in
      yaml) cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RT/$m $RT/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
}
wheel() {  # sets WHL: graftling wheel built from git archive GCOMMIT (archive root)
  local GS=${GCOMMIT[1,8]}; local SRC=$T/graftling-$GS N=$T/wheels-gl-$GS
  WHL=($N/graftling-*.whl(N))
  (( $#WHL )) && { WHL=$WHL[1]; print -r -- "reusing $WHL"; return 0; }
  git -C $G cat-file -e $GCOMMIT^{commit} || { print "STOP: graftling $GCOMMIT is not in $G"; return 1; }
  rm -rf $SRC $N && mkdir -p $SRC && git -C $G archive $GCOMMIT | tar -x -C $SRC || { print "STOP: cannot extract graftling"; return 1; }
  $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
    -w $N $SRC >/dev/null || return 1
  WHL=($N/graftling-*.whl(N)); WHL=${WHL[1]:-}
  [[ -f $WHL ]] || { print "STOP: no graftling wheel in $N"; return 1; }
}
# venv $1 (c821: Miniconda's click; c850: production's click copied in), graftling wheel, checkout $2 (default this
# Worktree) editable; $3 prefixes the venv name. Sets V.
mkvenv() {
  local CO=${2:-$WT}
  V=$T/venv-${3:-}$1-gl-${GCOMMIT[1,8]}
  if [[ -x $V/bin/python && -f $V/installed ]]; then print "reusing $V"
  else
    local WHL; wheel || return 1
    rm -rf $V && $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
    if [[ $1 == c850 ]]; then
      print -r -- "click: copied read only from $RT"
      cp -Rp $RT/click $RT/click-*.dist-info(N) $(purelib $V)/ || return 1
    fi
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $WHL || return 1
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $CO 2>&1 | grep -vi cache
    print -r -- $GCOMMIT > $V/installed
  fi
}
versions() {  # interpreter, click, graftling of venv $1, run from a neutral directory
  (cd $PYTEST_TMP && $1/bin/python -I -W ignore::DeprecationWarning -c 'import sys, click, graftling
print("python", sys.executable, "| click.__version__", click.__version__, click.__file__)
print("graftling", graftling.__version__, graftling.__file__)')
}
new_runtmp() {  # a new pytest temp root under $PYTEST_TMP, outside the Harness, no Harness marker above. Sets RUNTMP.
  check_tmp || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-565-$1-$(date +%Y%m%dT%H%M%S)
  [[ -e $RUNTMP ]] && { print "STOP: $RUNTMP exists; run again in a second"; return 1; }
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print "STOP: $d (above the pytest temp root) holds a Harness marker; set TMPDIR elsewhere"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP
  print -r -- "pytest temp root (new for this run; outside the Harness, no Harness marker above): $RUNTMP"
}
guard() {
  local dirty=$(git -C $WT status --porcelain -- src tests plugins)
  print "uncommitted in src/tests/plugins: ${dirty:-none}"; [[ -z $dirty ]] || { print "STOP: uncommitted changes in $WT"; return 1; }
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  return 0
}
classify() {  # FAILED/ERROR lines of files $@ as known (560's accepted G, 516's current definition) or NEW
  local line t any=0
  local k560=(${(f)"$(grep -h -E '^(FAILED|ERROR) ' $KNOWN560 2>/dev/null | sed -E 's/ - .*//' | sort -u)"})
  for line in ${(f)"$(grep -h -E '^(FAILED|ERROR) ' $@ 2>/dev/null | sed -E 's/ - .*//' | sort -u)"}; do
    any=1; t=${line#* }
    if (( ${k560[(Ie)$line]} )); then
      print -r -- "known (560 accepted G, production pair): $line"
    elif grep -qF -- "${${t%%\[*}##*::}" $KNOWN516 2>/dev/null; then print -r -- "known (516): $line"
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
  [[ -x $CONDA ]] && print -r -- "Miniconda: $CONDA" || { print "STOP: $CONDA missing"; return 1; }
  [[ -d $RT/click ]] && print -r -- "production click (read only): $(print $RT/click-*.dist-info(N:t))" || { print "STOP: $RT/click missing"; return 1; }
  print -r -- "516 current definition (from task.yml): $KNOWN516"; [[ -f $KNOWN516 ]] || { print "STOP: 516 current definition missing"; return 1; }
  [[ -f $KNOWN560 ]] && print -r -- "560 accepted G (known reference): $KNOWN560" || { print "STOP: 560 G record missing"; return 1; }
  git -C $G cat-file -e $GCOMMIT^{commit} && print -r -- "graftling $GCOMMIT ($(git -C $G describe --tags --exact-match $GCOMMIT 2>/dev/null)) present in $G" || { print "STOP: graftling commit missing"; return 1; }
  git -C $WT cat-file -e $BASE^{commit} || { print "STOP: base $BASE missing"; return 1; }
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) | base $BASE"
  local dirty=$(git -C $WT status --porcelain -- src tests plugins scripts)
  print "uncommitted in src/tests/plugins/scripts: ${dirty:-none}"
  print "Success: 'pytest temp: ... outside the Harness', the 516 path ends in definitions/<time>.md, 'uncommitted ...: none'."
  print -r -- "next: zsh $THIS C"
  ;;
C)
  say "[C] Main. Collector tests under click 8.2.1 (Miniconda) and 8.5.0 (production), and base $BASE under 8.2.1. Dialog: none. ~1 min."
  guard || return 1
  local RUNTMP V v rc res=() B=$T/base-$BASE
  new_runtmp C || return 1
  print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT"
  for v in c821 c850; do
    say "$v: venv"
    mkvenv $v || return 1
    versions $V || return 1
    say "$v: (cd $WT && $V/bin/python -m pytest -p no:cacheprovider -q $TESTS)"
    (cd $WT && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q $TESTS 2>&1 | tail -15); rc=$?
    (( rc == 0 )) && res+=("PASS: candidate $v ($(versions $V | head -1 | awk '{print $5}'))") || res+=("FAIL: candidate $v rc=$rc")
  done
  say "red before green: base $BASE (old loop) test file under c821; its pyproject pythonpath=src imports its own src"
  rm -rf $B && mkdir -p $B && git -C $WT archive $BASE | tar -x -C $B || { print "STOP: cannot extract base"; return 1; }
  mkvenv c821 $B base- || return 1
  versions $V || return 1
  print -r -- "base collector loop: $(grep -n 'for line in sys.stdin' $B/src/graphtraj/runtimes/pi/collector.py)"
  local o; o=$(cd $B && TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rf tests/test_pi_attachment_private_paths.py 2>&1); rc=$?
  print -l -- ${(M)${(f)o}:#((FAILED|ERROR)*|<->\ (passed|failed)*|*Aborted*)}
  if (( rc != 0 )) && [[ $o == *'FAILED tests/test_pi_attachment_private_paths.py::test_graphtraj_collection_entry_protects_its_directory_and_declares_it'* && $o == *'1 failed'* ]]
  then res+=("PASS: base $BASE fails under c821 only in the collection-entry test (red before green; rc=$rc)")
  else res+=("FAIL: base $BASE under c821 did not fail as expected (rc=$rc)"); fi
  say "results"; print -l -- $res
  [[ ${(M)res:#FAIL*} == "" ]] && print "RESULT: PASS" || print "RESULT: FAIL"
  print "Success: two 'click.__version__' lines (8.2.1 and 8.5.0), 'PASS: candidate c821', 'PASS: candidate c850', 'PASS: base ... fails', 'RESULT: PASS'."
  print -r -- "next: zsh $THIS G  (background ~25 min; then zsh $THIS GR)"
  [[ ${(M)res:#FAIL*} == "" ]]
  ;;
G)
  setopt local_options no_bg_nice
  say "[G] Main. GraphTraj full suite of the Worktree HEAD (6 shards, --timeout 1500, -rA, background ~25 min), click c$GCLICK. Dialog: none. Run nothing else meanwhile."
  [[ $GCLICK == (821|850) ]] || { print "usage: zsh $THIS G [821|850]"; return 2; }
  quiet || return 1
  guard || return 1
  local V RUNTMP; new_runtmp G || return 1
  mkvenv c$GCLICK || return 1
  (cd $RUNTMP && $V/bin/python -I -W ignore::DeprecationWarning -c 'import graphtraj, graftling, click, pytest; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__version__, graftling.__file__, "| click", click.__version__, "| pytest", pytest.__version__)') || return 1
  local R=$OUT/G-$(git -C $WT rev-parse --short HEAD)-c$GCLICK-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  { print -r -- "pytest temp root: $RUNTMP"; print -r -- "candidate: $(git -C $WT rev-parse HEAD) | graftling wheel from git archive $GCOMMIT (v0.6.3)"; versions $V; } | tee $R/run.txt
  local extra=(${(Q)${(z)${VERIFY565_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: $extra (same shard entry; whole suite collected)" | tee -a $R/run.txt
  (cd $WT && TMPDIR=$RUNTMP $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $OUT/G-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (last line 'exit=N' when it ends)"
  print "Success: the graphtraj line under $WT/src, 'graftling 0.6.3 ...', 'click 8.5.0' (or 8.2.1 with '821'), 'started in the background'."
  print -r -- "next (after G ends): zsh $THIS GR"
  ;;
GR)
  say "[GR] Main. Read only. Newest G; FAILED/ERROR lines classed known (560 accepted G, 516 current definition) or NEW. <10 s."
  check_tmp
  print -r -- "516 current definition: $KNOWN516"; print -r -- "560 accepted G: $KNOWN560"
  local g=$(cat $OUT/G-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no G result yet; run: zsh $THIS G"; return 0; }
  print -r -- "---- G $g"; cat $g/run.txt; tail -4 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || print "G still running (no exit= line yet)"
  classify $g/suite.txt $g/shards/*(N.)
  print "Success: G 'exit=0' or only 'known' lines; no 'NEW' line."
  print -r -- "next: report $OUT/GR.txt to the Leader"
  ;;
*) print -r -- "usage: zsh $THIS pre|C|G [821|850]|GR" ; return 2 ;;
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
