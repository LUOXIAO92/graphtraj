#!/bin/zsh
# Task 648 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh648.py around 632's fakegh.py), chosen
# only through VERIFY648_* knobs. The results are judged against the real scripts/verify-632/windows-expected.txt as
# it stands, and, for two scenarios, against a copy another Task changed. Modelled on verify-639/rehearsal/rehearse.zsh.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from the macOS candidate run with simulated
#        Windows skips (verify-632/evidence/macos/simulate_windows_skips.py)>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/648-graftling-windows-pi
BASE=eb5ad8e5b080f2cc0c826f8d0fe7c54882d96866
BUNDLE=$HERE/../graftling-648.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NEWTESTS=$HERE/../new-tests.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the Windows-only tests skip ("Windows only: ...", "Windows-only: ..."); on the runner they run, so the
# stand-in's artifact starts from the macOS run with those made passed. Every other W10 test runs on macOS.
# For newtest-skipped, the Pi host shim test is made skipped with a 'POSIX-only: ' reason (a skip the 632 judge
# allows), so only the W10 test check can catch it.
SKIPPED_ONE=tests/test_pi_windows_648.py::test_pi_host_through_the_shim_serves_an_mcp_call_and_ends_at_stdin_eof
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
# Failing in the stand-in run: every `fail` entry of the list in use (mismatch makes the first one pass).
fails_of() { awk -F'\t' '$1=="fail" {print $2}' $1; }
diverged_commit() { git -C $1 commit-tree -p $BASE -m diverged "$BASE^{tree}"; }
fresh() {  # fresh <scenario> [junit]: a new bare remote, scratch graftling clone and fake gh state
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --template= --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -D -q $BRANCH 2> /dev/null   # absent on the remote, as on GitHub before P
  git clone -q --template= --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-$1} > $S/$1/gh/scenario; cp ${2:-$S/junit-passed.xml} $S/$1/gh/junit
  print -lr -- ${(f)"$(fails_of ${BADLIST:-$LIST})"} ${EXTRA_FAIL:-} > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh648.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY648_GRAFTLING=$S/$1/graftling VERIFY648_GREMOTE=$S/$1/gremote.git VERIFY648_GH=$S/$1/gh/gh \
    VERIFY648_EVIDENCE=$S/$1/evidence VERIFY648_POLL_S=1 VERIFY648_APPEAR_S=${2:-10} VERIFY648_DONE_S=30 \
    ${BAD:+VERIFY648_BUNDLE=$BAD} ${BADLIST:+VERIFY648_EXPECTED=$BADLIST}
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

# PASS: the run shows exactly the listed failure and every W10 test passed.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# PASS: the same run written as the Windows runner writes it (backslash paths).
FAKE_SCENARIO=winpaths fresh winpaths; step winpaths winpaths-P.txt P
# FAIL: a listed entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh listed-passes; step listed-passes listed-passes-P.txt P
# FAIL: one W10 test fails on the runner (unexpected failure and W10 test check).
FAKE_SCENARIO=matched EXTRA_FAIL=$(grep -v '^#' $NEWTESTS | sed -n 7p) fresh newtest-fails; step newtest-fails newtest-fails-P.txt P
# FAIL: the Pi host shim test skips with an allowed 'POSIX-only: ' reason: only the W10 test check catches it.
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
# 00 not ready, P STOP: a bundle whose head also changes CHANGELOG.md and the workflow's job timeout.
git clone -q --template= --no-hardlinks $REAL $S/badsrc
git -C $S/badsrc fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} && git -C $S/badsrc checkout -q $BRANCH
$PY -I -c '
import sys; from pathlib import Path
root = Path(sys.argv[1])
(root / "CHANGELOG.md").write_text((root / "CHANGELOG.md").read_text() + "\nrehearsal: a path outside the allowed set\n")
wf = root / ".github/workflows/windows.yml"
wf.write_text(wf.read_text().replace("timeout-minutes: 90", "timeout-minutes: 91", 1))' $S/badsrc
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside W10'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# 00 not ready, P STOP: the list gains a W10 line for a W10 test (this Task's own lines are none).
{ cat $LIST; print -r -- "fail	tests/test_pi_windows_648.py::test_pi_host_from_a_venv_runs_as_a_direct_child_of_pi	x:1	W10 (648)	rehearsal: an added own line"; } > $S/own-line-list.txt
BADLIST=$S/own-line-list.txt; fresh own-line; step own-line own-line-00.txt 00
step own-line own-line-P.txt P; unset BADLIST
print -r -- "--- after P: remote $(git -C $S/own-line/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/own-line-P.txt
# PASS: another Task changed the list (its W8 line removed, a W11 line added, its test failing in the run): 00 and P
# judge the list as it stands, not a fixed copy.
{ grep -v '	W8 ' $LIST; print -r -- "fail	tests/test_dsh_live.py::test_interrupted_stream_replay_and_native_final_link	src/graftling/dsh/x.py:1	W11 (649)	rehearsal: another Task's line"; } > $S/other-task-list.txt
BADLIST=$S/other-task-list.txt; FAKE_SCENARIO=matched fresh other-task; step other-task other-task-00.txt 00
step other-task other-task-P.txt P; unset BADLIST
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
