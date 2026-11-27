#!/bin/zsh
# Task 649 rehearsal driver (Engineer only): runs steps.zsh 00/P/W/X against a local bare graftling remote, a scratch
# clone of <Harness>/graftling (never the real one) and the gh stand-in (fakegh649.py around 632's fakegh.py), chosen
# only through VERIFY649_* knobs. The windows-tests results are judged against the real
# scripts/verify-632/windows-expected.txt. Modelled on verify-639/rehearsal/rehearse.zsh.
# Usage: zsh rehearse.zsh <scratch dir outside the Harness> <JUnit file from a macOS run of the candidate's tests with
#        simulated Windows skips: verify-639/evidence/macos/simulated-windows-skips-2ee706eb-junit.xml; graftling
#        eb5ad8e and the 649 candidate change no test since 2ee706eb>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/649-graftling-windows-dsh
BASE=eb5ad8e5b080f2cc0c826f8d0fe7c54882d96866
BUNDLE=$HERE/../graftling-649.bundle
LIST=$HERE/../../verify-632/windows-expected.txt
NOREPLY=(-c user.name=LUOXIAO92 -c user.email=89069722+LUOXIAO92@users.noreply.github.com)
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# On macOS the Windows-only tests of earlier Tasks skip ("Windows only: ...", "Windows-only: ..."); on the runner
# they run, so the stand-in's artifact starts from the macOS run with those made passed.
$PY -I -c '
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.argv[1])
for case in tree.getroot().iter("testcase"):
    for child in list(case):
        if child.tag == "skipped" and child.get("message", "").startswith(("Windows only", "Windows-only")):
            case.remove(child)
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-passed.xml
# Failing in the stand-in run: every `fail` entry of the list (mismatch makes the first one pass).
FAILS=(${(f)"$(awk -F'\t' '$1=="fail" {print $2}' $LIST)"})
diverged_commit() { git -C $1 commit-tree -p $BASE -m diverged "$BASE^{tree}"; }
fresh() {  # fresh <scenario>: a new bare remote, scratch graftling clone and fake gh state (PROBE_CASE: the probe case)
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git branch -D -q $BRANCH 2> /dev/null   # absent on the remote, as on GitHub before P
  git clone -q --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-$1} > $S/$1/gh/scenario; cp $S/junit-passed.xml $S/$1/gh/junit
  print -r -- ${PROBE_CASE:-complete} > $S/$1/gh/probe
  print -lr -- $FAILS > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/fakegh649.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY649_GRAFTLING=$S/$1/graftling VERIFY649_GREMOTE=$S/$1/gremote.git VERIFY649_GH=$S/$1/gh/gh \
    VERIFY649_EVIDENCE=$S/$1/evidence VERIFY649_POLL_S=1 VERIFY649_APPEAR_S=${2:-10} VERIFY649_DONE_S=30 \
    ${BAD:+VERIFY649_BUNDLE=$BAD} ${BADLIST:+VERIFY649_EXPECTED=$BADLIST}
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

# PASS: the run shows exactly the listed failure; the probe artifact is complete and DSH ran.
fresh matched; step matched matched-00.txt 00; step matched matched-P.txt P; step matched matched-00-again.txt 00
step matched matched-W-sha.txt W $HEAD_SHA
step matched matched-W-run.txt W 51000000000
# PASS: the same run written as the Windows runner writes it (backslash paths).
FAKE_SCENARIO=winpaths fresh winpaths; step winpaths winpaths-P.txt P
# PASS: DSH does not run on Windows (install, CLI and service fail): the findings are evidence, not a pass condition.
FAKE_SCENARIO=matched PROBE_CASE=negative fresh probe-negative; step probe-negative probe-negative-P.txt P
# FAIL: the probe script failed while recording (its step failed; owner-death absent).
FAKE_SCENARIO=matched PROBE_CASE=incomplete fresh probe-incomplete; step probe-incomplete probe-incomplete-P.txt P
# FAIL: the probe upload failed; no probe artifact.
FAKE_SCENARIO=matched PROBE_CASE=missing fresh probe-missing; step probe-missing probe-missing-P.txt P
# FAIL: a listed entry passes (unexpected pass), an unlisted test fails, a skip has no prefix.
FAKE_SCENARIO=mismatch fresh listed-passes; step listed-passes listed-passes-P.txt P
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
# 00 not ready, P STOP: a bundle whose head also changes README.md and the windows-tests job's timeout.
git clone -q --no-hardlinks $REAL $S/badsrc
git -C $S/badsrc fetch -q $BUNDLE refs/heads/${BRANCH}:refs/heads/${BRANCH} && git -C $S/badsrc checkout -q $BRANCH
$PY -I -c '
import sys; from pathlib import Path
root = Path(sys.argv[1])
(root / "README.md").write_text((root / "README.md").read_text() + "\nrehearsal: a path outside the allowed set\n")
wf = root / ".github/workflows/windows.yml"
wf.write_text(wf.read_text().replace("timeout-minutes: 90", "timeout-minutes: 91", 1))' $S/badsrc
git -C $S/badsrc $NOREPLY commit -q -am 'rehearsal: changes outside 649'
git -C $S/badsrc bundle create -q $S/bad.bundle $BASE..refs/heads/$BRANCH
BAD=$S/bad.bundle; fresh disallowed; step disallowed disallowed-00.txt 00; step disallowed disallowed-P.txt P; unset BAD
print -r -- "--- after P: remote $(git -C $S/disallowed/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/disallowed-P.txt
# 00 not ready, P STOP: an expected list whose DSH-related lines differ from afaf516d's (phase A changes none).
$PY -I -c '
import sys
text = open(sys.argv[1], encoding="utf-8").read()
old = "skip-allowed\tInstalled DSH and Node are required.\t"
assert text.count(old) == 1
open(sys.argv[2], "w", encoding="utf-8").write(text.replace(old, "skip-allowed\tInstalled DSH and Node are required (changed).\t"))' $LIST $S/dsh-list.txt
BADLIST=$S/dsh-list.txt; fresh dsh-list; step dsh-list dsh-list-00.txt 00; step dsh-list dsh-list-P.txt P; unset BADLIST
print -r -- "--- after P: remote $(git -C $S/dsh-list/gremote.git rev-parse -q --verify $BRANCH || print -r -- absent)" >> $OUT/dsh-list-P.txt
# 00 ready: another Task (647, 648) changed a non-DSH line of the list in parallel; it is only noted.
$PY -I -c '
import sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines(keepends=True)
out = [l for l in lines if not l.startswith("fail\ttests/test_unified_data_root_577.py::test_claude_launcher_logs_into_the_variable")]
assert len(out) == len(lines) - 1
open(sys.argv[2], "w", encoding="utf-8").write("".join(out))' $LIST $S/other-list.txt
BADLIST=$S/other-list.txt; fresh other-list; step other-list other-list-00.txt 00; unset BADLIST
# The real <Harness>/graftling was only read: its branches are the same before and after.
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
