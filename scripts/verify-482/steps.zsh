#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 482: the suite never writes an enclosing Harness. Run from this Worktree: zsh scripts/verify-482/steps.zsh <step>
# 00  preflight (~1-2 min): interpreter, commit, Harness root, fix checked out; scratch venvs BEFORE (ddd80e0c) and AFTER.
# 01  gate (~2 min): fake outer Harness under <Harness>/tmp/482; the 470 failing tests BEFORE write into it, AFTER do not.
# 02  full suite, pytest temp OUTSIDE the Harness (Main's TMPDIR), 8 shards (~12-20 min; self-stops at 25).
# 03  full suite, pytest temp INSIDE <Harness>/tmp/482/t (outer Harness = the real one); needs 01 PASS (~12-20 min).
# 02 and 03 snapshot production main-sessions/continuity.jsonl, main-sessions/ and swarm/sessions/ before and after
# and print CHANGED/UNCHANGED, separating test-caused entries from ordinary production activity. Production is only
# read. All outputs stay under <Harness>/tmp/482/out.
set -u
SD=${0:A:h}; THIS=${0:A}; WT=${SD:h:h}; H=${WT:h:h:h:h}
FIX_COMMIT=c498b8e2
BEFORE_COMMIT=ddd80e0c
BASE=$H/tmp/482; OUT=$BASE/out
RT=$H/.venv-runtime
CONDA=${VERIFY482_PYTHON:-/Users/luoxiao/miniconda3/bin/python3.13}
SHARDS=8
OUTSIDE_TMP=${TMPDIR:-/tmp}
STEP=${1:-help}
path=(/opt/homebrew/bin $HOME/.local/bin $path)
mkdir -p $OUT
say() { print -r -- ""; print -r -- "### $*"; }
next() { print -r -- ""; print -r -- "==> next (Main): zsh $THIS $1"; }
# $1 = TMPDIR; the rest is the command. No Session variables of the caller leak in.
clean() { local T=$1; shift; env -i HOME=$HOME USER=${USER:-luoxiao} PATH=${(j.:.)path} TERM=${TERM:-xterm} TMPDIR=$T LANG=${LANG:-en_US.UTF-8} \
    ${PYTEST_OUTSIDE_HARNESS_TMPDIR:+PYTEST_OUTSIDE_HARNESS_TMPDIR=$PYTEST_OUTSIDE_HARNESS_TMPDIR} "$@"; }
venv() { print -r -- $BASE/venv-$1; }
markers() { print -r -- $BASE pytest-of- graphtraj-tests- shared-native-session e3116b3f $OUTSIDE_TMP; }
# Prints the enclosing Harness of $1, or nothing.
harness_of() { $(venv after)/bin/python -I -c 'import sys; sys.path.insert(0, sys.argv[1]); from harness_isolation import enclosing_harness as e; r = e(sys.argv[2]); print(r or "")' $WT/tests $1; }

build() {  # $1 label, $2 source tree
  local V=$(venv $1) S=($RT/lib/python*/site-packages(N)) D
  rm -rf $V; $CONDA -m venv --system-site-packages $V || return 1
  $V/bin/python -m pip install -q --disable-pip-version-check --no-cache-dir --no-index --no-deps --no-build-isolation \
      -e $2/src/graftling -e $2 2>&1 | grep -vi cache
  D=($V/lib/python*/site-packages(N))
  cp -Rp $S[1]/click $S[1]/click-*.dist-info(N) $S[1]/yaml $S[1]/_yaml(N) $S[1]/[Pp]y[Yy][Aa][Mm][Ll]-*.dist-info(N) \
      $S[1]/websockets $S[1]/websockets-*.dist-info(N) $D[1]/ || return 1
  (cd /tmp && $V/bin/python -I -c 'import graphtraj; print("  '$1' venv imports", graphtraj.__file__)')
}

