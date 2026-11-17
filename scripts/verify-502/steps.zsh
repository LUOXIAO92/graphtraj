#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 502 Main-run steps. Run one step at a time:  zsh <this file> <STEP> [arg]
#   0            preflight: versions, paths, Worktree and graftling heads
#   L dev|cand   loaded repetition of the items 1, 5, 6 tests (verify-487 repeat.py --tests, 6 workers x 5 passes,
#                600 s bound) at dev 78279964 (dev) or the Worktree HEAD (cand), same method for both, with a
#                wall-clock watcher beside it (foreground, ~11 min). It must NOT overlap Task 501's CPU
#                measurement or any other test run: Main sequences them.
#   G            GraphTraj full suite of the Worktree HEAD, graftling as a wheel from <Harness>/graftling, with the
#                wall-clock watcher beside it (background)
#   R            results: newest G (failed lines, the items 1, 5, 6 files) and newest L dev and L cand (counts, clock)
# Dialog: none in every step. pytest's TMPDIR stays outside the Harness; each test step prints it.
# No step signals processes it did not start. Every step prints its follow-up with real values.
emulate -L zsh
setopt err_return pipe_fail no_unset
WT=$(git -C ${0:A:h} rev-parse --show-toplevel)    # this Task Worktree
H=${WT:h:h:h:h}                                     # <Harness>/.graphtraj/core/worktrees/<name> -> <Harness>
T=$H/tmp/502                                        # venvs and clones
OUT=$H/.graphtraj/core/state/tasks/502-claude-native-host-test-intermittent-failures/realhost   # text results
G=$H/graftling
BR=agent/502-claude-native-host-test-intermittent-failures
DEV=78279964
CONDA=$HOME/miniconda3/bin/python3.13
RT=$H/.venv-runtime/lib/python3.13/site-packages
F1=tests/test_claude_native_host.py
F5=tests/test_task_node_protocol.py
F6=tests/test_team_session_delivery.py
NODES=$F1,$F5::test_cancelled_replacement_acceptance_survives_unrelated_revision,$F6::test_a_leader_dispatches_two_same_role_members_in_one_turn
STEP=${1:-}
PYTEST_TMP=${TMPDIR:-/tmp}

