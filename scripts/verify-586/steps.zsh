#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 586 Main-run steps: GraphTraj's full suite with graftling dev 58778c8 (576 + 578) installed as a WHEEL. The 62
# Claude tests that failed since graftling 576 are fixed test-side (tests/claude_cli_fixture.py answers graftling's
# default-tools probe; three tests follow the accepted 576/578 contracts). No product code changed; no login is used.
# Run one step at a time:  zsh <this file> <STEP>
#   pre         Main. Read only: zsh version; candidate HEAD, base GraphTraj 712957bd and graftling 58778c8 (in
#               <Harness>/graftling) resolvable; TMPDIR outside the Harness; click/PyYAML/websockets present in
#               <Harness>/.venv-runtime; no other pytest running. Dialog: none. No login. <5 s.
#   suite       Main. GraphTraj full suite of HEAD (scripts/run_test_shards.py, 6 shards, --timeout 1500, -rA,
#               background ~25 min) in a venv under <Harness>/tmp/586 with graftling 58778c8 as a WHEEL and GraphTraj
#               editable. pytest's temp root is a fresh directory under TMPDIR=${TMPDIR:-/tmp}, outside the Harness
#               (checked; the step prints it). Dialog: none. No login.
#   SR          Read only: the newest suite's FAILED/ERROR node ids (whole, via scripts/verify-581/suiteids.py, params
#               with spaces included) classed 'known (516)' (Task 516's CURRENT definition, read through its task.yml
#               current_definition) or NEW; writes new-ids.txt and prints the ready-to-paste suite-base command, each
#               id a separate shell-quoted argument, and the --from form. Dialog: none.
#   suite-base  Main, only if SR reports NEW: `zsh <this file> suite-base <id>...` or `... suite-base --from <file>`
#               reruns exactly those ids on base GraphTraj 712957bd (a local clone under <Harness>/tmp/586), then on
#               the candidate (this Worktree's HEAD), both with the graftling 58778c8 wheel; per id: fails on both
#               (pre-existing) | candidate-only | ... Dialog: none. No login.
#   push        Main, ONLY after the user agreed. Pushes HEAD to LUOXIAO92/graphtraj as this Task's branch. Dialog:
#               none expected; git uses your usual GitHub login.
# Order: pre, suite, SR (suite-base only if SR names NEW ids); push separately after the user agrees.
# Credentials: none is needed. Every pytest starts from an ALLOWLIST (launch(): HOME USER LOGNAME SHELL TERM LANG
# LC_ALL LC_CTYPE TMPDIR PATH and the step's own VAR=value); a guard STOPs (exit 97, names only) if any *_API_KEY,
# *_TOKEN, *_BASE_URL or *_AUTH* name is left. Writes: T (venvs, sources, outputs), OUT (copies of SR/suite-base
# results) and pytest's temp roots under TMPDIR only.
# Rehearsal only (Engineer): VERIFY586_T (instead of <Harness>/tmp/586), VERIFY586_OUT, VERIFY586_PYTEST_ARGS (pytest
# args appended after `-- -rA`, e.g. a -k filter), VERIFY586_SUITE_ENV (extra VAR=value for the suite's launch, e.g.
# CLAUDE_FIXTURE_FAIL=1 to make the selected Claude tests fail so SR has NEW ids to print).
emulate -L zsh
setopt pipe_fail no_unset extended_glob
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
STEP=${1:-}
URL=https://github.com/LUOXIAO92/graphtraj.git
BRANCH=agent/586-graphtraj-claude-tests-fail-since-graftling-576
GREPO=$H/graftling                                  # the local graftling repository (read only)
GCOMMIT=58778c83e99f3cff7348d7e60afe0c8d86a9b6c1   # graftling dev (576 + 578 + 581)
GTBASE=712957bdc082a1bf1ad6b41c546bbe84becdcb6d     # GraphTraj dev, this Task's base (unfixed)
HEAD=$(git -C $WT rev-parse HEAD)                   # the candidate
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: click, PyYAML and websockets are copied from here
CONDA=/Users/luoxiao/miniconda3/bin/python3.13
T=${VERIFY586_T:-$H/tmp/586}                        # suite venvs, sources and outputs
OUT=${VERIFY586_OUT:-$H/.graphtraj/core/state/tasks/586-graphtraj-claude-tests-fail-since-graftling-576/realhost}
PYTEST_TMP=${TMPDIR:-/tmp}
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
SUITEIDS=$WT/scripts/verify-581/suiteids.py        # whole node ids, classification, error origins (Task 581)
path=(/opt/homebrew/bin $path)

say() { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
# ALLOWLIST launch: in a subshell every exported name outside ALLOW is unset, then the given VAR=value are exported;
# a guard STOPs (exit 97) if a provider-credential-like name is left. Names only are printed, never values.
ALLOW=(HOME USER LOGNAME SHELL TERM LANG LC_ALL LC_CTYPE TMPDIR PATH)
launch() {  # [VAR=value...] -- command...
  local -a add=(); while (( $# )) && [[ $1 != -- ]]; do add+=$1; shift; done
  (( $# )) && shift
  (
    local n
    for n in ${(k)parameters[(R)*export*]}; do
      (( ${ALLOW[(Ie)$n]} )) || unset $n 2>/dev/null
    done
    for n in $add; do export "$n"; done
    local -a bad=(${(M)${(k)parameters[(R)*export*]}:#(*_API_KEY|*_TOKEN|*_BASE_URL|*_AUTH*)})
    (( $#bad )) && { print -u2 -r -- "STOP: provider credential names in the launch environment: $bad"; exit 97; }
    exec "$@"
  )
}
# Other test runs (their command lines). A ps that cannot list processes is itself reported, never read as "none";
# VERIFY586_NO_PS=1 (Engineer rehearsal in a sandbox without ps) skips the check and says so.
others() {
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1); then
    [[ ${VERIFY586_NO_PS:-} == 1 ]] && { print -u2 -r -- "NOTE: ps cannot list processes here; check skipped (VERIFY586_NO_PS=1, rehearsal)"; return 0; }
    print -r -- "ps cannot list processes here ($listed); run this script in your own terminal"; return 0
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -v grep || true
}
outside() {  # STOP unless TMPDIR is outside the Harness
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
# venv with graftling GCOMMIT as a WHEEL (git archive of <Harness>/graftling, built offline) and GraphTraj editable.
suite_venv() {  # venv graphtraj-checkout
  local V=$1 gt=$2 S=$1-src
  [[ -x $V/bin/python && -f $V/installed ]] && { print -r -- "reusing $V ($(<$V/installed))"; return 0; }
  rm -rf -- $V $S && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  $CONDA -m venv --system-site-packages $V || return 1
  local D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))') m
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    case $m in
      yaml) cp -Rp $RTSP/yaml $RTSP/_yaml(N) $RTSP/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
      *) cp -Rp $RTSP/$m $RTSP/$m-*.dist-info(N) $D/ ;;
    esac || return 1
  done
  local -a pip=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
  $CONDA -m pip wheel $pip -w $S/wheels $S/graftling > /dev/null || return 1
  $V/bin/python -m pip install $pip $S/wheels/graftling-*.whl && $V/bin/python -m pip install $pip -e $gt || return 1
  print -r -- "graftling $GCOMMIT (wheel) + graphtraj $gt (editable)" > $V/installed; print -r -- "$V: $(<$V/installed)"
}
# A fresh pytest temp root under TMPDIR, outside the Harness, with no Harness marker above it; sets RUNTMP.
run_root() {  # label
  outside || return 1
  RUNTMP=${PYTEST_TMP:A}/verify-586-$1-$(date +%Y%m%dT%H%M%S)
  local d=${RUNTMP:h}; while [[ $d != / ]]; do
    [[ -e $d/.graphtraj || -e $d/.agents-control/claude-host.json ]] && { print -r -- "STOP: $d above the pytest temp root holds a Harness marker"; return 1; }
    d=${d:h}; done
  mkdir -p $RUNTMP && print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
}
versions() {  # venv: which graphtraj and graftling it imports (from the pytest temp root, not the checkout)
  (cd $RUNTMP && $1/bin/python -I -c 'import graphtraj, graftling, importlib.metadata as m; d = m.distribution("graftling"); print("graphtraj", graphtraj.__file__, "| graftling", graftling.__version__, graftling.__file__, "| editable:", any(str(f).startswith("__editable__") for f in d.files))')
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Read-only preflight. Dialog: none. No login is needed and none is used. <5 s."
  OK=1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT cat-file -e "$GTBASE^{commit}" 2>/dev/null && pass "base GraphTraj $GTBASE resolvable ($(git -C $WT log --format=%s -1 $GTBASE | cut -c1-70))" || fail "base GraphTraj $GTBASE not in $WT"
  git -C $GREPO cat-file -e "$GCOMMIT^{commit}" 2>/dev/null && pass "graftling $GCOMMIT resolvable in $GREPO" || fail "graftling $GCOMMIT not in $GREPO"
  local dirty=$(git -C $WT status --porcelain -- src tests scripts)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, scripts" || fail "uncommitted changes in $WT: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m; for m in click yaml websockets; do [[ -d $RTSP/$m ]] && pass "$m present in $RTSP" || fail "$m missing in $RTSP"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  local o=$(others); [[ -z $o ]] && pass "no other pytest running" || { fail "another test run is running:"; print -r -- $o; }
  print -r -- "writes: nothing (read only). dialog: none."
  (( OK )) && print -r -- "next: zsh $THIS suite" || print -r -- "next: fix the FAIL lines above, then: zsh $THIS pre"
  (( OK ))
  ;;
suite)
  setopt local_options no_bg_nice
  say "[suite] Main. GraphTraj full suite of HEAD $HEAD (6 shards, --timeout 1500, -rA, background ~25 min). Dialog: none. No login."
  print -r -- "load average: $(sysctl -n vm.loadavg)"
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later: zsh $THIS suite"; print -r -- $o; return 1; }
  local dirty=$(git -C $WT status --porcelain -- src tests)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  run_root suite || return 1
  local V=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $V $WT || return 1
  versions $V || return 1
  local R=$T/suite-${HEAD[1,8]}-$(date +%Y%m%dT%H%M%S); mkdir -p $R
  print -r -- "pytest temp root: $RUNTMP (TMPDIR, outside the Harness) | candidate GraphTraj $HEAD | graftling $GCOMMIT (wheel)" > $R/run.txt
  local extra=(${(Q)${(z)${VERIFY586_PYTEST_ARGS:-}}}) senv=(${(Q)${(z)${VERIFY586_SUITE_ENV:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${(j: :)${(@qq)extra}}" >> $R/run.txt
  (( $#senv )) && print -r -- "REHEARSAL: extra launch environment: $senv" >> $R/run.txt
  cat $R/run.txt
  (cd $WT && launch TMPDIR=$RUNTMP $senv -- $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA $extra \
     > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print -r -- $R > $T/suite-latest
  print -r -- "started in the background at $(date +%T); output: $R/suite.txt (ends with 'exit=N')"
  print -r -- "writes: $T (venv, sources, $R) and $RUNTMP only. dialog: none."
  print -r -- "progress (paste): tail -3 $R/suite.txt; ls -la $R/shards"
  print -r -- "next (paste, after $R/suite.txt ends with exit=): zsh $THIS SR"
  ;;
SR)
  say "[SR] read only: newest suite; FAILED/ERROR node ids classed against 516's current definition. Dialog: none."
  local cur=${${${(M)${(f)"$(<$D516/task.yml)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  local K=$D516/$cur
  print -r -- "516 current definition (task.yml current_definition): $K"
  [[ -n $cur && -f $K ]] || { print -r -- "STOP: cannot read 516's current definition '$K'"; return 1; }
  local g=$(cat $T/suite-latest 2>/dev/null)
  [[ -n $g && -f $g/suite.txt ]] || { print -r -- "no suite result yet; run: zsh $THIS suite"; return 1; }
  cat $g/run.txt; tail -6 $g/suite.txt
  grep -q '^exit=' $g/suite.txt || { print -r -- "suite still running (no exit= line yet); next: zsh $THIS SR (later)"; return 1; }
  # Whole node ids: suiteids.py ends an id at pytest's ' - ' or its matching ']' (file::function if not closed).
  local line t id new=0 any=0; local -a ids=()
  for id in ${(f)"$(python3 -I $SUITEIDS ids $g/suite.txt $g/shards/*(N.))"}; do
    any=1; t=${id%%\[*}
    if grep -qF -- "${t##*::}" $K; then print -r -- "known (516): $id"
    else print -r -- "NEW: $id"; new=1; ids+=$id; fi
  done
  print -l -- $ids > $g/new-ids.txt
  (( any )) || print -r -- "(no FAILED/ERROR lines)"
  # A shard ending other than by test failures (exit 1) is a failure of the run itself; exit 5 (nothing collected)
  # is only expected when a rehearsal filter was given.
  for line in ${(f)"$(grep -E '^ABNORMAL .*: exit [0-9]+' $g/suite.txt)"}; do
    case ${line##*exit } in
      1) ;;
      5) grep -q '^REHEARSAL' $g/run.txt && print -r -- "rehearsal filter, nothing collected: $line" \
           || { print -r -- "ABNORMAL shard: $line"; new=1; } ;;
      *) print -r -- "ABNORMAL shard: $line"; new=1 ;;
    esac
  done
  grep -E '^(=+ )?[0-9]+ (passed|failed)|^[0-9]+ (passed|failed)' $g/shards/*(N.) | sed "s#^$g/shards/##"
  mkdir -p $OUT 2>/dev/null && cp $g/run.txt $g/new-ids.txt $OUT/ 2>/dev/null && cp $g/suite.txt $OUT/suite-${g:t}.txt 2>/dev/null
  print -r -- "SR verdict: $( (( new == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  print -r -- "NEW node ids ($#ids, one per line): $g/new-ids.txt"
  print -r -- "writes: $g/new-ids.txt and copies in $OUT only. dialog: none."
  if (( $#ids )); then
    # Each id its own single-quoted word ((@qq) quotes element by element; joining first made one argument, 583).
    print -r -- "next (paste): zsh ${(qq)THIS} suite-base ${(@qq)ids}"
    print -r -- "or (paste):   zsh ${(qq)THIS} suite-base --from ${(qq)g}/new-ids.txt"
  else
    print -r -- "next: none (no NEW id); report the SR verdict"
  fi
  return $new
  ;;
suite-base)
  # The ids on base (GraphTraj GTBASE), then on the candidate (HEAD), both with the GCOMMIT wheel; same pytest flags,
  # a fresh temp root each; only ids collected on a side run there (pytest stops the whole run on one unknown id).
  setopt local_options no_bg_nice
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then
    [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file '${IDS[2]:-}'; SR writes it (new-ids.txt)"; return 2; }
    ids=(${(f)"$(<${IDS[2]})"})
  else ids=("${(@)IDS}"); fi
  ids=(${ids:#})
  (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>...   (SR prints both)"; return 2; }
  say "[suite-base] Main. $#ids node ids: base (GraphTraj $GTBASE), then candidate (HEAD $HEAD), both with graftling $GCOMMIT (wheel). Dialog: none. No login."
  print -l -- "  id: "${^ids}
  local o=$(others); [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun this command later"; print -r -- $o; return 1; }
  local B=$T/graphtraj-base
  if [[ ! -d $B/.git ]]; then
    rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
      && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1
  fi
  [[ $(git -C $B rev-parse HEAD) == $GTBASE ]] || { print -r -- "STOP: $B is not at $GTBASE"; return 1; }
  print -r -- "base checkout: $B (a git clone; $(git -C $B log --oneline -1)); candidate checkout: $WT ($(git -C $WT log --oneline -1))"
  local VB=$T/venv-base-${GTBASE[1,8]} VC=$T/venv-suite-${GCOMMIT[1,8]}
  suite_venv $VB $B && suite_venv $VC $WT || return 1
  local R=$T/suite-base-$(date +%Y%m%dT%H%M%S); mkdir -p $R || return 1
  print -l -- $ids > $R/ids.txt
  local side dir V rc
  for side dir V in base $B $VB candidate $WT $VC; do
    run_root $side || return 1
    say "$side: pytest in $dir; $(versions $V)"
    (cd $dir && launch TMPDIR=$RUNTMP -- $V/bin/python -m pytest -p no:cacheprovider -q --collect-only ${(u)${ids%%::*}} > $R/$side-collected.txt 2>&1)
    python3 -I $SUITEIDS present $R/$side-collected.txt $R/ids.txt > $R/$side-ids.txt 2> $R/$side-missing.txt
    [[ -s $R/$side-missing.txt ]] && print -r -- "not on $side (not run there): $(tr '\n' ' ' < $R/$side-missing.txt)"
    local -a run=(${(f)"$(<$R/$side-ids.txt)"})
    if (( $#run )); then
      (cd $dir && launch TMPDIR=$RUNTMP -- $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $R/$side.txt 2>&1); rc=$?
    else print -r -- "(no id present on $side)" > $R/$side.txt; rc=5; fi
    print -r -- "$side: pytest exit=$rc, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $R/$side.txt | tail -1) (output: $R/$side.txt)"
    python3 -I $SUITEIDS errors $R/$side.txt > $R/$side-errors.txt
  done
  say "classification (each id: base, then candidate)"
  python3 -I $SUITEIDS classify $R/ids.txt $R/base.txt $R/candidate.txt | tee $R/classification.txt; local fails=${pipestatus[1]}
  mkdir -p $OUT 2>/dev/null && cp -R $R $OUT/ 2>/dev/null
  print -r -- "first E line + raise location per failing test: $R/base-errors.txt and $R/candidate-errors.txt"
  print -r -- "writes: $T (venvs, $B, $R), a copy in $OUT/${R:t} and the pytest temp roots under $PYTEST_TMP only. dialog: none."
  print -r -- "next: report the classification ($R/classification.txt); a candidate-only id is a regression of this Task"
  return $fails
  ;;
push)
  say "[push] Main, ONLY after the user agreed. $HEAD -> $URL $BRANCH. Dialog: none expected (your usual GitHub login)."
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && { pass "already on GitHub"; print -r -- "next: none"; return 0; }
  print -r -- "authors and committers since base: $(git -C $WT log --format='%an <%ae> | %cn <%ce>' $GTBASE..$HEAD | sort -u)"
  git -C $WT push $URL "${HEAD}:refs/heads/${BRANCH}" 2>&1 | tail -3
  [[ $(git ls-remote $URL refs/heads/$BRANCH | cut -f1) == $HEAD ]] && pass "GitHub $BRANCH = $HEAD" || { fail "GitHub $BRANCH is not $HEAD"; return 1; }
  print -r -- "writes: the GitHub branch $BRANCH only. dialog: none. next: none"
  ;;
*) print -r -- "usage: zsh $THIS pre|suite|SR|suite-base --from <file>|<ids>...|push"; return 2 ;;
esac
}
OK=1
IDS=("${(@)argv[2,-1]}")                            # suite-base: the node ids after the step name
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
