#!/bin/zsh
# Task 637 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh637.py around 632's fakegh.py), chosen
# only through VERIFY637_* knobs. The results are judged against the real scripts/verify-632/windows-expected.txt as
# this Task edits it. Modelled on verify-635/rehearsal/rehearse.zsh.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS candidate run with simulated
#        Windows skips (verify-632/evidence/macos/simulate_windows_skips.py)>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/637-graftling-windows-process-listing
BASE=7609e52089e638c963cc54c28438c99ea3964f99
BUNDLE=$HERE/../graftling-637.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NEWTESTS=$HERE/../new-tests.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the Windows-only tests of earlier Tasks skip ("Windows only: ...", "Windows-only: ..."); on the runner
# they run, so the stand-in's artifact starts from the macOS run with those made passed. Every W5 test already runs on
# macOS. For newtest-skipped, the deleted W5 entry's test is made skipped with a 'POSIX-only: ' reason (a skip the
# 632 judge allows), so only the W5 test check can catch it.
W5DELETED=tests/test_codex_child_interpreter_shutdown_473.py::test_child_ends_completed_after_the_owner_main_thread_returns
$PY -I -c '
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.argv[1])
for case in tree.getroot().iter("testcase"):
    for child in list(case):
        if child.tag == "skipped" and child.get("message", "").startswith(("Windows only", "Windows-only")):
            case.remove(child)
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)
for case in tree.getroot().iter("testcase"):
    if case.get("name") == sys.argv[4].split("::")[1] and case.get("file", "").endswith(sys.argv[4].split("::")[0].split("/")[1]):
        ET.SubElement(case, "skipped", {"type": "pytest.skip", "message": "POSIX-only: rehearsal"}).text = "rehearsal"
tree.write(sys.argv[3], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-passed.xml $S/junit-473-skipped.xml $W5DELETED
# Failing in the stand-in run: every `fail` entry of the edited list (mismatch makes the first one pass: a listed
# entry that unexpectedly passes).
FAILS=(${(f)"$(awk -F'\t' '$1=="fail" {print $2}' $LIST)"})
diverged_commit() { git -C $1 commit-tree -p $BASE -m diverged "$BASE^{tree}"; }
fresh() {  # fresh <scenario> [junit]: a new bare remote, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -D -q $BRANCH 2> /dev/null   # absent on the remote, as on GitHub before P
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-$1} > $S/$1/gh/scenario; cp ${2:-$S/junit-passed.xml} $S/$1/gh/junit
  print -lr -- $FAILS ${EXTRA_FAIL:-} > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh637.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY637_GRAFTLING=$S/$1/graftling VERIFY637_GREMOTE=$S/$1/gremote.git VERIFY637_GH=$S/$1/gh/gh \
    VERIFY637_EVIDENCE=$S/$1/evidence VERIFY637_POLL_S=1 VERIFY637_APPEAR_S=${2:-10} VERIFY637_DONE_S=30 \
    ${BAD:+VERIFY637_BUNDLE=$BAD} ${BADLIST:+VERIFY637_EXPECTED=$BADLIST}
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

# PASS: the run shows exactly the listed failures and every W5 test passed.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# PASS: the same run written as the Windows runner writes it (backslash paths).
FAKE_SCENARIO=winpaths fresh winpaths; step winpaths winpaths-P.txt P
# FAIL: a listed entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh listed-passes; step listed-passes listed-passes-P.txt P
# FAIL: the test whose W5 entry was deleted fails on the runner (unexpected failure and W5 test check).
FAKE_SCENARIO=matched EXTRA_FAIL=$W5DELETED fresh deleted-fails; step deleted-fails deleted-fails-P.txt P
# FAIL: one new W5 test fails on the runner.
FAKE_SCENARIO=matched EXTRA_FAIL=$(grep -v '^#' $NEWTESTS | head -1) fresh newtest-fails; step newtest-fails newtest-fails-P.txt P
# FAIL: the deleted entry's test skips with an allowed 'POSIX-only: ' reason: only the W5 test check catches it.
FAKE_SCENARIO=matched fresh newtest-skipped $S/junit-473-skipped.xml; step newtest-skipped newtest-skipped-P.txt P
FAKE_SCENARIO=setup-fail fresh setup-fail; step setup-fail setup-fail-P.txt P
# Re-run of a failed attempt: attempt 1 as mismatch, attempt 2 as matched.
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
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside W5'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# 00 not ready, P STOP: the expected list with the W5 (637) line still in it (GraphTraj dev 5d5938ad's list).
git -C $HERE show 5d5938ad:scripts/verify-632/windows-expected.txt > $S/unedited-list.txt
BADLIST=$S/unedited-list.txt; fresh unedited-list; step unedited-list unedited-list-00.txt 00
step unedited-list unedited-list-P.txt P; unset BADLIST
print -r -- "--- after P: remote $(git -C $S/unedited-list/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/unedited-list-P.txt
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
