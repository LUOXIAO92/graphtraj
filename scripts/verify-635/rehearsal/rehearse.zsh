#!/bin/zsh
# Task 635 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh635.py around 632's fakegh.py), chosen
# only through VERIFY635_* knobs. The results are judged against the real scripts/verify-632/windows-expected.txt as
# this Task edits it.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS candidate run with simulated
#        Windows skips (verify-632/evidence/macos/simulate_windows_skips.py)>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/635-graftling-windows-process-tree
# graftling dev with W2 (634) and W6 (638) integrated; the candidate merges it (635 correction 2).
BASE=d5fb80c7cf5d85a19971c434e7f247568ad22bef
BUNDLE=$HERE/../graftling-635.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the five Windows-only W3 tests skip ("Windows only: ..."); on the runner they must pass. The stand-in's
# artifact starts from the macOS run with those made passed; newtest-skipped keeps them skipped. W2's (634) Windows-only
# tests ("Windows-only: ...") run on the runner too, so they are made passed the same way (correction 1).
$PY -I -c '
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.argv[1])
for case in tree.getroot().iter("testcase"):
    for child in list(case):
        if child.tag == "skipped" and child.get("message", "").startswith(("Windows only", "Windows-only")):
            case.remove(child)
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-w3-passed.xml
# Failing in the stand-in run: every `fail` entry of the edited list, a line this Task moved first (mismatch makes
# the first one pass: a listed entry that unexpectedly passes). It passes in the simulated JUnit.
MOVED=tests/test_envelope_validation_555.py::test_agents_mcp_reads_files_inside_the_verified_session_cwd
FAILS=($MOVED ${(f)"$(awk -F'\t' -v moved=$MOVED '$1=="fail" && $2!=moved {print $2}' $LIST)"})
NEWFAIL=tests/test_process_tree_635.py::test_windows_a_breakaway_attempt_stays_in_the_job
diverged_commit() { git -C $1 commit-tree -p $BASE -m diverged "$BASE^{tree}"; }
fresh() {  # fresh <scenario> [junit]: a new bare remote, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -D -q $BRANCH 2> /dev/null   # absent on the remote, as on GitHub before P
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-$1} > $S/$1/gh/scenario; cp ${2:-$S/junit-w3-passed.xml} $S/$1/gh/junit
  print -lr -- $FAILS ${EXTRA_FAIL:-} > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh635.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY635_GRAFTLING=$S/$1/graftling VERIFY635_GREMOTE=$S/$1/gremote.git VERIFY635_GH=$S/$1/gh/gh \
    VERIFY635_EVIDENCE=$S/$1/evidence VERIFY635_POLL_S=1 VERIFY635_APPEAR_S=${2:-10} VERIFY635_DONE_S=30 \
    ${BAD:+VERIFY635_BUNDLE=$BAD} ${BADLIST:+VERIFY635_EXPECTED=$BADLIST}
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

# PASS: the run shows exactly the listed failures and every W3 test passed.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# FAIL: a kept W3 entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh w3-passes; step w3-passes w3-passes-P.txt P
cp $S/w3-passes/evidence/run-51000000000-a1/observed-expected.txt $OUT/w3-passes-observed-expected.txt
# FAIL: one of the new W3 tests fails on the runner.
FAKE_SCENARIO=matched EXTRA_FAIL=$NEWFAIL fresh newtest-fails; step newtest-fails newtest-fails-P.txt P
# FAIL: the Windows-only W3 tests skip (as on macOS) instead of running.
FAKE_SCENARIO=matched fresh newtest-skipped $JUNIT; step newtest-skipped newtest-skipped-P.txt P
FAKE_SCENARIO=setup-fail fresh setup-fail; step setup-fail setup-fail-P.txt P
# Re-run of a failed attempt: attempt 1 as w3-passes, attempt 2 as matched.
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
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside W3'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# 00 not ready, P STOP: the expected list with one moved line left at W3 (635) instead of Main's owner (correction 2).
awk -F'\t' -v OFS='\t' -v moved=$MOVED '$1=="fail" && $2==moved {$4="W3 (635)"} {print}' $LIST > $S/bad-owner-list.txt
BADLIST=$S/bad-owner-list.txt; fresh bad-owner; step bad-owner bad-owner-00.txt 00; step bad-owner bad-owner-P.txt P
unset BADLIST
print -r -- "--- after P: remote $(git -C $S/bad-owner/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/bad-owner-P.txt
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
