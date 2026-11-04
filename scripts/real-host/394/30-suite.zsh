#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 30-suite: the whole test suite at COMMIT, compared with the base's failures.
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/30-suite.zsh
#
# 392's step 70: a clean clone and venv, run_test_shards.py, an allowlisted environment (env -i with HOME,
# PATH, TMPDIR, LANG). The base list is 392's saved run of the same code as cb29c3a4 in this Terminal;
# when that record is missing or of other code, the suite runs at the base here too. A failure new at
# COMMIT is run once more at COMMIT and once at the base, so a flaky or machine-bound one is told apart.
# Downloads PyYAML, click, websockets, pytest and setuptools into $AG/suite*/venv only. No model call, no key.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 30-suite 35 none 'new-failures.txt is empty (no failure at COMMIT that the base lacks), and the native-sandbox test says passed'
if [[ -n ${AGENTS_394_DRY_BIN:-} && -z ${AGENTS_394_DRY_SUITE:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi
# A short path: tests make Unix sockets under it, and a socket path holds 104 bytes.
SHORT=${AGENTS_394_DRY_SHORT:-/tmp/agents-394-suite}
[[ -e $SHORT ]] && mv $SHORT $SHORT.$STAMP
mkdir -p $SHORT

# `suite_tree <directory> <commit>`: a clone at that commit and a venv with its package(s) editable.
suite_tree() {
  local dir=$1 commit=$2 package
  [[ -e $dir ]] && mv $dir $dir.$STAMP
  mkdir -p $dir/home
  git clone -q --no-hardlinks $WT $dir/clone
  git -C $dir/clone checkout -q --detach $commit
  package=graftling
  [[ -d $dir/clone/src/graftling ]] || package=agent_swarm
  $PY -m venv $dir/venv
  (cd $dir/clone && $dir/venv/bin/python -m pip install -q --disable-pip-version-check -e ./src/$package -e . pytest setuptools) \
    > $OUT/install-${dir:t}.txt 2>&1 || fail "pip install in $dir failed; see install-${dir:t}.txt"
  print -r -- $commit > $dir/installed-commit
}
# `test_env <directory>`: the allowlisted environment of that tree.
test_env() {
  TESTENV=(env -i HOME=$1/home PATH=$1/venv/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$SHORT
           LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1)
}
# `whole_suite <directory> <log directory>`: run_test_shards.py, at most 60 minutes; sets COUNTS.
whole_suite() {
  local dir=$1 logs=$2 code=0
  test_env $dir
  (cd $dir/clone && bounded 3600 $TESTENV $dir/venv/bin/python scripts/run_test_shards.py --shards 4 --log-dir $logs -- -o faulthandler_timeout=300) \
    2>&1 | tee $logs.console.txt | tail -5 || code=$?
  COUNTS=$(grep -E '[0-9]+ (passed|failed)' $logs.console.txt | tail -1)
  [[ -f $logs/failures.txt ]] || fail "the suite in $dir left no failures.txt (exit $code); see ${logs:t}.console.txt"
}
# `rerun <directory> <ids file> <label>`: those ids once more; prints the ids that failed again.
rerun() {
  local dir=$1 ids=$2 label=$3
  test_env $dir
  (cd $dir/clone && bounded 1800 $TESTENV $dir/venv/bin/python -m pytest -p no:cacheprovider -q -rfE -o faulthandler_timeout=300 ${(f)"$(<$ids)"}) \
    > $OUT/rerun-$label.txt 2>&1 || true
  sed -E -n 's/^(FAILED|ERROR) ([^ ]+).*/\2/p' $OUT/rerun-$label.txt | sort -u
}
# failures.txt lines are '<FAILED|ERROR> <id>'; the lists below hold the ids only, sorted.
# Dry run only: AGENTS_394_DRY_SUITE names a directory of fixtures standing for the runs (head.txt and
# base.txt in failures.txt form, again-head.txt and again-base.txt as ids), to check the comparison.
if [[ -n ${AGENTS_394_DRY_SUITE:-} ]]; then
  suite_tree() { mkdir -p $1; print -r -- $2 > $1/installed-commit; }
  whole_suite() { mkdir -p $2; local f=head; [[ ${2:t} == base-logs ]] && f=base; cp $AGENTS_394_DRY_SUITE/$f.txt $2/failures.txt; COUNTS="dry $f"; }
  rerun() { cat $AGENTS_394_DRY_SUITE/again-$3.txt; }
fi
print -r -- "environment names given to the tests: HOME PATH TMPDIR LANG PYTHONDONTWRITEBYTECODE" > $OUT/environment.txt

say "the suite at COMMIT $COMMIT"
HEAD_DIR=$AG/suite
suite_tree $HEAD_DIR $COMMIT
$HEAD_DIR/venv/bin/python -m pip list --disable-pip-version-check 2>/dev/null > $OUT/pip-list.txt || true
whole_suite $HEAD_DIR $OUT/logs
HEAD_COUNTS=$COUNTS
cut -d' ' -f2- $OUT/logs/failures.txt | sort -u > $OUT/head-failures.txt
note "suite at $COMMIT: $HEAD_COUNTS; failing ids: $(wc -l < $OUT/head-failures.txt | tr -d ' ')"

say "the base's failures ($BASE)"
BASE_RECORD=${AGENTS_394_DRY_BASE_RECORD:-}
[[ -n $BASE_RECORD ]] || BASE_RECORD=$HARNESS/.graphtraj/core/state/tasks/392-agents-standalone-combined-acceptance/realhost/70-suite
RECORD_CODE=$(sed -n 's/^step 70-suite code \([0-9a-f]*\) .*/\1/p' $BASE_RECORD/run.txt 2>/dev/null || true)
BASE_DIR=$AG/suite-base
if [[ -n $RECORD_CODE && -f $BASE_RECORD/finished.txt && -f $BASE_RECORD/logs/failures.txt ]] \
    && git -C $WT diff --quiet $RECORD_CODE $BASE -- . ':!scripts/real-host/392' 2>/dev/null; then
  cut -d' ' -f2- $BASE_RECORD/logs/failures.txt | sort -u > $OUT/base-failures.txt
  BASE_COUNTS=$(grep -E '[0-9]+ (passed|failed)' $BASE_RECORD/console.txt | tail -1)
  check PASS "base list: 392's saved suite run of $RECORD_CODE, the same code as $BASE: $BASE_COUNTS; failing ids: $(wc -l < $OUT/base-failures.txt | tr -d ' ')"
else
  note "392's saved suite run is missing or of other code (${RECORD_CODE:-none}); the suite runs at $BASE here"
  suite_tree $BASE_DIR $BASE
  whole_suite $BASE_DIR $OUT/base-logs
  BASE_COUNTS=$COUNTS
  cut -d' ' -f2- $OUT/base-logs/failures.txt | sort -u > $OUT/base-failures.txt
  check PASS "base list: the suite at $BASE in this run: $BASE_COUNTS; failing ids: $(wc -l < $OUT/base-failures.txt | tr -d ' ')"
fi
note "counts: base $BASE_COUNTS; COMMIT $HEAD_COUNTS"

say "failures at COMMIT that the base lacks"
comm -23 $OUT/head-failures.txt $OUT/base-failures.txt > $OUT/new-at-head.txt
if [[ ! -s $OUT/new-at-head.txt ]]; then
  : > $OUT/new-failures.txt
  check PASS "no new failures: every failing id at $COMMIT also fails at the base ($(wc -l < $OUT/head-failures.txt | tr -d ' ') at COMMIT)"
else
  note "$(wc -l < $OUT/new-at-head.txt | tr -d ' ') ids fail at COMMIT and not in the base list; each runs once more at COMMIT and at the base"
  rerun $HEAD_DIR $OUT/new-at-head.txt head > $OUT/again-at-head.txt
  [[ -f $BASE_DIR/installed-commit && $(<$BASE_DIR/installed-commit) == $BASE ]] || suite_tree $BASE_DIR $BASE
  rerun $BASE_DIR $OUT/new-at-head.txt base > $OUT/again-at-base.txt
  comm -12 $OUT/new-at-head.txt $OUT/again-at-head.txt | comm -23 - $OUT/again-at-base.txt > $OUT/new-failures.txt
  comm -23 $OUT/new-at-head.txt $OUT/again-at-head.txt > $OUT/flaky.txt
  comm -12 $OUT/again-at-head.txt $OUT/again-at-base.txt > $OUT/fail-at-both.txt
  [[ -s $OUT/flaky.txt ]] && note "passed when run again at COMMIT (flaky): $(tr '\n' ' ' < $OUT/flaky.txt | cut -c1-600)"
  [[ -s $OUT/fail-at-both.txt ]] && note "fail again at both COMMIT and the base (not caused by 394): $(tr '\n' ' ' < $OUT/fail-at-both.txt | cut -c1-600)"
  if [[ -s $OUT/new-failures.txt ]]; then
    check FAIL "new failures at $COMMIT (fail twice at COMMIT, pass at the base): $(wc -l < $OUT/new-failures.txt | tr -d ' '); new-failures.txt: $(tr '\n' ' ' < $OUT/new-failures.txt | cut -c1-600)"
  else
    check PASS "no new failures: each id new in the full run passed when run again or fails at the base too; see flaky.txt and fail-at-both.txt"
  fi
fi

if [[ -n ${AGENTS_394_DRY_SUITE:-} ]]; then note 'dry run: the native-sandbox test not run'; step_end; fi
say "the native-sandbox test must say passed, not skipped"
test_env $HEAD_DIR
(cd $HEAD_DIR/clone && bounded 300 $TESTENV $HEAD_DIR/venv/bin/python -m pytest -p no:cacheprovider -q -rA tests/test_runtime_resources.py::test_explicit_read_access_is_enforced_by_native_sandbox) > $OUT/native-sandbox.txt 2>&1 || true
grep -q '^PASSED' $OUT/native-sandbox.txt && check PASS "test_explicit_read_access_is_enforced_by_native_sandbox: passed" \
  || check FAIL "test_explicit_read_access_is_enforced_by_native_sandbox: $(tail -1 $OUT/native-sandbox.txt | cut -c1-200)"
pkill -f "$HEAD_DIR/clone" 2>/dev/null || true
pkill -f "$BASE_DIR/clone" 2>/dev/null || true
step_end
