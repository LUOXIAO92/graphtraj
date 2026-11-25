#!/bin/zsh
# Task 632 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X/D against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the fakegh.py stand-in, chosen only through VERIFY632_* knobs.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS run with simulated Windows skips>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
# Two tests that pass on macOS stand for the listed Windows failures (one in-process, one with a subprocess).
FAILS=(tests/test_connection_serve.py::test_removed_control_directory_stops_the_service
       tests/test_jsonl_archive.py::test_native_history_not_notifications_defines_order_and_pagination)
EXPECTED=$S/windows-expected-rehearsal.txt
mkdir -p $S
{ grep '^skip-allowed' $HERE/../windows-expected.txt
  for f in $FAILS; do print -r -- "fail	$f	src/graftling/connection.py:68	W4	rehearsal stand-in"; done } > $EXPECTED
fresh() {  # fresh <scenario>: a new bare remote, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- $1 > $S/$1/gh/scenario; cp $JUNIT $S/$1/gh/junit; print -lr -- $FAILS > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY632_GRAFTLING=$S/$1/graftling VERIFY632_GREMOTE=$S/$1/gremote.git VERIFY632_GH=$S/$1/gh/gh \
    VERIFY632_EXPECTED=$EXPECTED VERIFY632_EVIDENCE=$S/$1/evidence VERIFY632_POLL_S=1 VERIFY632_APPEAR_S=${2:-10} \
    VERIFY632_DONE_S=30
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc ${APPEAR:-10}) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
real_state() { git -C $REAL for-each-ref --format='%(refname) %(objectname)' refs/heads; }
BEFORE=$(real_state)

fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $(git bundle list-heads $HERE/../graftling-632.bundle | cut -d' ' -f1)
step matched matched-W-run.txt W 51000000000
fresh mismatch; step mismatch mismatch-P.txt P
cp $S/mismatch/evidence/run-51000000000-a1/observed-expected.txt $OUT/mismatch-observed-expected.txt
fresh setup-fail; step setup-fail setup-fail-P.txt P
fresh exit2; step exit2 exit2-P.txt P
fresh rerun; step rerun rerun-P.txt P; step rerun rerun-X.txt X 51000000000
fresh dispatch; step dispatch dispatch-P.txt P; step dispatch dispatch-D.txt D
APPEAR=4; fresh timeout; step timeout timeout-P.txt P; APPEAR=10
# Guards: a local branch in the graftling clone that differs from the bundle head stops 00 (never overwritten); a
# remote branch that is not an ancestor of the bundle head stops P before any push (never forced).
fresh guard; git -C $S/guard/graftling branch -q agent/632-graftling-windows-ci 6166718; step guard guard-local-00.txt 00
fresh diverged; git -C $S/diverged/gremote.git branch -q agent/632-graftling-windows-ci 82e9d12
git -C $S/diverged/gremote.git commit-tree -p 82e9d12 -m diverged 82e9d12^{tree} > $S/diverged/tip
git -C $S/diverged/gremote.git update-ref refs/heads/agent/632-graftling-windows-ci $(<$S/diverged/tip)
step diverged diverged-P.txt P
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
