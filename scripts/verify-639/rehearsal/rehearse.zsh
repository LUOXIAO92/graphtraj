#!/bin/zsh
# Task 639 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh639.py around 632's fakegh.py), chosen
# only through VERIFY639_* knobs. The results are judged against the real scripts/verify-632/windows-expected.txt
# (unchanged by this Task). Modelled on verify-637/rehearsal/rehearse.zsh.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS candidate run with simulated
#        Windows skips (verify-632/evidence/macos/simulate_windows_skips.py)>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/639-graftling-windows-codex
BASE=9bbf644321d1746b5f268a94dcff4b1e7a2a92fb
BUNDLE=$HERE/../graftling-639.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NEWTESTS=$HERE/../new-tests.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the Windows-only tests of earlier Tasks skip ("Windows only: ...", "Windows-only: ..."); on the runner
# they run, so the stand-in's artifact starts from the macOS run with those made passed. Every W7 test runs on macOS.
# For newtest-skipped, the Codex host test is made skipped with a 'POSIX-only: ' reason (a skip the 632 judge allows),
# so only the W7 test check can catch it.
SKIPPED_ONE=tests/test_codex_independent_control.py::test_packaged_host_owns_parent_mcp_and_resume
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
tree.write(sys.argv[3], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-passed.xml $S/junit-one-skipped.xml $SKIPPED_ONE
# Failing in the stand-in run: every `fail` entry of the list (mismatch makes the first one pass).
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
exec $PY -I $HERE/fakegh639.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY639_GRAFTLING=$S/$1/graftling VERIFY639_GREMOTE=$S/$1/gremote.git VERIFY639_GH=$S/$1/gh/gh \
    VERIFY639_EVIDENCE=$S/$1/evidence VERIFY639_POLL_S=1 VERIFY639_APPEAR_S=${2:-10} VERIFY639_DONE_S=30 \
    ${BAD:+VERIFY639_BUNDLE=$BAD} ${BADLIST:+VERIFY639_EXPECTED=$BADLIST}
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

# PASS: the run shows exactly the listed failure and every W7 test passed.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# PASS: the same run written as the Windows runner writes it (backslash paths).
FAKE_SCENARIO=winpaths fresh winpaths; step winpaths winpaths-P.txt P
# FAIL: a listed entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh listed-passes; step listed-passes listed-passes-P.txt P
# FAIL: one W7 test fails on the runner (unexpected failure and W7 test check).
FAKE_SCENARIO=matched EXTRA_FAIL=$(grep -v '^#' $NEWTESTS | sed -n 7p) fresh newtest-fails; step newtest-fails newtest-fails-P.txt P
# FAIL: an opened Codex host test skips with an allowed 'POSIX-only: ' reason: only the W7 test check catches it.
FAKE_SCENARIO=matched fresh newtest-skipped $S/junit-one-skipped.xml; step newtest-skipped newtest-skipped-P.txt P
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
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside W7'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# 00 not ready, P STOP: an expected list that differs from a5e5cc92's (this Task must not change it).
{ cat $LIST; print -r -- "fail	tests/test_codex_windows_639.py::test_codex_child_tool_end_stop_and_takeover	x:1	W7 (639)	rehearsal: an added line"; } > $S/changed-list.txt
BADLIST=$S/changed-list.txt; fresh changed-list; step changed-list changed-list-00.txt 00
step changed-list changed-list-P.txt P; unset BADLIST
print -r -- "--- after P: remote $(git -C $S/changed-list/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/changed-list-P.txt
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
