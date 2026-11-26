#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 642 Main-run steps: tests/test_tool_name_592.py follows Task 627's Activity.tsx footer (the ALLOWED look-alike
# now pins `activity.agents.length === 1 ? 'agent' : 'agents'`; no regex loosened, no UI change). Candidate = this
# Worktree's HEAD (GraphTraj dev c18b4beb + 642); graftling 0.10.2 (v0.10.2 = 57bca736) from <Harness>/graftling, as a
# WHEEL. Modelled on Task 641's scripts/verify-641/steps.zsh (commit bb11bc1c): only its pre, G, GR, SR and suite-base,
# plus t592. No claude, no gh, no Issue, no network. Production (<Harness>/.venv-runtime) is only read (click, PyYAML,
# websockets copied). graftling is not changed. Nothing is pushed. README.md says what each step proves.
# Run one step at a time, in this order:  zsh <this file> <STEP>
#   pre     Main. zsh, HEAD, base c18b4beb is an ancestor, graftling v0.10.2; no uncommitted src/tests/pyproject or
#           step-file change; TMPDIR outside the Harness. Dialog: none. No login. <5 s.
#   t592    Main. tests/test_tool_name_592.py on HEAD in the suite venv (HEAD editable + the v0.10.2 wheel); its LAST
#           lines are PASS/FAIL and the next command. pytest temp under TMPDIR=${TMPDIR:-/tmp} (outside the Harness).
#           Dialog: none. No login. ~1 min (first run builds the venv).
#   G       Main. Full suite of HEAD + the v0.10.2 wheel (6 shards, scripts/run_test_shards.py); waits for other test
#           runs first, then for its shards; ends by running GR, so its LAST lines are the verdict, counts and next
#           command. pytest temp under TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Dialog: none. No login. ~25-30 min.
#   GR      Main, read only: the newest G record judged (G runs it at its end). Dialog: none. No login.
#   SR      Main, read only: the newest G record classed against 516's CURRENT definition (+ the known start-an-agent
#           id). Dialog: none. No login.
#   suite-base  Main, only for SR's NEW ids: base c18b4beb vs candidate, both with the v0.10.2 wheel. pytest temp under
#           TMPDIR=${TMPDIR:-/tmp} (outside the Harness). Dialog: none. No login.
# Credentials: before any step, every exported credential-class variable (names ending KEY, TOKEN, SECRET(S),
# PASSWORD, CREDENTIAL(S); GIT_CONFIG_KEY_<n> excepted) is unset and its NAME printed. Every started process gets an
# ALLOWLIST environment (clean(): PATH HOME USER TERM TMPDIR LANG and the step's own NAME=value); HOME is T/home, never
# a provider login. No token is read, printed or written anywhere.
# Records: T=<Harness>/tmp/642; copies in the Task's state realhost directory (as 641 does).
# Rehearsal only (Engineer; Main leaves all unset): VERIFY642_T, VERIFY642_OUT, VERIFY642_DEPS, VERIFY642_PYTEST_ARGS,
# VERIFY642_GWAIT, VERIFY642_NO_PS=1. A run with any of them set prints REHEARSAL and is not evidence.
# No zsh special parameter name is used as a variable (path, status, argv, prompt, reply, match, ...).
emulate -L zsh
setopt pipe_fail no_unset extended_glob no_bg_nice
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
THIS=${0:A}
STEP=${1:-}
TASKDIR=642-tool-name-592-follows-627-activity
GREPO=$H/graftling                                  # read only
GCOMMIT=57bca73657d3135a4504904fcc3f1898c2419766    # graftling 0.10.2, tag v0.10.2
GVERSION=0.10.2
GTBASE=c18b4bebd42d9c7801fd5ba26a290d585a021118    # GraphTraj dev, this Task's base
HEAD=$(git -C $WT rev-parse HEAD)
RTSP=$H/.venv-runtime/lib/python3.13/site-packages  # read only: deps are copied from here
DEPS=(${=${VERIFY642_DEPS:-$RTSP}})
CONDA=$HOME/miniconda3/bin/python3.13               # builds the wheels and venvs
T=${VERIFY642_T:-$H/tmp/642}                        # suite venvs, sources and records
OUT=${VERIFY642_OUT:-$H/.graphtraj/core/state/tasks/$TASKDIR/realhost}
HOMEDIR=$T/home
VENV=$T/gvenv-642
SUITEIDS=$WT/scripts/verify-581/suiteids.py
D516=$H/.graphtraj/core/state/tasks/516-low-priority-flaky-tests
KNOWN_EXTRA=("tests/test_agents_discovery_intents.py::test_intent_queries_find_create[start an agent]")   # 611; base too
PYTEST_TMP=${TMPDIR:-/tmp}
BASEPATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
PIP=(-q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation)
REHEARSAL=$(print -r -- ${(k)parameters[(I)VERIFY642_*]})