say() { print -r -- "== $*"; }
check_tmp() {
  case ${PYTEST_TMP:A}/ in
    ${H:A}/*) print "STOP: TMPDIR $PYTEST_TMP is inside the Harness; set TMPDIR outside it"; return 1 ;;
  esac
  print "pytest temp: $PYTEST_TMP (outside the Harness)"
}
quiet() {  # loaded runs and full suites run on an idle host, never beside another test run
  local others=$(ps -axww -o pid=,command= | grep -E 'run_test_shards|-m pytest|repeat\.py' | grep -v grep || true)
  [[ -z $others ]] || { print "STOP: another test run is running; rerun this step later:"; print -r -- $others; return 1; }
}
copy_deps() {  # production's click, yaml, websockets into venv $1 (no PyPI on this host)
  local D=$($1/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  cp -Rp $RT/click $RT/click-*.dist-info(N) $RT/yaml $RT/_yaml(N) $RT/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
    $RT/websockets $RT/websockets-*.dist-info(N) $D/
}
venv_for() {  # venv_for <venv> <checkout>: graftling wheel from $G plus <checkout> editable
  local V=$1 K=$2 N=$1-wheels
  if [[ -x $V/bin/python ]]; then
    print -r -- "reusing $V"
  else
    $CONDA -m venv --system-site-packages $V && copy_deps $V
    $CONDA -m pip wheel -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -w $N $G/src/graftling >/dev/null
    $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      $N/graftling-*.whl -e $K 2>&1 | grep -vi cache || true
  fi
  (cd $PYTEST_TMP && $V/bin/python -I -c 'import graphtraj, graftling; print("graphtraj", graphtraj.__file__); print("graftling", graftling.__file__, graftling.__version__)')
}

[[ -d $H/graphtraj && -d $H/.graphtraj ]] || { print "STOP: $H is not the Harness root"; return 1; }
case $STEP in
0)
  say "[0] preflight. Dialog: none."
  print "zsh: $ZSH_VERSION ($0)"; print "git: $(git --version)"
  print "conda python: $($CONDA --version 2>&1) ($CONDA)"
  print "Harness: $H"; print "Worktree: $WT ($(git -C $WT rev-parse --short HEAD) on $(git -C $WT branch --show-current); expected $BR)"
  print "dev base: $(git -C $WT rev-parse --short $DEV^{commit})"
  print "graftling: $G ($(git -C $G rev-parse --short HEAD), $(git -C $G describe --tags --always 2>&1))"
  check_tmp
  print -r -- "next, on an idle host and not during Task 501's CPU measurement: zsh ${0:A} L dev"
  print -r -- "then: zsh ${0:A} L cand; then zsh ${0:A} G; then zsh ${0:A} R"
  ;;
L)
  local VAR=${2:-}
  [[ $VAR == dev || $VAR == cand ]] || { print -r -- "usage: zsh ${0:A} L dev|cand"; return 2; }
  say "[L $VAR] loaded repetition of items 1, 5, 6 (6 workers x 5 passes, 600 s bound) plus a clock watcher. Dialog: none. Foreground, ~11 min. Not during Task 501's CPU measurement."
  check_tmp; quiet
  [[ -d $G/src/graftling ]] || { print -r -- "STOP: $G/src/graftling missing"; return 1; }
  git -C $WT diff --quiet HEAD -- || { print "STOP: tracked changes in $WT are uncommitted"; return 1; }
  local REV=$([[ $VAR == dev ]] && print $DEV || git -C $WT rev-parse HEAD)
  local S=$(git -C $WT rev-parse --short "$REV^{commit}") FULL=$(git -C $WT rev-parse "$REV^{commit}")
  local K=$T/gt-$S V=$T/venv-gt-$S O=$OUT/L-$VAR-$S-$(date +%H%M%S)
  if [[ -d $K/.git ]]; then
    print -r -- "reusing $K"
  else
    mkdir -p $T
    git clone -q --no-hardlinks $WT $K && git -C $K checkout -q --detach $S
  fi
  [[ $(git -C $K rev-parse HEAD) == $FULL ]] || { print -r -- "STOP: $K HEAD is not $FULL"; return 1; }
  git -C $K diff --quiet HEAD -- || { print -r -- "STOP: $K has tracked changes"; return 1; }
  [[ -e $K/src/graftling ]] && { print -r -- "STOP: $K/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  print -r -- "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  venv_for $V $K
  mkdir -p $O
  print -r -- "checkout $K at $S; repeat.py from $WT (same file for dev and cand); tests: $NODES"
  # The watcher ends by itself after 700 s; nothing signals it.
  $V/bin/python -I $WT/scripts/verify-502/clockwatch.py 700 $O/clock.txt &
  local W=$!
  (cd $PYTEST_TMP && TMPDIR=$PYTEST_TMP $V/bin/python -I $WT/scripts/verify-487/repeat.py $K $O \
     --workers 6 --fast 5 --limit 600 --tests $NODES 2>&1) | tee $O/run.txt
  print -r -- "waiting for the clock watcher (ends by itself within 700 s of its start)"
  wait $W || true
  tail -1 $O/clock.txt
  grep -E 'BACKWARD|OFFSET' $O/clock.txt | head -20 || true
  print -r -- "result: $O (run.txt, counts.txt, failures/, clock.txt)"
  [[ $VAR == dev ]] && print -r -- "next: zsh ${0:A} L cand" || print -r -- "next, on an idle host: zsh ${0:A} G"
  ;;
G)
  say "[G] GraphTraj full suite of the Worktree HEAD, graftling as a wheel from $G (6 shards, --timeout 1500, -rA, background), clock watcher beside it. Dialog: none. Returns at once."
  check_tmp; quiet
  [[ -d $G/src/graftling ]] || { print "STOP: $G/src/graftling missing"; return 1; }
  print "graftling wheel source: $G at $(git -C $G rev-parse HEAD) ($(git -C $G branch --show-current))"
  [[ -e $WT/src/graftling ]] && { print "STOP: $WT/src/graftling exists; GraphTraj must use the installed graftling"; return 1; }
  git -C $WT diff --quiet HEAD -- || { print "STOP: tracked changes in $WT are uncommitted"; return 1; }
  local C=$(git -C $WT rev-parse --short HEAD)
  local V=$T/venv-gtw-$C R=$OUT/G-$C-$(date +%H%M%S)
  mkdir -p $T
  venv_for $V $WT
  mkdir -p $R
  # The watcher ends by itself after 1800 s; nothing signals it.
  (cd $PYTEST_TMP && nohup $V/bin/python -I $WT/scripts/verify-502/clockwatch.py 1800 $R/clock.txt >/dev/null 2>&1) &!
  (cd $WT && TMPDIR=$PYTEST_TMP nohup $V/bin/python scripts/run_test_shards.py --shards 6 --timeout 1500 --log-dir $R/shards -- -rA > $R/suite.txt 2>&1; print "exit=$?" >> $R/suite.txt) &!
  print "started; result: tail -30 $R/suite.txt"
  print "next, when it ends: zsh ${0:A} R"
  ;;
R)
  say "[R] results. Dialog: none."
  local g=($OUT/G-*(N/om[1]))
  if (( $#g )); then
    print -r -- "---- $g"
    if [[ -f $g/suite.txt ]]; then
      tail -8 $g/suite.txt
      print "failed/error lines:"
      local logs=($g/suite.txt $g/shards/*(N.))   # never empty: grep never reads stdin
      grep -h -E '^(FAILED|ERROR) ' $logs 2>/dev/null | sort -u || print "(none)"
      local f
      for f in $F1 $F5 $F6; do
        local lines=$(grep -h -F "$f::" $logs 2>/dev/null | grep -E '^(PASSED|FAILED|ERROR) ' | sort -u || true)
        print -r -- "$f: results $(print -r -- $lines | grep -c . || true), failed or error $(print -r -- $lines | grep -c -E '^(FAILED|ERROR) ' || true)"
      done
      print -r -- "item 1 diagnoses (ended without answering):"
      grep -h -E 'ended without answering' $logs 2>/dev/null | sort -u || print "(none)"
    else
      print -r -- "(no suite.txt yet)"
    fi
    [[ -f $g/clock.txt ]] && { print -r -- "clock: $(tail -1 $g/clock.txt)"; grep -E 'BACKWARD|OFFSET' $g/clock.txt | head -20 || true; }
  else
    print -r -- "no G result under $OUT yet"
  fi
  local v
  for v in dev cand; do
    local l=($OUT/L-$v-*(N/om[1]))
    (( $#l )) || { print -r -- "no L $v result yet"; continue; }
    print -r -- "---- $l"
    [[ -f $l/counts.txt ]] && cat $l/counts.txt || print -r -- "(no counts.txt yet)"
    local texts=($l/failures/*(N.))
    (( $#texts )) && { grep -h -E 'ended without answering' $texts 2>/dev/null | sort | uniq -c || true; }
    [[ -f $l/clock.txt ]] && { print -r -- "clock: $(tail -1 $l/clock.txt)"; grep -E 'BACKWARD|OFFSET' $l/clock.txt | head -20 || true; }
  done
  print -r -- "next: report these paths to the Leader"
  ;;
*) print -r -- "usage: zsh ${0:A} 0|L dev|L cand|G|R"; return 2 ;;
esac
