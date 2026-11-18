#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 523 steps: cleanup refused integrated Tasks 519/520 as worktree-busy although every member had ended.
#   zsh scripts/verify-523/steps.zsh <STEP>        (Main, from this Task's Worktree)
# Order: 0 -> D -> T -> F ; C only after production adopts the candidate.
#   0  preflight: interpreters, candidate and base commits, 517/519/520 records present. Dialog: none.
#   D  read-only diagnosis of production 519/520 (and 517) Session records: cleanup's busy judgement with the base
#      code and with the candidate, and the names under runner/sessions that no alias can take. No cleanup, no write
#      to any record, no signal (only os.kill(pid, 0) existence probes). Dialog: none.
#   T  focused pytest (tests/test_agent_runner_cleanup.py) in a test venv. Dialog: none.
#   F  full pytest in the same venv (about 73 min single process). Dialog: none.
#   C  AFTER PRODUCTION ADOPTION ONLY: prints the public cleanup calls for 519 and 520 and the expected observable.
# Test venvs, old source and run outputs are under BASE=/private/tmp/graphtraj-523 (outside the Harness); pytest's
# TMPDIR is ${TMPDIR:-/tmp}, also outside the Harness. Production .venv-runtime and runner/state are read only.
emulate -L zsh
setopt err_return pipe_fail no_unset
SD=${0:A:h}; THIS=${0:A}
WT=$(git -C $SD rev-parse --show-toplevel)             # this Task Worktree (the candidate)
H=${WT:h:h:h:h}                                        # <Harness>
GDEV=$H/.graphtraj/core/worktrees/graftling-dev        # graftling Integration Worktree (read only: git archive)
GCOMMIT=a51e1004a0fe77fe492681faa2f278d80b3d725e        # graftling 0.6.0, as production and 520
OLD=595d4dfa19c56951978d3827f70e8c2e1ffb7b83            # dev when 523 started: the code that refused 519/520
# VERIFY523_* are set only by a rehearsal (scratch BASE and runner); the defaults are the real paths.
BASE=${VERIFY523_BASE:-/private/tmp/graphtraj-523}
RUNNER=${VERIFY523_RUNNER:-$H/.graphtraj/core/runner}  # read only
STATE=${VERIFY523_STATE:-$H/.graphtraj/core/state}     # read only
VT=$BASE/venv-test; OUT=$BASE/runs
CONDA=$HOME/miniconda3/bin/python3.13
RTPY=$H/.venv-runtime/bin/python                       # production graftling + deps, read only (python -I -B)
RT=$H/.venv-runtime/lib/python3.13/site-packages       # read only: yaml, websockets, click (no PyPI on this host)
TASKS=(519 520)
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}
FOCUSED=tests/test_agent_runner_cleanup.py

say() { print -r -- "== $*"; }
candidate() { git -C $WT rev-parse HEAD; }
begin() { D=$OUT/$1-$(date +%Y%m%dT%H%M%S); mkdir -p $D; print -r -- "candidate $(candidate) base $OLD step $1" > $D/run.txt
  print -r -- "run records: $D"; }
