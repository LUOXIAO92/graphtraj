#!/bin/zsh
# Rehearsal of the 528 correction (product guard with one allowed test file, step Gt, GR on G+Gt), before 529 exists.
# A scratch clone of this Worktree under $TMPDIR gets a stand-in fix commit that edits only
# tests/test_pi_generic_execution.py (selects the agent directory with is_dir()). steps.zsh runs from THIS Worktree's
# scripts with ADOPT528_WT pointing at the clone. B reads the real annotated v0.6.2 (read only); production's
# .venv-runtime is only read (B's Requires-Dist check, G's venv copies click/yaml/websockets). GR judges a COPY of
# Main's real G run (adoption/G-8267f9e5-20261119T235550). Gt runs the real test file with the repository fixtures.
#   zsh scripts/adopt-528/rehearse-Gt.zsh   (→ rehearsal-Gt.txt)
set -u
SD=${0:A:h}
WT0=${SD:h:h}
F=${${TMPDIR:-/tmp}:A}/adopt528-rehearsal-gt   # resolved (/private/tmp): pi_parity_scenarios normalises venv paths
FH=$F/project
REALH=/Users/luoxiao/workspace/you-are-a-product-architect-delivery
REALG=$REALH/.graphtraj/core/state/tasks/528-production-adoption-graftling-0-6-2/adoption/G-8267f9e5-20261119T235550
TASK=528-production-adoption-graftling-0-6-2
C=$F/wt
export ADOPT528_H=$FH ADOPT528_BASE=$FH/tmp/528 ADOPT528_RT=$REALH/.venv-runtime ADOPT528_WT=$C ADOPT528_G=$REALH/graftling ADOPT528_KNOWN=$REALH/.graphtraj/core/state/tasks ADOPT528_PNPM_SHIM=$F/no-shim
W=$FH/.graphtraj/core/state/tasks/$TASK/adoption
RW=$W/raw-8267f9e5
T=tests/test_pi_generic_execution.py
steps() { zsh $SD/steps.zsh "$@"; }
head1() { print -r -- ""; print -r -- "======== $*"; }
gitc() { git -C $C -c user.name=rehearsal -c user.email=rehearsal@invalid "$@"; }
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }

head1 "empty base $F; scratch clone of the Worktree; stand-in fix commit (only $T)"
rm -rf $F; mkdir -p $F/tpl $FH
zsh -n $SD/steps.zsh; check "zsh -n steps.zsh" [ $? -eq 0 ]
git clone -q --template=$F/tpl $WT0 $C || exit 1
BASEC=$(git -C $C rev-parse HEAD)
check "clone at the Worktree's committed HEAD; src/tests/plugins = 8267f9e5" sh -c "[ -z \"\$(git -C $C diff --name-only 8267f9e5 HEAD -- src tests plugins)\" ]"
/usr/bin/sed -i '' "s|directory = next((data / 'native').iterdir())|directory = next(path for path in (data / 'native').iterdir() if path.is_dir())|" $C/$T
gitc commit -qam "Stand-in for 529: select the agent directory under native/ (rehearsal only)"
FIXC=$(git -C $C rev-parse HEAD)
git -C $C show --stat --format='%H %s' HEAD | head -4
gitc branch fix

head1 "B through the guard (positive) and the old G judged alone"
steps B > $F/B.out 2>&1; check "B exit 0 with the stand-in" [ $? -eq 0 ]
grep -E '^(git diff|product guard|STOP)' $F/B.out
check "B guard: one allowed difference, F = the stand-in, subject printed" grep -q "^product guard: one allowed difference $T by fix commit F=$FIXC: Stand-in for 529" $F/B.out
mkdir -p $W; cp -Rp $REALG $W/; print -r -- $W/${REALG:t} > $W/G-latest
check "copy of Main's real G holds the one NEW failure" grep -q "FAILED $T::test_task_free_child_launches_messages_and_continues" $W/${REALG:t}/suite.txt

