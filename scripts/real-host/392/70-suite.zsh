#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 70-suite. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/70-suite.zsh
# The whole test suite in a clean clone and a clean venv, by run_test_shards.py, with an allowlisted environment.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# Nothing of your environment reaches the tests and nothing writes it to a file: env -i with HOME, PATH, TMPDIR, LANG.
# It downloads PyYAML, click, websockets, pytest and setuptools into $AG/suite/venv only. No model call, no key.
step_begin 70-suite 30 none 'the suite ends with its counts and failures.txt saved, the native-sandbox test says passed, and every failure is a line to read'
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: downloads nothing, not run'; step_end; fi
SUITE=$AG/suite
[[ -e $SUITE ]] && mv $SUITE $SUITE.$STAMP
mkdir -p $SUITE/home
# A short path: tests make Unix sockets under it, and a socket path holds 104 bytes.
SHORT=/tmp/agents-392-suite
[[ -e $SHORT ]] && mv $SHORT $SHORT.$STAMP
mkdir -p $SHORT
git clone -q --no-hardlinks $WT $SUITE/clone
git -C $SUITE/clone checkout -q --detach $COMMIT
$PY -m venv $SUITE/venv
(cd $SUITE/clone && $SUITE/venv/bin/python -m pip install -q --disable-pip-version-check -e ./src/agent_swarm -e . pytest setuptools) 2>&1 | tee $OUT/install.txt | tail -3
print -r -- $COMMIT > $SUITE/installed-commit
$SUITE/venv/bin/python -m pip list --disable-pip-version-check 2>/dev/null > $OUT/pip-list.txt
TESTENV=(env -i HOME=$SUITE/home PATH=$SUITE/venv/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$SHORT LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1)
print -r -- "environment names given to the tests: HOME PATH TMPDIR LANG PYTHONDONTWRITEBYTECODE" > $OUT/environment.txt
say "the suite; at most 60 minutes"
CODE=0
(cd $SUITE/clone && bounded 3600 $TESTENV $SUITE/venv/bin/python scripts/run_test_shards.py --shards 4 --log-dir $OUT/logs -- -o faulthandler_timeout=300) 2>&1 | tee $OUT/console.txt | tail -30 || CODE=$?
COUNTS=$(tail -2 $OUT/console.txt | head -1)
check $([[ -s $OUT/logs/failures.txt ]] && print FAIL || print PASS) "suite at $COMMIT: $COUNTS; failing ids in logs/failures.txt: $(wc -l < $OUT/logs/failures.txt 2>/dev/null | tr -d ' ')"
say "the native-sandbox test must say passed, not skipped"
(cd $SUITE/clone && bounded 300 $TESTENV $SUITE/venv/bin/python -m pytest -p no:cacheprovider -q -rA tests/test_runtime_resources.py::test_explicit_read_access_is_enforced_by_native_sandbox) > $OUT/native-sandbox.txt 2>&1 || true
grep -q '^PASSED' $OUT/native-sandbox.txt && check PASS "test_explicit_read_access_is_enforced_by_native_sandbox: passed" \
  || check FAIL "test_explicit_read_access_is_enforced_by_native_sandbox: $(tail -1 $OUT/native-sandbox.txt | cut -c1-200)"
pkill -f "$SUITE/clone" 2>/dev/null || true
step_end