say()  { print -r -- "== $*"; }
pass() { print -r -- "PASS: $*"; }
fail() { print -r -- "FAIL: $*"; OK=0; }
# Allowlist environment: PATH HOME USER TERM TMPDIR LANG and the given NAME=value words, then the command.
clean() { env -i PATH=$VENV/bin:$BASEPATH HOME=$HOMEDIR USER=${USER:-user} TERM=${TERM:-xterm} \
            TMPDIR=$PYTEST_TMP LANG=en_US.UTF-8 "$@"; }
outside() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print -r -- "STOP: TMPDIR $PYTEST_TMP is inside the Harness; run with TMPDIR=/tmp zsh $THIS $STEP"; return 1 ;; esac
}
copy_deps() {  # venv: click, PyYAML, websockets copied from production (read only) when the venv lacks them
  local V=$1 D m s found
  D=$($V/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  for m in click yaml websockets; do
    $V/bin/python -I -c "import $m" 2>/dev/null && continue
    found=0
    for s in $DEPS; do
      [[ -d $s/$m ]] || continue
      case $m in
        yaml) cp -Rp $s/yaml $s/_yaml(N) $s/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $D/ ;;
        *) cp -Rp $s/$m $s/$m-*.dist-info(N) $D/ ;;
      esac && { found=1; break; }
    done
    (( found )) || { print -r -- "STOP: $m not found in ${DEPS[*]}"; return 1; }
  done
}
graftling_wheel() {  # $1 dir: graftling v0.10.2 built offline from git archive into $1/wheels
  local S=$1
  rm -rf -- $S/graftling && mkdir -p $S/graftling $S/wheels || return 1
  git -C $GREPO archive $GCOMMIT | tar -x -C $S/graftling || { print -r -- "STOP: graftling $GCOMMIT not found"; return 1; }
  clean $CONDA -m pip wheel $PIP -w $S/wheels $S/graftling > /dev/null
}
other_suites() {  # exit 2 when ps cannot list (never read as "none")
  local listed
  if ! listed=$(ps -axww -o pid=,command= 2>&1) || [[ -z $listed ]]; then
    [[ ${VERIFY642_NO_PS:-} == 1 ]] && { print -u2 -r -- "REHEARSAL: ps cannot list processes here; other-run check skipped (VERIFY642_NO_PS=1)"; return 0; }
    print -r -- "ps cannot list processes"; return 2
  fi
  print -r -- $listed | grep -E 'run_test_shards|-m pytest' | grep -vE 'grep -E' ; return 0
}
cdef_516() {  # Task 516's CURRENT definition file, through its task.yml current_definition
  local c=${${${(M)${(f)"$(cat $D516/task.yml 2>/dev/null)"}:#current_definition: *}#current_definition: }//[\'\"]/}
  print -r -- ${c:+$D516/$c}
}
grec() { print -r -- ${$(print -l $T/G-*(N/om[1])):-$T/G-none}; }
sr_classify() {  # $1 = G record; sets SR_NEW SR_ANY SR_IDS; writes <record>/new-ids.txt
  local rec=$1 line t id K=$(cdef_516); SR_NEW=0; SR_ANY=0; SR_IDS=()
  print -r -- "516 current definition (task.yml current_definition): ${K:-unreadable}"
  [[ -f $K ]] || { print -r -- "STOP: cannot read 516's current definition"; SR_NEW=1; return 1; }
  local -a logs=($rec/shards/*.log(N.)); (( $#logs )) || logs=($rec/suite.txt)
  for id in ${(f)"$(clean $CONDA -I $SUITEIDS ids $logs)"}; do
    SR_ANY=1; t=${id%%\[*}
    if (( ${KNOWN_EXTRA[(Ie)$id]} )); then print -r -- "  known (611, fails on base too; graftling's models description says 'starts no Agent'): $id"
    elif grep -qF -- "${t##*::}" $K; then print -r -- "  known (516): $id"
    else print -r -- "  NEW: $id"; SR_NEW=1; SR_IDS+=$id; fi
  done
  (( SR_ANY )) || print -r -- "  (no FAILED/ERROR lines)"
  for line in ${(f)"$(grep -E '^ABNORMAL ' $rec/suite.txt)"}; do
    case $line in
      *': exit 1') ;;
      *': exit 5') grep -q '^REHEARSAL' $rec/run.txt && print -r -- "  rehearsal filter, nothing collected: $line" || { print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1; } ;;
      *) print -r -- "  ABNORMAL shard (NEW): $line"; SR_NEW=1 ;;
    esac
  done
  print -l -- $SR_IDS > $rec/new-ids.txt
}
g_venv() {  # $1 venv, $2 checkout: graftling v0.10.2 WHEEL + the checkout editable (the suite needs its metadata)
  local V=$1 S=$1-src
  [[ $(cat $V/installed 2>/dev/null) == "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" ]] && { print -r -- "reusing $V"; return 0; }
  rm -rf -- $V $S && mkdir -p $S || return 1
  graftling_wheel $S || return 1
  clean $CONDA -m venv --system-site-packages $V && copy_deps $V || return 1
  clean $V/bin/python -m pip install $PIP $S/wheels/graftling-*.whl && clean $V/bin/python -m pip install $PIP -e $2 > /dev/null || return 1
  print -r -- "$GCOMMIT $2 $(git -C $2 rev-parse HEAD)" > $V/installed
}

run_step() {
case $STEP in
pre)
  say "[pre] Main. Preflight, read only (creates $T and $OUT). Dialog: none. No login."
  OK=1
  mkdir -p $T $HOMEDIR $OUT || return 1
  print -r -- "zsh $ZSH_VERSION runs $THIS"
  print -r -- "candidate HEAD $HEAD ($(git -C $WT log --format=%s -1 | cut -c1-90))"
  git -C $WT merge-base --is-ancestor $GTBASE $HEAD 2>/dev/null && pass "base GraphTraj $GTBASE is an ancestor of HEAD" || fail "base $GTBASE is not an ancestor of HEAD"
  [[ $(git -C $GREPO rev-parse -q --verify 'v0.10.2^{commit}' 2>/dev/null) == $GCOMMIT ]] \
    && pass "graftling v0.10.2 = $GCOMMIT in $GREPO (wheel source)" || fail "graftling v0.10.2 is not $GCOMMIT in $GREPO"
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml scripts/verify-642/steps.zsh)
  [[ -z $dirty ]] && pass "no uncommitted change in src, tests, pyproject.toml, the step file" || fail "uncommitted changes: $dirty"
  outside && pass "TMPDIR=$PYTEST_TMP is outside the Harness $H" || OK=0
  local m s d; for m in click yaml websockets; do s=0; for d in $DEPS; do [[ -d $d/$m ]] && s=1; done
    (( s )) && pass "$m present in ${DEPS[*]}" || fail "$m missing in ${DEPS[*]}"; done
  [[ -x $CONDA ]] && pass "$CONDA: $($CONDA --version 2>&1)" || fail "$CONDA missing"
  print -r -- "writes: $T and $OUT only. No network. dialog: none."
  (( OK )) && print -r -- "RESULT 642 pre: PASS" || print -r -- "RESULT 642 pre: FAIL (lines above)"
  (( OK )) && print -r -- "next (paste): zsh $THIS t592" || print -r -- "next: report the FAIL lines"
  (( OK ))
  ;;
t592)
  say "[t592] Main. tests/test_tool_name_592.py on HEAD $HEAD + graftling $GVERSION (wheel). pytest temp under TMPDIR=$PYTEST_TMP (outside the Harness). Dialog: none. No login."
  outside || return 1
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  mkdir -p $T $HOMEDIR || return 1
  g_venv $VENV $WT || { print -r -- "STOP: suite venv"; return 1; }
  local O=$T/t592-$(date +%Y%m%dT%H%M%S) RUNTMP=${PYTEST_TMP:A}/verify-642-t592-$(date +%Y%m%dT%H%M%S) rc
  mkdir -p $O $RUNTMP || return 1
  (cd $WT && clean TMPDIR=$RUNTMP $VENV/bin/python -m pytest -p no:cacheprovider -q -rA tests/test_tool_name_592.py > $O/pytest.txt 2>&1 < /dev/null); rc=$?
  print -r -- "exit=$rc" >> $O/pytest.txt
  cat $O/pytest.txt; cp -R $O $OUT/ 2>/dev/null
  print -r -- ""
  print -r -- "RESULT 642 t592: $( (( rc == 0 )) && print PASS || print FAIL) | $(grep -E '^=*.* (passed|failed)|^[0-9]+ (passed|failed)' $O/pytest.txt | tail -1) | record: $O$([[ -n $REHEARSAL ]] && print ' | REHEARSAL (not evidence)')"
  (( rc == 0 )) && print -r -- "next (paste): zsh $THIS G" || print -r -- "next: report the FAIL (record $O/pytest.txt)"
  return $rc
  ;;
G)
  say "[G] Main. Full GraphTraj suite: HEAD $HEAD (editable) + graftling $GVERSION ($GCOMMIT wheel), 6 shards. This process waits for any other test run, then for its shards, then judges; its LAST lines are the verdict, counts and next command. pytest temp under TMPDIR=$PYTEST_TMP (outside the Harness). Dialog: none. No login. ~25-30 min."
  outside || return 1
  local dirty=$(git -C $WT status --porcelain -- src tests pyproject.toml)
  [[ -z $dirty ]] || { print -r -- "STOP: uncommitted changes in $WT: $dirty"; return 1; }
  local busy; busy=$(other_suites) || { print -r -- "STOP: $busy (nothing started)"; return 1; }
  local O=$T/G-$(date +%Y%m%dT%H%M%S) RUNTMP=${PYTEST_TMP:A}/verify-642-G-$(date +%Y%m%dT%H%M%S)
  mkdir -p $T $HOMEDIR $O $RUNTMP || return 1
  g_venv $VENV $WT || { print -r -- "STOP: suite venv"; return 1; }
  { print -r -- "pytest temp root: $RUNTMP (TMPDIR=$PYTEST_TMP, outside the Harness)"
    print -r -- "launch environment: PATH HOME USER TERM TMPDIR LANG only (clean(); no provider credential)"
    print -r -- "candidate: $HEAD | graftling wheel from git archive $GCOMMIT (v$GVERSION)"
    (cd $RUNTMP && clean $VENV/bin/python -I -c 'import importlib.metadata as m; print("test interpreter:", " | ".join(f"{n} {m.version(n)}" for n in ("click", "PyYAML", "websockets", "pytest", "graftling", "graphtraj")))')
    [[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not evidence): $REHEARSAL"; } > $O/run.txt
  local -a extra=(${(Q)${(z)${VERIFY642_PYTEST_ARGS:-}}})
  (( $#extra )) && print -r -- "REHEARSAL: extra pytest args after -- -rA: ${extra[*]}" >> $O/run.txt
  cat $O/run.txt; print -r -- "record: $O"
  while true; do
    busy=$(other_suites) || { print -r -- "STOP: ps failed; G did not start"; return 1; }
    [[ -z $busy ]] && break
    print -r -- "$(date +%T) waiting for another test run: $(print -r -- $busy | awk '{print $1}' | xargs)" | tee -a $O/wait.txt; sleep ${VERIFY642_GWAIT:-60}
  done
  print -r -- "$(date +%T) started (6 shards; this step waits for them)" | tee -a $O/wait.txt
  (cd $WT && clean TMPDIR=$RUNTMP $VENV/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $O/shards -- -rA $extra \
     > $O/suite.txt 2>&1 < /dev/null)
  print "exit=$?" >> $O/suite.txt; print -r -- "$(date +%T) ended: $(tail -1 $O/suite.txt)" | tee -a $O/wait.txt
  STEP=GR; run_step; return $?
  ;;
GR)
  say "[GR] read only: the newest G record judged (G runs this at its end; Main may rerun it). Dialog: none. No login."
  local rec=$(grec); print -r -- "G record: $rec"
  [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "RESULT 642 G: NOT ENDED (no exit= line in $rec/suite.txt)"; return 1; }
  sed 's/^/  run.txt: /' $rec/run.txt
  local tot=$(grep -hE '^=*.* (passed|failed)' $rec/shards/*(N.) | sed "s#^#  #") ex=$(sed -n 's/^exit=//p' $rec/suite.txt | tail -1)
  print -r -- "shard totals:"; print -r -- $tot
  sr_classify $rec
  local rf=0; grep -q '^REHEARSAL' $rec/run.txt && rf=1
  local verdict=FAIL; (( SR_NEW == 0 )) && [[ $ex == 0 || ( $ex == 1 && ( $SR_ANY == 1 || $rf == 1 ) ) ]] && verdict=PASS
  cp -R $rec $OUT/ 2>/dev/null
  local kn=$(sr_classify $rec | grep -c '^  known') nw=$#SR_IDS
  print -r -- ""
  print -r -- "RESULT 642 G: $verdict | exit $ex | known non-blocking ids: $kn | NEW ids: $nw$( (( rf )) && print ' | REHEARSAL (not evidence)')"
  if [[ $verdict == PASS ]]; then print -r -- "next: report RESULT 642 G (record $rec)"
  else print -r -- "next (paste): zsh $THIS SR"; return 1; fi
  ;;
SR)
  say "[SR] Main, read only: the newest G record's FAILED/ERROR ids and ABNORMAL shards against 516's current definition. Dialog: none. No login."
  local rec=$(grec); [[ -f $rec/suite.txt ]] && grep -q '^exit=' $rec/suite.txt || { print -r -- "no ended G record ($rec)"; return 1; }
  tail -4 $rec/suite.txt; sr_classify $rec
  print -r -- "SR verdict: $( (( SR_NEW == 0 )) && print 'PASS (no NEW failure)' || print 'FAIL (NEW lines above)')"
  if (( $#SR_IDS )); then print -r -- "next (paste): zsh ${(qq)THIS} suite-base --from ${(qq)rec}/new-ids.txt"
  else print -r -- "next: none for suite-base (no NEW id)"; fi
  return $SR_NEW
  ;;
suite-base)
  local -a ids
  if [[ ${IDS[1]:-} == --from ]]; then [[ -f ${IDS[2]:-} ]] || { print -r -- "STOP: no id file"; return 2; }; ids=(${(f)"$(<${IDS[2]})"}); else ids=("${(@)IDS}"); fi
  ids=(${ids:#}); (( $#ids )) || { print -r -- "usage: zsh $THIS suite-base --from <ids file> | <node id>..."; return 2; }
  say "[suite-base] Main, only for SR's NEW ids ($#ids): base GraphTraj $GTBASE vs candidate HEAD $HEAD, both with graftling $GVERSION (wheel). pytest temp under TMPDIR (outside the Harness). Dialog: none. No login."
  outside || return 1
  local o; o=$(other_suites) || { print -r -- "STOP: $o"; return 1; }; [[ -z $o ]] || { print -r -- "STOP: another test run is running; rerun later"; return 1; }
  mkdir -p $T $HOMEDIR || return 1
  local B=$T/graphtraj-base VB=$T/sbvenv-${GTBASE[1,8]} VC=$VENV
  if [[ ! -d $B/.git ]]; then rm -rf -- $B && git clone -q --no-checkout $(git -C $WT rev-parse --path-format=absolute --git-common-dir) $B \
     && git -C $B -c advice.detachedHead=false checkout -q $GTBASE || return 1; fi
  g_venv $VB $B && g_venv $VC $WT || return 1
  local RS=$T/suite-base-$(date +%Y%m%dT%H%M%S) side dir V src RUNTMP f; local -a files run; mkdir -p $RS; print -l -- $ids > $RS/ids.txt
  for side dir V in base $B $VB candidate $WT $VC; do
    RUNTMP=${PYTEST_TMP:A}/verify-642-sb-$side-$(date +%Y%m%dT%H%M%S); mkdir -p $RUNTMP
    print -r -- "$side: pytest in $dir | temp $RUNTMP"
    files=(); for f in ${(u)${ids%%::*}}; do [[ -e $dir/$f ]] && files+=$f; done   # a file absent on a side is not collected there
    if (( $#files )); then (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q --collect-only $files > $RS/$side-collected.txt 2>&1)
    else : > $RS/$side-collected.txt; fi
    clean $CONDA -I $SUITEIDS present $RS/$side-collected.txt $RS/ids.txt > $RS/$side-ids.txt 2> $RS/$side-missing.txt
    run=(${(f)"$(<$RS/$side-ids.txt)"}); run=(${run:#})
    if (( $#run )); then (cd $dir && clean TMPDIR=$RUNTMP $V/bin/python -m pytest -p no:cacheprovider -q -rA "${run[@]}" > $RS/$side.txt 2>&1); src=$?
    else print -r -- "(no id present on $side)" > $RS/$side.txt; src=5; fi
    print -r -- "$side: pytest exit=$src, $(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' $RS/$side.txt | tail -1) ($RS/$side.txt)"
  done
  clean $CONDA -I $SUITEIDS classify $RS/ids.txt $RS/base.txt $RS/candidate.txt | tee $RS/classification.txt; local fails=${pipestatus[1]}
  cp -R $RS $OUT/ 2>/dev/null
  print -r -- ""; print -r -- "RESULT 642 suite-base: $( (( fails == 0 )) && print 'PASS (no candidate-only failure)' || print 'FAIL (classification above)') | ids: $#ids | record: $RS"
  print -r -- "next: report the classification; a candidate-only id is a regression of this Task"
  return $fails
  ;;
*) print -r -- "usage: zsh $THIS pre|t592|G|GR|SR|suite-base --from <file>|<ids>..."; return 2 ;;
esac
}

[[ -d $H/.graphtraj || -n $REHEARSAL ]] || { print "STOP: $H is not the Harness root"; exit 1; }
scrub() {  # unset every exported credential-class name; print the names removed
  local k u part; local -a gone=()
  for k in ${(k)parameters[(R)*export*]}; do
    u=${(U)k}; [[ $u == GIT_CONFIG_KEY_<-> ]] && continue
    for part in ${(s:_:)u}; do
      [[ $part == *(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS) ]] && { gone+=$k; unset $k; break; }
    done
  done
  print -r -- "credential scrub: removed from this script's environment (names only): ${gone:-none}"
}
scrub
[[ -n $REHEARSAL ]] && print -r -- "REHEARSAL (not acceptance evidence): $REHEARSAL"
OK=1
IDS=("${(@)@[2,-1]}")
mkdir -p $OUT 2>/dev/null
run_step; rc=$?
print -r -- "STEP-END $STEP rc=$rc"
exit $rc
