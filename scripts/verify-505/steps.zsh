#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 505 Main-run steps. Run one step at a time:  zsh <this file> <STEP> [arg]
#   0      preflight: versions, paths, Worktree and graftling heads
#   G      GraphTraj full suite of the Worktree HEAD, graftling installed as a wheel from <Harness>/graftling main (background)
#   R      results: newest G (tail, FAILED/ERROR lines, the test_wait_handover_477 lines and failure count)
#   O <rev> <test paths...>  focused run of the given test files at <rev> of this Worktree, one pytest process (foreground)
# Dialog: none in every step. pytest's TMPDIR stays outside the Harness; each test step prints it.
# No step signals processes it did not start. Every step prints its follow-up with real values.
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=$H/tmp/505                                        # venvs and clones
OUT=$H/.graphtraj/core/state/tasks/505-member-hold-leak-between-tests/realhost   # text results
G=$H/graftling
BR=agent/505-member-hold-leak-between-tests
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
F477=tests/test_wait_handover_477.py
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}

say() { print -r -- "== $*"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: $PYTEST_TMP (outside the Harness)"
}
quiet() {  # the full suites run on an idle host, never beside another suite
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun this step later:"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case $STEP in
0)
  say "[0] preflight. Dialog: none."
  print "zsh: $ZSH_VERSION ($0)"; print "git: $(git --version)"
  print "conda python: $($CONDA --version 2>&1) ($CONDA)"
  print "Harness: $H"; print "Worktree: $WT ($(git -C $WT rev-parse --short HEAD) on $(git -C $WT branch --show-current); expected $BR)"
  print "graftling: $G ($(git -C $G rev-parse --short HEAD), $(git -C $G describe --tags --always 2>&1))"
  check_tmp
  local C=$(git -C $WT rev-parse --short HEAD)
  print -r -- "next: zsh ${0:A} O $C tests/test_member_child_workspace.py $F477"
  print -r -- "then, on an idle host: zsh ${0:A} G"
  ;;
G)
  say "[G] GraphTraj full suite of the Worktree HEAD, graftling as a wheel from $G (6 shards, --timeout 1500, -rA, background). Dialog: none. Returns at once."
  check_tmp; quiet
  [[ -d $G/src/graftling ]] || { print "STOP: $G/src/graftling missing"; return 1; }
  print "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  git -C $WT diff --quiet HEAD -- || { print "STOP: tracked changes in $WT are uncommitted"; return 1; }
  local C=$(git -C $WT rev-parse --short HEAD)
  local V=$T/venv-gt-$C N=$T/wheels-gt-$C R=$OUT/G-$C-$(date +%H%M%S)
  if [[ -x $V/bin/python ]]; then
    print "reusing $V (made for $C)"
  else
    mkdir -p $T
    $CONDA -m venv --system-site-packages $V && copy_deps $V
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $G/src/graftling >/dev/null
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      $N/graftling-*.whl -e $WT 2>&1 | grep -vi cache || true
  fi
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $R
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print "next, when it ends: zsh ${0:A} R"
  ;;
R)
  say "[R] results. Dialog: none."
  local g=($OUT/G-*(N/om[1]))
  (( $#g )) || { print -r -- "no G result under $OUT yet; run: zsh ${0:A} G"; return 0; }
  print -r -- "---- $g"
  [[ -f $g/suite.txt ]] || { print -r -- "(no suite.txt yet)"; return 0; }
  tail -8 $g/suite.txt
  print "failed/error lines:"
  grep -h -E '^(FAILED|ERROR) ' $g/suite.txt $g/shards/*(N.) 2>/dev/null | sort -u || print "(none)"
  print -r -- "---- $F477 in $g"
  local lines=$(grep -h -F "$F477::" $g/suite.txt $g/shards/*(N.) 2>/dev/null | grep -E '^(PASSED|FAILED|ERROR|SKIPPED) ' | sort -u || true)
  print -r -- "result lines: $(print -r -- $lines | grep -c . || true)"
  print -r -- "failed or error: $(print -r -- $lines | grep -c -E '^(FAILED|ERROR) ' || true)"
  print -r -- $lines | grep -E '^(FAILED|ERROR) ' || true
  print -r -- "next: report $g to the Leader"
  ;;
O)
  (( $# >= 3 )) || { print -r -- "usage: zsh ${0:A} O <rev> <test paths...>"; return 2; }
  local REV=$2; shift 2
  say "[O] focused run at $REV of $WT, one pytest process, foreground. Dialog: none."
  check_tmp; quiet
  [[ -d $G/src/graftling ]] || { print -r -- "STOP: $G/src/graftling missing"; return 1; }
  local S=$(git -C $WT rev-parse --short "$REV^{commit}") FULL=$(git -C $WT rev-parse "$REV^{commit}")
  local K=$T/gt-$S V=$T/venv-gto-$S N=$T/wheels-gto-$S O=$OUT/O-$S-$(date +%H%M%S).txt
  if [[ -d $K/.git ]]; then
    print -r -- "reusing $K"
  else
    mkdir -p $T
    git clone -q --no-hardlinks $WT $K && git -C $K checkout -q --detach $S
  fi
  [[ $(git -C $K rev-parse HEAD) == $FULL ]] || { print -r -- "STOP: $K HEAD is not $FULL"; return 1; }
  [[ -e $K/src/graftling ]] && { print -r -- "STOP: $K/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  print -r -- "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  if [[ -x $V/bin/python ]]; then
    print -r -- "reusing $V (made for $S)"
  else
    $CONDA -m venv --system-site-packages $V && copy_deps $V
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $G/src/graftling >/dev/null
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      $N/graftling-*.whl -e $K 2>&1 | grep -vi cache || true
  fi
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $OUT
  print -r -- "tests: $*"
  (cd $K && TMPDIR=$PYTEST_TMP $V/bin/python -m pytest -p no:cacheprovider -q -rfE "$@" 2>&1 && print "exit=0" || print "exit=$?") | tee $O
  print -r -- "result: $O"
  print -r -- "next: report $O to the Leader; another focused run: zsh ${0:A} O <rev> <test paths...>"
  ;;
*) print -r -- "usage: zsh ${0:A} 0|G|R|O <rev> <test paths...>"; return 2 ;;
esac
