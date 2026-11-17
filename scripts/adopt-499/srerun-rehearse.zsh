#!/bin/zsh
# Rehearsal of srerun.zsh (keep, compare) in $TMPDIR with fixture files in the real S result shapes. Stub ps.
#   zsh scripts/adopt-499/srerun-rehearse.zsh >> scripts/adopt-499/srerun-rehearsal.txt
set -u
SD=${0:A:h}
F=${TMPDIR:-/tmp}/srerun499-rehearsal
FH=$F/project
R=$FH/.graphtraj/core/state/tasks/499-production-adoption-496-498/adoption/raw-871aaaa9
export ADOPT499_H=$FH ADOPT499_BASE=$FH/tmp/499 ADOPT499_STUB=$F/stub
FAILED=0; COUNT=0
check() { local what=$1; shift; (( COUNT++ )); if "$@"; then print -r -- "REHEARSAL PASS: $what"; else print -r -- "REHEARSAL FAIL: $what"; FAILED=1; fi; }
sr() { zsh $SD/srerun.zsh "$@"; }
rm -rf $F; mkdir -p $F/stub $R/S-shards
print -l '#!/bin/zsh' "[[ -e $F/ps.txt ]] && cat $F/ps.txt; exit 0" > $F/stub/ps; chmod +x $F/stub/ps
print "== srerun rehearsal $(date '+%F %T')"

# Run 1 fixtures (real shapes: S-suite.txt '== totals', 'NEW <id> [label]'; failures.txt 'FAILED <id> - msg').
print -l '== quiet at 11:56:32 start' '== totals: 7 failed, 4174 passed, 69 skipped' 'NEW tests/test_a.py::test_one [unattributed]' \
  'NEW tests/test_b.py::test_two [unattributed]' '== new failures: 7' '== DONE 12:20:00' > $R/S-suite.txt
print -l 'FAILED tests/test_a.py::test_one - AssertionError' 'FAILED tests/test_b.py::test_two - Timeout' > $R/S-shards/failures.txt
for f in S-setup.txt S-setup-imports.txt S-ps.txt S-quiet-ps.txt S2.txt; do print "run1 $f" > $R/$f; done

# keep refuses while an S of ours runs (our test venv's shard runner).
print "8812 1 05:00 $FH/tmp/499/svenv-871aaaa9/bin/python scripts/run_test_shards.py --shards 6" > $F/ps.txt
sr keep > $F/keep-busy.out 2>&1; RC=$?; cat $F/keep-busy.out
check "keep refuses while our S runs (ours: 1); nothing moved" sh -c "[ $RC -ne 0 ] && grep -q '^ours: 1' $F/keep-busy.out && [ ! -e $R/S-run1 ] && [ -e $R/S-suite.txt ]"
# a leftover timer of our test venv is not 'ours' (busy499 rule): keep proceeds.
print "8813 1 2:00:00 $FH/tmp/499/svenv-871aaaa9/bin/python -I -m graphtraj.execution.budget_idle_timer /x 0123 5" > $F/ps.txt
sr keep > $F/keep.out 2>&1; RC=$?; cat $F/keep.out
check "keep moves the 7 existing run 1 files into S-run1 and prints the S command with the real path" sh -c "[ $RC -eq 0 ] && grep -q 'kept 7 of 7' $F/keep.out && [ -f $R/S-run1/S-suite.txt ] && [ -d $R/S-run1/S-shards ] && [ ! -e $R/S-suite.txt ] && grep -q \"next.*: zsh $SD/steps.zsh S \" $F/keep.out"
sr keep > $F/keep2.out 2>&1; RC=$?; cat $F/keep2.out
check "keep refuses when S-run1 already exists" sh -c "[ $RC -ne 0 ] && grep -q 'STOP: .*S-run1 already exists' $F/keep2.out"

# compare: PENDING while run 2 has no '== DONE'.
print '== quiet at 12:40:00 start' > $R/S-suite.txt
sr compare > $F/cmp-pending.out 2>&1; RC=$?; cat $F/cmp-pending.out
check "compare is PENDING with the rerun line before run 2's '== DONE'" sh -c "[ $RC -ne 0 ] && grep -q \"^PENDING: run 2 has no '== DONE'\" $F/cmp-pending.out && grep -q 'srerun.zsh compare' $F/cmp-pending.out"
# compare: run 2 with one recurring id (test_one) and one new id (test_three).
mkdir -p $R/S-shards
print -l '== quiet at 12:40:00 start' '== totals: 2 failed, 4179 passed, 69 skipped' 'NEW tests/test_a.py::test_one [unattributed]' \
  'NEW tests/test_c.py::test_three [unattributed]' '== new failures: 2' '== DONE 13:05:00' > $R/S-suite.txt
print -l 'FAILED tests/test_a.py::test_one - AssertionError' 'ERROR tests/test_c.py::test_three - setup' > $R/S-shards/failures.txt
print 'leftover processes of the suite (never signalled): 0' > $R/S2.txt
sr compare > $F/cmp.out 2>&1; RC=$?; cat $F/cmp.out
check "compare: totals of both runs; test_one FAILED AGAIN, test_two passed; run 2 NEW ids listed; '== run 2 new failures: 2'" sh -c "[ $RC -eq 0 ] && grep -q '^run 1 == totals: 7 failed' $F/cmp.out && grep -q '^run 2 == totals: 2 failed' $F/cmp.out && grep -q '  FAILED AGAIN in run 2: tests/test_a.py::test_one' $F/cmp.out && grep -q '  passed in run 2: tests/test_b.py::test_two' $F/cmp.out && grep -q '  tests/test_c.py::test_three' $F/cmp.out && grep -q '^== run 2 new failures: 2' $F/cmp.out && grep -q 'run 2 S2: leftover processes of the suite (never signalled): 0' $F/cmp.out"
print "\nSRERUN REHEARSAL RESULT: $([[ $FAILED == 0 ]] && print ALL PASS || print SOME FAILED) ($COUNT checks)"
exit $FAILED