step_00() {
  say "[00] preflight"
  print "interpreter: $CONDA ($($CONDA --version 2>&1))"
  print "Worktree: $WT  HEAD $(git -C $WT rev-parse HEAD)"
  print "Harness root: $H  (.graphtraj present: $([[ -d $H/.graphtraj ]] && print yes || print NO))"
  [[ -d $H/.graphtraj ]] || { print "STOP: $H has no .graphtraj"; return 1; }
  git -C $WT merge-base --is-ancestor $FIX_COMMIT HEAD && [[ -f $WT/tests/harness_isolation.py ]] \
    && print "fix $FIX_COMMIT checked out: yes" || { print "STOP: fix $FIX_COMMIT is not checked out"; return 1; }
  [[ -z $(git -C $WT status --porcelain -- src tests scripts) ]] || { print "STOP: uncommitted changes in src/tests/scripts"; return 1; }
  say "scratch venvs under $BASE"
  rm -rf $BASE/src-before; mkdir -p $BASE/src-before; git -C $WT archive $BEFORE_COMMIT | tar -x -C $BASE/src-before || return 1
  build before $BASE/src-before || return 1
  build after $WT || return 1
  print "Main's TMPDIR for step 02: $OUTSIDE_TMP; enclosing Harness: ${$(harness_of $OUTSIDE_TMP):-none}"
  [[ -z $(harness_of $OUTSIDE_TMP) ]] || { print "STOP: Main's TMPDIR lies inside a Harness; step 02 needs it outside"; return 1; }
  print "== 00 done"; next 01
}

fake_harness() {  # $1 dir: a valid GraphTraj Config and an agents host configuration, so every product walk-up stops here
  rm -rf $1; mkdir -p $1/tmp/t $1/docs $1/.agents-control
  print -r -- '{}' > $1/.agents-control/claude-host.json
  $(venv after)/bin/python -I -c 'import sys; from pathlib import Path
from graphtraj.configuration.project_configuration import DEFAULT_CONFIG_CONTENT, configuration_file
p = configuration_file(Path(sys.argv[1])); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(DEFAULT_CONFIG_CONTENT)' $1
}
fake_listing() { (cd $1 && find .graphtraj .agents-control -type f | sort | while read f; do print -r -- "$(shasum -a 256 $f | cut -c1-16) $(stat -f %z $f) $f"; done) }

step_01() {
  say "[01] gate: fake outer Harness under $BASE (the walk-up stops there, never at $H)"
  local ok=1 label fake src log
  $CONDA -I $SD/snap.py take $H $OUT/01-prod-before.json
  for label in before after; do
    fake=$BASE/fake-$label; src=$([[ $label == before ]] && print $BASE/src-before || print $WT); log=$OUT/01-$label.log
    fake_harness $fake || return 1
    fake_listing $fake > $OUT/01-$label-fake-before.txt
    (cd $src && clean $fake/tmp/t $(venv $label)/bin/python -m pytest -p no:cacheprovider -q -rfEs $(cat $SD/gate-tests.txt) > $log 2>&1)
    print "$label: pytest exit $? | $(grep -E '^[0-9]+ (passed|failed)' $log | tail -1) | log $log"
    grep -h "moved TMPDIR" $log | head -1
    fake_listing $fake > $OUT/01-$label-fake-after.txt
    if cmp -s $OUT/01-$label-fake-before.txt $OUT/01-$label-fake-after.txt; then
      print "$label: fake Harness .graphtraj/.agents-control: UNCHANGED"
      [[ $label == before ]] && { print "  (expected CHANGED: the reproduction did not reproduce)"; ok=0; }
    else
      print "$label: fake Harness .graphtraj/.agents-control: CHANGED"; diff $OUT/01-$label-fake-before.txt $OUT/01-$label-fake-after.txt | sed 's/^/  /'
      [[ $label == after ]] && ok=0
    fi
  done
  grep -q "moved TMPDIR" $OUT/01-after.log || { print "after: the move notice is missing"; ok=0; }
  [[ -z $(ls -A $BASE/fake-after/tmp/t) ]] && print "after: fake tmp/t is empty (pytest temp moved out)" || { print "after: fake tmp/t is NOT empty"; ok=0; }
  $CONDA -I $SD/snap.py take $H $OUT/01-prod-after.json
  $CONDA -I $SD/snap.py compare $OUT/01-prod-before.json $OUT/01-prod-after.json $(markers) || ok=0
  if (( ok )); then print ok > $OUT/01-PASS; print "== 01 verdict: PASS"; next 02
  else rm -f $OUT/01-PASS; print "== 01 verdict: FAIL (do not run 03)"; return 1; fi
}

