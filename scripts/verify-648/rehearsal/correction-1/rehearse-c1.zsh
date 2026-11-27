#!/bin/zsh
# Task 648 correction 1 rehearsal (Engineer only). It reproduces the state Main's next run starts from:
# - after round 1's P, <Harness>/graftling and LUOXIAO92/graftling hold agent/648-graftling-windows-pi at f759fd6c;
# - the new bundle (bbcea6d..57153234) has a head that descends from f759fd6c and from graftling dev bbcea6d (647);
# - the expected list is this Worktree's after merging GraphTraj dev (647 removed the W8 line).
# It runs the real steps.zsh 00 and P (fast-forward path), then 00 again and W, against:
# - a scratch clone whose local branch is at f759fd6c;
# - a local bare remote at f759fd6c;
# - 632's fakegh behind fakegh648.py.
# The P judge reads the JUnit of a real local suite run of 57153234 with simulated Windows skips. One negative case:
# the corrected venv test fails on the runner, and the P verdict must be FAIL.
# Usage: zsh rehearse-c1.zsh <scratch dir outside the Harness> <JUnit file>
emulate -L zsh
setopt pipe_fail no_unset
S=${1:?scratch dir}; JUNIT=${2:?junit file}; HERE=${0:A:h}; STEPS=$HERE/../../steps.zsh
PY=/Users/luoxiao/miniconda3/bin/python3.13
REAL=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/graftling
BRANCH=agent/648-graftling-windows-pi
ROUND1=f759fd6c1611ab4fe812de0eac1663d0551b6352
LIST=$HERE/../../../verify-632/windows-expected.txt
OUT=$HERE/console; mkdir -p $OUT; rm -f $OUT/*.txt(N)
rm -rf $S; mkdir -p $S
# As round 1: the Windows-only tests that skip on macOS run on the runner, so they are made passed.
$PY -I -c '
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.argv[1])
for case in tree.getroot().iter("testcase"):
    for child in list(case):
        if child.tag == "skipped" and child.get("message", "").startswith(("Windows only", "Windows-only")):
            case.remove(child)
tree.write(sys.argv[2], encoding="utf-8", xml_declaration=True)' $JUNIT $S/junit-passed.xml
fresh() {  # fresh <scenario>: remote and local branch at round 1's head, as after Main's first P
  rm -rf $S/$1; mkdir -p $S/$1/gh
  git clone -q --template= --bare --no-hardlinks $REAL $S/$1/gremote.git
  git -C $S/$1/gremote.git update-ref refs/heads/$BRANCH $ROUND1
  git clone -q --template= --no-hardlinks --no-checkout $REAL $S/$1/graftling
  git -C $S/$1/graftling branch -q -f $BRANCH $ROUND1
  git -C $S/$1/graftling remote set-url origin https://github.com/LUOXIAO92/graftling.git
  print -r -- ${FAKE_SCENARIO:-matched} > $S/$1/gh/scenario; cp $S/junit-passed.xml $S/$1/gh/junit
  print -lr -- ${(f)"$(awk -F'\t' '$1=="fail" {print $2}' $LIST)"} ${EXTRA_FAIL:-} > $S/$1/gh/fails
  print -r -- "#!/bin/zsh
exec $PY -I $HERE/../fakegh648.py $S/$1/gh \"\$@\"" > $S/$1/gh/gh; chmod +x $S/$1/gh/gh
}
knobs() {
  print -r -- VERIFY648_GRAFTLING=$S/$1/graftling VERIFY648_GREMOTE=$S/$1/gremote.git VERIFY648_GH=$S/$1/gh/gh \
    VERIFY648_EVIDENCE=$S/$1/evidence VERIFY648_POLL_S=1 VERIFY648_APPEAR_S=10 VERIFY648_DONE_S=30
}
step() {  # step <scenario> <file> <step> [args]
  local sc=$1 file=$2; shift 2
  print -r -- "\$ $(knobs $sc) zsh steps.zsh $*" > $OUT/$file
  env $(knobs $sc) zsh $STEPS "$@" >> $OUT/$file 2>&1; print -r -- "[exit $?]" >> $OUT/$file
  print -r -- "--- $file"; tail -2 $OUT/$file
}
real_state() { git -C $REAL for-each-ref --format='%(refname) %(objectname)' refs/heads; }
BEFORE=$(real_state)
# PASS: 00 sees both branches at f759fd6c, an ancestor; P fetches and pushes fast-forward, then judges.
fresh ancestor; step ancestor ancestor-00.txt 00; step ancestor ancestor-P.txt P
print -r -- "--- after P: clone $(git -C $S/ancestor/graftling rev-parse $BRANCH), remote $(git -C $S/ancestor/gremote.git rev-parse $BRANCH)" >> $OUT/ancestor-P.txt
step ancestor ancestor-00-again.txt 00; step ancestor ancestor-W.txt W
# FAIL: the corrected venv test fails on the runner; only P's verdict can show it.
EXTRA_FAIL=tests/test_pi_windows_648.py::test_pi_host_from_a_venv_runs_as_a_direct_child_of_pi fresh venv-fails
step venv-fails venv-fails-P.txt P
AFTER=$(real_state)
{ print -r -- "real graftling branches before rehearsal:"; print -r -- $BEFORE; print -r -- "after:"; print -r -- $AFTER
  [[ $BEFORE == $AFTER ]] && print -r -- "UNCHANGED (the rehearsal wrote only scratch clones)" || print -r -- "CHANGED"; } > $OUT/real-graftling-untouched.txt
tail -1 $OUT/real-graftling-untouched.txt
