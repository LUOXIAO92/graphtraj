#!/bin/zsh
# Task 634 rehearsal driver (Engineer only): runs `zsh steps.zsh <step>` (Main's entry) against a local bare graftling
# remote, a scratch clone of <Harness>/graftling (never the real one) and the fakegh.py stand-in, chosen only through
# VERIFY634_* knobs. The expected list is the real edited scripts/verify-632/windows-expected.txt.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file of the candidate's simulated-Windows macOS run>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
WT=$(git -C $HERE rev-parse --show-toplevel)
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/634-graftling-windows-durable-writes
BUNDLE=$HERE/../graftling-634.bundle
EXPECTED=$WT/scripts/verify-632/windows-expected.txt
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
mkdir -p $S
# The stand-in's failing tests: the list's `fail` entries; and the W2 entries this Task removed (from dev 7add0b40).
grep $'^fail\t' $EXPECTED | cut -f2 > $S/fails
git -C $WT show 7add0b40:scripts/verify-632/windows-expected.txt | grep $'\tW2 (634)\t' | cut -f2 > $S/removed
print -r -- "stand-in failures: $(grep -c . $S/fails); removed W2 entries: $(grep -c . $S/removed)"

fresh() {  # fresh <scenario>: a new bare remote (branch absent), scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -q -D $BRANCH 2> /dev/null
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- $1 > $S/$1/gh/scenario; cp $JUNIT $S/$1/gh/junit; cp $S/fails $S/removed $S/$1/gh/
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY634_GRAFTLING=$S/$1/graftling VERIFY634_GREMOTE=$S/$1/gremote.git VERIFY634_GH=$S/$1/gh/gh \
    VERIFY634_EVIDENCE=$S/$1/runs VERIFY634_POLL_S=1 VERIFY634_APPEAR_S=${APPEAR:-10} VERIFY634_DONE_S=30 \
    ${BUNDLE_KNOB:-}
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
real_state() { git -C $REAL for-each-ref --format='%(refname) %(objectname)' refs/heads; }
BEFORE=$(real_state)
HEAD_SHA=$(git bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1)

# PASS path: 00 (remote absent), P (publish, wait, judge), 00 again (remote equal), W by sha and by run id.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000634
print -r -- "--- after P: clone $(git -C $S/matched/graftling rev-parse $BRANCH), remote $(git -C $S/matched/gremote.git rev-parse $BRANCH)" >> $OUT/matched-P.txt
# Round 2: <Harness>/graftling and the remote hold the round-1 candidate 2fadc6c8, as after Main's first P; 00 sees an
# ancestor, P fast-forwards both.
PREV=2fadc6c8087a9c2bfb3eb1d3832f3ef101ea02f6
fresh ff; git -C $S/ff/gremote.git update-ref refs/heads/$BRANCH $PREV; git -C $S/ff/graftling branch -q $BRANCH $PREV
step ff ff-00.txt 00; step ff ff-P.txt P
print -r -- "--- after P: clone $(git -C $S/ff/graftling rev-parse $BRANCH), remote $(git -C $S/ff/gremote.git rev-parse $BRANCH)" >> $OUT/ff-P.txt
# FAIL path: a removed W2 test still fails at another Task's point, and a listed failure passes.
fresh residual; step residual residual-P.txt P
cp $S/residual/runs/*/observed-expected.txt $OUT/residual-observed-expected.txt
# Transient fault: X re-runs the failed job; attempt 2 is as matched.
fresh rerun; step rerun rerun-P.txt P; step rerun rerun-X.txt X 51000000634
# The run never appears.
APPEAR=4; fresh timeout; step timeout timeout-P.txt P; APPEAR=10

# Guards. A bundle whose workflow changes more than the push branches line: 00 reports FAIL, P stops before any push.
rm -rf $S/badwf-src; git clone -q --no-hardlinks $REAL $S/badwf-src
git -C $S/badwf-src fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} &&git -C $S/badwf-src checkout -q $BRANCH
sed 's/timeout-minutes: 90/timeout-minutes: 120/' $S/badwf-src/.github/workflows/windows.yml > $S/badwf.yml
cp $S/badwf.yml $S/badwf-src/.github/workflows/windows.yml
git -C $S/badwf-src -c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com \
  commit -q -am 'rehearsal: an extra workflow change'
git -C $S/badwf-src bundle create -q $S/badwf.bundle defad1db083e911900cbea1cb0ef165e6a66d322..$BRANCH
BUNDLE_KNOB=VERIFY634_BUNDLE=$S/badwf.bundle
fresh badwf; step badwf badwf-00.txt 00; step badwf badwf-P.txt P
print -r -- "--- remote branch after P: $(git -C $S/badwf/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/badwf-P.txt
unset BUNDLE_KNOB
# A local branch in the graftling clone that is not an ancestor of the bundle head stops 00 (never overwritten).
fresh guard; git -C $S/guard/graftling branch -q $BRANCH \
  $(git -C $S/guard/graftling commit-tree -p 82e9d12 -m diverged '82e9d12^{tree}'); step guard guard-local-00.txt 00
# A remote branch that is not an ancestor of the bundle head stops P before any push (never forced).
fresh diverged
git -C $S/diverged/gremote.git update-ref refs/heads/$BRANCH $(git -C $S/diverged/gremote.git commit-tree -p 82e9d12 -m diverged '82e9d12^{tree}')
step diverged diverged-P.txt P

# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