head1 "negative: no Gt yet -> GR not PASS"
steps GR > $F/GR-noGt.out 2>&1; GN=$?
grep -E '^(Gt run|CHECK|  (NEW|fixed))' $F/GR-noGt.out
check "GR without Gt: exit 1, G+Gt FAIL, the test stays NEW" sh -c "[ $GN -ne 0 ] && grep -q '^CHECK 528 G+Gt no NEW failure: FAIL' $F/GR-noGt.out && grep -q '^  NEW  $T::test_task_free_child' $F/GR-noGt.out"

head1 "Gt through the real entry, VERIFY528_REPEAT=3 (real runs of $T with the repository fixtures)"
VERIFY528_REPEAT=3 steps Gt > $F/Gt.out 2>&1; GT=$?; cat $F/Gt.out
check "Gt exit 0; guard found F; temp root outside the Harness; graftling 0.6.2 with ignore_in_git" sh -c "[ $GT -eq 0 ] && grep -q 'fix commit F=$FIXC' $F/Gt.out && grep -q 'TMPDIR of the run is outside the Harness: yes' $F/Gt.out && grep -q 'verify-528-Gt-' $F/Gt.out && grep -q 'graftling 0.6.2 .*526 ignore_in_git: True' $F/Gt.out"
check "Gt: three runs, each with its own basetemp and exit line" sh -c "[ \$(grep -c '^Gt run [123]/3: .*passed.*| exit=' $F/Gt.out) -eq 3 ]"
check "Gt: native/ of run 1 lists .gitignore beside the agent directory" grep -qE '^  bt-1/.*native: .*\.gitignore.*agent-|^  bt-1/.*native: .*agent-.*\.gitignore' $F/Gt.out
steps GR > $F/GR.out 2>&1; GRR=$?
grep -E '^(Gt |CHECK|product guard|  (NEW|fixed|known|Gt run))' $F/GR.out
check "GR: the G failure is 'fixed (529 ${FIXC[1,8]}…)', G+Gt PASS, exit 0" sh -c "[ $GRR -eq 0 ] && grep -q '^  fixed (529 ${FIXC[1,8]}; passed in every Gt repeat)  $T::test_task_free_child_launches_messages_and_continues' $F/GR.out && grep -q '^CHECK 528 G+Gt no NEW failure: PASS' $F/GR.out"
check "GR kept the earlier GR result" sh -c "ls $RW/GR-*.txt > /dev/null 2>&1"
print -r -- 11111111-2222-3333-4444-555555555555 > $FH/tmp/528/main.session   # Mpre needs a Main id (fake)
steps Mpre > $F/Mpre.out 2>&1
check "Mpre shows the G+Gt PASS" grep -q '^GR: PASS (CHECK 528 G+Gt no NEW failure: PASS)' $F/Mpre.out
GOODGT=$(cat $W/Gt-latest)

head1 "negative: Gt with a failing repeat (forced fail, still only $T) -> GR FAIL"
/usr/bin/sed -i '' "s|directory = next(path for path in (data / 'native').iterdir() if path.is_dir())|directory = next(path for path in (data / 'native').iterdir() if path.is_dir()); assert False, 'rehearsal forced fail'|" $C/$T
gitc commit -qam "Rehearsal: forced fail in the stand-in test"
VERIFY528_REPEAT=3 steps Gt > $F/Gt-fail.out 2>&1; grep -E '^Gt run' $F/Gt-fail.out
steps GR > $F/GR-fail.out 2>&1; GF=$?; grep -E '^(Gt |CHECK|  (NEW|fixed|Gt run))' $F/GR-fail.out
check "GR with failing Gt repeats: exit 1, Gt runs show NEW, G+Gt FAIL" sh -c "[ $GF -ne 0 ] && grep -q '^  Gt run 1: NEW  $T::test_task_free_child' $F/GR-fail.out && grep -q '^  NEW  $T::test_task_free_child' $F/GR-fail.out && grep -q '^CHECK 528 G+Gt no NEW failure: FAIL' $F/GR-fail.out"
gitc reset -q --hard fix