deps() {  # $1 venv: PyYAML, click and websockets from production's site-packages (copied, never changed there)
  local SP=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) $RT/websockets $RT/websockets-*.dist-info(N) \
    $RT/click $RT/click-*.dist-info(N) $SP/
}
test_venv() {  # conda (pytest) + graftling at GCOMMIT + this Worktree editable
  local C=$(candidate)
  if [[ ! -f $VT/installed || $(<$VT/installed) != "$GCOMMIT" ]]; then
    local Wh=$BASE/wheels-test src=$BASE/wheels-test/src gw; rm -rf $Wh; mkdir -p $src
    git -C $GDEV archive $GCOMMIT src/graftling | tar -x -C $src
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $Wh $src/src/graftling >/dev/null
    gw=($Wh/graftling-*.whl(N)); (( $#gw == 1 )) || { print "STOP: graftling wheel not built"; return 1; }
    [[ -e $VT ]] && mv $VT $VT.$(date +%H%M%S)
    $CONDA -m venv --system-site-packages $VT; deps $VT
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps $gw
    $VT/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation -e $WT 2>&1 | grep -vi cache || true
    print -r -- "$GCOMMIT" > $VT/installed
  fi
  (cd $PYTEST_TMP && $VT/bin/python -I -c 'import graftling, graphtraj, pytest; print("graftling", graftling.__version__, graftling.__file__, "| graphtraj", graphtraj.__file__, "| pytest", pytest.__version__)')
  print "candidate under test: $C"
}
pytest_tmp_check() {
  case ${PYTEST_TMP:A}/ in ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness"; return 1 ;; esac
  print "pytest temp: TMPDIR=$PYTEST_TMP (outside the Harness)"
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case ${BASE:A}/ in ${H:A}/*) print "STOP: BASE $BASE is inside the Harness"; return 1 ;; esac
mkdir -p $OUT
case $STEP in
0)
  say "[0] preflight. Dialog: none. Reads only."
  print "zsh $ZSH_VERSION; $(git --version); conda $($CONDA --version 2>&1); runtime $($RTPY -I -B --version 2>&1)"
  print "candidate: $WT $(candidate) (branch $(git -C $WT branch --show-current)); base $OLD"
  git -C $WT cat-file -e $OLD^{commit} || { print "STOP: base $OLD missing"; return 1; }
  local t
  for t in 517 $TASKS; do
    print -r -- "$t: state $(print $STATE/tasks/$t-*(N/)) status $(grep -h '^status:' $STATE/tasks/$t-*/task.yml 2>/dev/null)"
    print -r -- "   sessions: $(print -l $RUNNER/sessions/$t-*(N/:t) | tr '\n' ' ')"
  done
  print "Ready when: 519 and 520 are 'status: integrated' and each lists its two sessions."
  print -r -- "next: zsh $THIS D"
  ;;
D)
  say "[D] read-only diagnosis of $RUNNER for 517 $TASKS. Dialog: none. No cleanup, no record written, no signal."
  begin D
  rm -rf $BASE/old-src; mkdir -p $BASE/old-src
  git -C $WT archive $OLD src/graphtraj | tar -x -C $BASE/old-src
  for label src in "base $OLD" $BASE/old-src/src "candidate $(candidate)" $WT/src; do
    print -r -- "--- $label"
    (cd $BASE && PYTHONDONTWRITEBYTECODE=1 $RTPY -I -B $SD/diag523.py $src $RUNNER $STATE 517 $TASKS) 2>&1 | tee -a $D/diag.txt
  done
  print "expected: base -> 519/520 (and 517) BUSY by 'subtree refused alias-not-found' with no live pids, caused by
the name '.claude' under sessions/; candidate -> every member 'not busy'. A live pid or a non-idle member stays BUSY."
  print -r -- "next: zsh $THIS T"
  ;;
T|F)
  pytest_tmp_check || return 1
  test_venv || return 1
  local targets=($FOCUSED); [[ $STEP == F ]] && targets=(tests)
  say "[$STEP] pytest ${targets} in $VT. Dialog: none. $([[ $STEP == F ]] && print 'About 73 min.' || print 'A few minutes.')"
  begin $STEP
  (cd $WT && TMPDIR=$PYTEST_TMP $VT/bin/python -m pytest -p no:cacheprovider -q -rfE ${VERIFY523_PYTEST_ARGS:-} $targets \
     > $D/pytest.txt 2>&1; print "exit=$?" >> $D/pytest.txt)
  tail -3 $D/pytest.txt; grep -E '^(FAILED|ERROR) ' $D/pytest.txt || print "(no FAILED/ERROR lines)"
  print "expected: all passed, including test_installed_cleanup_ignores_a_non_agent_directory_under_sessions[ended|executing]"
  [[ $STEP == T ]] && print -r -- "next: zsh $THIS F"
  ;;
C)
  say "[C] AFTER PRODUCTION ADOPTION OF $(candidate) ONLY. This step prints; it runs nothing."
  print -r -- "Main, with the adopted GraphTraj, calls the public cleanup (tasks tool) once per Task:
  mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"cleanup\", \"arguments\": {\"task_id\": \"519\"}}
  mcp__graphtraj__tasks {\"action\": \"execute\", \"feature\": \"cleanup\", \"arguments\": {\"task_id\": \"520\"}}
Dialog: at most the Runtime's own tool approval for mcp__graphtraj__tasks (choose: allow once).
Expected observable for each: cleanup_status 'cleaned', standby_aliases naming the Leader and Engineer,
the Worktree $H/.graphtraj/core/worktrees/<id>-<name> gone, branch agent/<id>-<name> deleted; runner/sessions/<id>-*
kept unchanged (standby). Before that, 'zsh $THIS D' with the adopted code must show 'not busy' for both."
  ;;
*) print -r -- "usage: zsh $THIS 0|D|T|F|C"; return 2 ;;
esac
