#!/bin/zsh
# Task 633 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh633.py around 632's fakegh.py), chosen
# only through VERIFY633_* knobs. The results are judged against the real scripts/verify-632/windows-expected.txt as
# this Task edits it.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS candidate run with simulated
#        Windows skips (verify-632/evidence/macos/simulate_windows_skips.py)>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/633-graftling-windows-process
BASE=defad1db083e911900cbea1cb0ef165e6a66d322
BUNDLE=$HERE/../graftling-633.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the two Windows-only W1 tests skip ("Windows only: ..."); on the runner they must pass. The stand-in's
# artifact starts from the macOS run with those two made passed; newtest-skipped keeps them skipped.
$PY -I -c '
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.argv[1])
for case in tree.getroot().iter("testcase"):
    for child in list(case):
        if child.tag == "skipped" and child.get("message", "").startswith("Windows only"):
            case.remove(child)
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-w1-passed.xml
# Failing in the stand-in run: every `fail` entry of the edited list, a W1 (633) host test first (mismatch makes the
# first one pass: a listed W1 entry that unexpectedly passes). test_agent_control's W1 entry is not first: in the
# simulated JUnit it reaches its POSIX-only part and skips, so it could not stand for a pass.
FAILS=(${(f)"$(awk -F'\t' '$1=="fail" && $4=="W1 (633)" && $2 !~ /test_agent_control/ {print $2}' $LIST
              awk -F'\t' '$1=="fail" && ($4!="W1 (633)" || $2 ~ /test_agent_control/) {print $2}' $LIST)"})
NEWFAIL=tests/test_process_windows_633.py::test_process_alive_never_terminates_its_target
diverged_commit() { git -C $1 commit-tree -p $BASE -m diverged "$BASE^{tree}"; }
fresh() {  # fresh <scenario> [junit]: a new bare remote, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -D -q $BRANCH 2> /dev/null   # absent on the remote, as on GitHub before P
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-$1} > $S/$1/gh/scenario; cp ${2:-$S/junit-w1-passed.xml} $S/$1/gh/junit
  print -lr -- $FAILS ${EXTRA_FAIL:-} > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh633.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY633_GRAFTLING=$S/$1/graftling VERIFY633_GREMOTE=$S/$1/gremote.git VERIFY633_GH=$S/$1/gh/gh \
    VERIFY633_EVIDENCE=$S/$1/evidence VERIFY633_POLL_S=1 VERIFY633_APPEAR_S=${2:-10} VERIFY633_DONE_S=30 \
    ${BAD:+VERIFY633_BUNDLE=$BAD}
}
step() {  # step <scenario> <file> <step> [args]: run one step with the knobs, keep the console output
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc ${APPEAR:-10}) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc ${APPEAR:-10}) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
real_state() { git -C $REAL for-each-ref --format='%(refname) %(objectname)' refs/heads; }
BEFORE=$(real_state)
HEAD_SHA=$(git bundle list-heads $BUNDLE refs/heads/$BRANCH | cut -d' ' -f1)

# PASS: the run shows exactly the listed failures and every W1 test passed.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# FAIL: a listed W1 entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh w1-passes; step w1-passes w1-passes-P.txt P
cp $S/w1-passes/evidence/run-51000000000-a1/observed-expected.txt $OUT/w1-passes-observed-expected.txt
# FAIL: one of the new W1 tests fails on the runner.
FAKE_SCENARIO=matched EXTRA_FAIL=$NEWFAIL fresh newtest-fails; step newtest-fails newtest-fails-P.txt P
# FAIL: the Windows-only W1 tests skip (as on macOS) instead of running.
FAKE_SCENARIO=matched fresh newtest-skipped $JUNIT; step newtest-skipped newtest-skipped-P.txt P
FAKE_SCENARIO=setup-fail fresh setup-fail; step setup-fail setup-fail-P.txt P
# Re-run of a failed attempt: attempt 1 as w1-passes, attempt 2 as matched.
FAKE_SCENARIO=rerun fresh rerun; step rerun rerun-P.txt P; step rerun rerun-X.txt X 51000000000
APPEAR=4; FAKE_SCENARIO=timeout fresh timeout; step timeout timeout-P.txt P; APPEAR=10
# STOP: a local branch in the graftling clone that is not an ancestor of the bundle head (never overwritten).
fresh guard; git -C $S/guard/graftling branch -q $BRANCH $(diverged_commit $S/guard/graftling); step guard guard-local-00.txt 00
# STOP: the remote branch is not an ancestor of the bundle head (never forced; nothing pushed).
fresh diverged; git -C $S/diverged/gremote.git update-ref refs/heads/$BRANCH $(diverged_commit $S/diverged/gremote.git)
step diverged diverged-P.txt P
print -r -- "--- after P: remote $(git -C $S/diverged/gremote.git rev-parse $BRANCH) (the diverged commit; unchanged)" >> $OUT/diverged-P.txt
# PASS: local branch at the base (an ancestor): P fast-forwards it from the bundle.
fresh ff-local; git -C $S/ff-local/graftling branch -q $BRANCH $BASE
step ff-local ff-local-00.txt 00; step ff-local ff-local-P.txt P
print -r -- "--- after P: clone $(git -C $S/ff-local/graftling rev-parse $BRANCH), remote $(git -C $S/ff-local/gremote.git rev-parse $BRANCH)" >> $OUT/ff-local-P.txt
# 00 not ready, P STOP: a bundle whose head also changes README.md and the workflow's job timeout.
git clone -q --no-hardlinks $REAL $S/badsrc
git -C $S/badsrc fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} && git -C $S/badsrc checkout -q $BRANCH
$PY -I -c '
import sys; from pathlib import Path
root = Path(sys.argv[1])
(root / "README.md").write_text((root / "README.md").read_text() + "\nrehearsal: a path outside the allowed set\n")
wf = root / ".github/workflows/windows.yml"
wf.write_text(wf.read_text().replace("timeout-minutes: 90", "timeout-minutes: 91", 1))' $S/badsrc
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside W1'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