head1 "negative: the good Gt but too few repeats (1) -> GR FAIL"
VERIFY528_REPEAT=1 steps Gt > $F/Gt-one.out 2>&1
steps GR > $F/GR-one.out 2>&1; G1=$?
check "GR with a 1-repeat Gt: exit 1, G+Gt FAIL" sh -c "[ $G1 -ne 0 ] && grep -q 'repeats 1/1 (need >= 3, all run: NO)' $F/GR-one.out && grep -q '^CHECK 528 G+Gt no NEW failure: FAIL' $F/GR-one.out"

head1 "negative: an extra src change after the fix -> STOP"
print '# rehearsal drift' >> $C/src/graphtraj/__init__.py; gitc commit -qam "Rehearsal: extra src change"
steps Gt > $F/Gt-src.out 2>&1; GS=$?; grep -E '^STOP' $F/Gt-src.out
check "Gt STOPs on an extra src change" sh -c "[ $GS -ne 0 ] && grep -q '^STOP: src/tests/plugins differ from 8267f9e5 in more than $T: .*src/graphtraj/__init__.py' $F/Gt-src.out"
print -r -- $GOODGT > $W/Gt-latest
steps GR > $F/GR-src.out 2>&1; GSR=$?
check "GR with that tree: guard STOP, no fix accepted, G+Gt FAIL" sh -c "[ $GSR -ne 0 ] && grep -q '^product guard STOP' $F/GR-src.out && grep -q '^CHECK 528 G+Gt no NEW failure: FAIL' $F/GR-src.out"
gitc reset -q --hard fix

head1 "negative: the fix commit also touches another file (reverted later, so only F's own diff shows it) -> STOP"
gitc reset -q --hard $BASEC
/usr/bin/sed -i '' "s|directory = next((data / 'native').iterdir())|directory = next(path for path in (data / 'native').iterdir() if path.is_dir())|" $C/$T
print '# rehearsal: second file' >> $C/tests/test_agent_runner_cleanup.py
gitc commit -qam "Rehearsal: fix that also touches another test"
git -C $C checkout -q HEAD~1 -- tests/test_agent_runner_cleanup.py; gitc commit -qm "Rehearsal: revert the other file only"
git -C $C log --format='%h %s' -3; git -C $C diff --name-only 8267f9e5 HEAD -- src tests plugins
steps Gt > $F/Gt-mixed.out 2>&1; GM=$?; grep -E '^(STOP|product guard)' $F/Gt-mixed.out
check "Gt STOPs when the fix commit also changed another file" sh -c "[ $GM -ne 0 ] && grep -q '^STOP: fix commit .* also changes .*tests/test_agent_runner_cleanup.py' $F/Gt-mixed.out"
gitc reset -q --hard fix

head1 "no difference at all (today's tree): the guard passes as before, with no fix; GR then grants no 'fixed'"
gitc reset -q --hard $BASEC
VERIFY528_REPEAT=x steps Gt > $F/Gt-none.out 2>&1   # stops at the repeat check, after the guard
check "guard with no difference: 'no difference from 8267f9e5 (no fix commit)', no STOP from the guard" sh -c "grep -q '^product guard: no difference from 8267f9e5 (no fix commit)' $F/Gt-none.out && ! grep -q '^STOP: src/tests' $F/Gt-none.out"
print -r -- $GOODGT > $W/Gt-latest
steps GR > $F/GR-none.out 2>&1; GNO=$?
check "GR on today's tree with the stand-in's Gt: fix differs, G+Gt FAIL" sh -c "[ $GNO -ne 0 ] && grep -q 'guard fix none | same: NO' $F/GR-none.out && grep -q '^CHECK 528 G+Gt no NEW failure: FAIL' $F/GR-none.out"
gitc reset -q --hard fix

print -r -- ""
print -r -- "REHEARSAL SUMMARY: $COUNT checks, $([[ $FAILED == 0 ]] && print 'all PASS' || print 'some FAIL')"
exit $FAILED
