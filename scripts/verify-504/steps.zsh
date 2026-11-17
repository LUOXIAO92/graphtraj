#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 504 Main-run steps. Run one step at a time:  zsh <this file> <STEP> [arg]
#   0      preflight: versions, paths, Worktree and graftling heads, clone state
#   C      clone <Harness>/graftling into this Worktree's ignored .scratch/504/graftling; the Task branch starts at its dev
#   G      GraphTraj full suite of the Worktree HEAD, graftling installed as a wheel from <Harness>/graftling main (background)
#   F [ref] graftling full suite of ref (default the Task branch; `dev` is the baseline) from a fresh clone (background)
#   R      results: newest G and the two newest F (tail, FAILED/ERROR lines, the item-1 test line)
# Dialog: none in every step. pytest's TMPDIR stays outside the Harness; each test step prints it.
# No step signals processes it did not start. Every step prints its follow-up with real values.
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=$H/tmp/504                                        # venvs and clones
OUT=$H/.graphtraj/core/state/tasks/504-split-followups-tests-docs-helpers/realhost   # text results
G=$H/graftling
GC=$WT/.scratch/504/graftling
BR=agent/504-split-followups-tests-docs-helpers
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
ITEM1=tests/test_suite_environment.py::test_a_suite_without_installed_metadata_stops_at_start_with_one_message
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
  print "Harness: $H"; print "Worktree: $WT ($(git -C $WT rev-parse --short HEAD) on $(git -C $WT branch --show-current))"
  print "graftling: $G ($(git -C $G rev-parse --short HEAD), $(git -C $G describe --tags --always 2>&1))"
  if [[ -d $GC ]]; then print "clone: $GC ($(git -C $GC rev-parse --short HEAD) on $(git -C $GC branch --show-current))"
  else print "clone: $GC absent"; fi
  check_tmp
  [[ -d $GC ]] && print "next: zsh ${0:A} G" || print "next: zsh ${0:A} C"
  ;;
C)
  say "[C] clone $G into $GC; $BR starts at its dev. Dialog: none."
  [[ -e $GC ]] && { print "STOP: $GC exists; it is not overwritten"; return 1; }
  print "graftling dev: $(git -C $G rev-parse -q --verify 'dev^{commit}' 2>/dev/null || print absent)"
  mkdir -p ${GC:h}
  git clone -q --no-hardlinks $G $GC
  git -C $GC rev-parse -q --verify 'refs/remotes/origin/dev^{commit}' >/dev/null \
    || { print "STOP: origin/dev does not exist in the clone $GC; nothing else changed there"; return 1; }
  git -C $GC rev-parse -q --verify refs/heads/dev >/dev/null || git -C $GC branch -q --no-track dev origin/dev
  git -C $GC switch -q -c $BR dev
  local base=$(git -C $GC rev-parse HEAD) gdev=$(git -C $G rev-parse 'dev^{commit}')
  print "branch: $(git -C $GC branch --show-current) base $base"
  [[ $base == $gdev ]] && print "PASS base equals $G dev ($gdev)" || { print "FAIL base differs from $G dev ($gdev)"; return 1; }
  git -C $GC remote remove origin
  print "remotes: $(git -C $GC remote | tr '\n' ' ')(none expected)"
  git -C $WT check-ignore -q $GC && print "PASS $GC is ignored by the Worktree" || print "FAIL $GC is not ignored"
  print "next: the Engineer edits and commits in $GC; then zsh ${0:A} G, zsh ${0:A} F dev and zsh ${0:A} F"
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
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print "next, when it ends: zsh ${0:A} R"
  ;;
F)
  local REF=${2:-$BR}
  say "[F] graftling full suite of $REF from a fresh clone of $GC (background). Dialog: none. Returns at once."
  check_tmp; quiet
  [[ -d $GC ]] || { print "STOP: run C first"; return 1; }
  local S=$(git -C $GC rev-parse --short "$REF^{commit}")
  local K=$T/graftling-$S V=$T/venv-gf-$S R=$OUT/F-$S-$(date +%H%M%S)
  if [[ -x $V/bin/python ]]; then
    print "reusing $K and $V (made for $S)"
  else
    [[ -e $K ]] && { print "STOP: $K exists without its venv $V"; return 1; }
    mkdir -p $T
    git clone -q --no-hardlinks $GC $K && git -C $K checkout -q --detach $S
    $CONDA -m venv --system-site-packages $V && copy_deps $V
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $K/src/graftling 2>&1 | grep -vi cache || true
  fi
  print "clone: $K at $(git -C $K rev-parse --short HEAD)"
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graftling; print("graftling", graftling.__file__, graftling.__version__)')
  mkdir -p $R
  (cd $K && TMPDIR=$PYTEST_TMP nohup $V/bin/python -m pytest -p no:cacheprovider -q -rfE > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print "next, when it ends: zsh ${0:A} R"
  ;;
R)
  say "[R] results. Dialog: none."
  local g=($OUT/G-*(N/om[1])) f=($OUT/F-*(N/om[1,2]))
  for r in $g $f; do
    print "---- $r"
    tail -8 $r/suite.txt
    print "failed/error lines:"
    grep -h -E '^(FAILED|ERROR) ' $r/suite.txt $r/shards/*(N.) 2>/dev/null | sort -u || print "(none)"
  done
  if (( $#g )); then
    print "---- item 1 in $g"
    grep -h -F "$ITEM1" $g/suite.txt $g/shards/*(N.) 2>/dev/null | grep -E 'PASSED|FAILED|ERROR|SKIPPED' | sort -u || print "item 1: no result line found"
  fi
  ;;
*) print "usage: zsh ${0:A} 0|C|G|F [ref]|R"; return 2 ;;
esac