suite() {  # $1 label, $2 TMPDIR
  local L=$1 T=$2 R=$OUT/$1
  rm -rf $R-shards; mkdir -p $R-shards
  $CONDA -I $SD/snap.py take $H $R-prod-before.json
  print "== start $(date +%T) commit $(git -C $WT rev-parse HEAD) TMPDIR=$T shards=$SHARDS"
  (cd $WT && clean $T $(venv after)/bin/python -I -c 'import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
try:
    sys.exit(child.wait(timeout=1500))
except subprocess.TimeoutExpired:
    print("== 25 min limit reached: stopping the suite", flush=True)
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
    sys.exit(124)' $(venv after)/bin/python $WT/scripts/run_test_shards.py --shards $SHARDS --log-dir $R-shards) > $R-suite.txt 2>&1
  print "== shards exit $? at $(date +%T); output $R-suite.txt, shard logs $R-shards/"
  tail -n 4 $R-suite.txt
  print "shards printing the move notice: $(grep -l 'moved TMPDIR' $R-shards/shard-*.log 2>/dev/null | wc -l | tr -d ' ') of $SHARDS"
  grep -h "moved TMPDIR" $R-shards/shard-*.log 2>/dev/null | head -1
  $CONDA -I $SD/snap.py take $H $R-prod-after.json
  $CONDA -I $SD/snap.py compare $R-prod-before.json $R-prod-after.json $(markers)
  touch $R-shards/failures.txt
  print "== failures ($(wc -l < $R-shards/failures.txt | tr -d ' ')):"; cat $R-shards/failures.txt
  print "== NEW failures (not in baseline $SD/baseline-failures.txt):"
  comm -23 <(sort -u $R-shards/failures.txt) <(grep -v '^#' $SD/baseline-failures.txt | sort -u) | sed 's/^/  /'
  print "== end of new failures"
}

step_02() {
  say "[02] full suite, pytest temp outside the Harness: $OUTSIDE_TMP"
  [[ -z $(harness_of $OUTSIDE_TMP) ]] || { print "STOP: $OUTSIDE_TMP lies inside a Harness"; return 1; }
  suite 02 $OUTSIDE_TMP
  next 03
}

step_03() {
  say "[03] full suite, pytest temp inside the real Harness: $BASE/t"
  [[ -f $OUT/01-PASS ]] || { print "STOP: 01 has not passed"; return 1; }
  rm -rf $BASE/t; mkdir -p $BASE/t
  print "enclosing Harness of $BASE/t: $(harness_of $BASE/t)"
  # Guard probe first: the session must announce the move and leave $BASE/t empty.
  (cd $WT && clean $BASE/t $(venv after)/bin/python -m pytest -p no:cacheprovider -q tests/test_harness_isolation.py > $OUT/03-probe.log 2>&1)
  print "probe exit $?: $(grep -h 'moved TMPDIR' $OUT/03-probe.log | head -1)"
  { grep -q "moved TMPDIR" $OUT/03-probe.log && [[ -z $(ls -A $BASE/t) ]] } || { print "STOP: the guard did not move the temp root"; return 1; }
  suite 03 $BASE/t
  print "$BASE/t after the run (expected empty): $(ls -A $BASE/t | head -5)"
  print "== failures only in 03 (not in 02):"; comm -23 <(sort -u $OUT/03-shards/failures.txt) <(sort -u $OUT/02-shards/failures.txt 2>/dev/null) | sed 's/^/  /'
}

case $STEP in
  00) step_00 2>&1 | tee $OUT/00.txt ;;
  01) step_01 2>&1 | tee $OUT/01.txt ;;
  02) step_02 2>&1 | tee $OUT/02.txt ;;
  03) step_03 2>&1 | tee $OUT/03.txt ;;
  *) print "usage: zsh $THIS <00|01|02|03>" ;;
esac
