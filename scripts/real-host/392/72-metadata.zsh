#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 72-metadata. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/72-metadata.zsh
# 413's opt-in metadata tests with the venv bin on PATH and local binding allowed: the run Task 413 could not make.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 72-metadata 5 none 'test_installed_runtime_metadata and test_installed_dsh_accepts each say passed, or a saved failure says how far it got past the bind'
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: needs step 70, not run'; step_end; fi
SUITE=$AG/suite
[[ -f $SUITE/installed-commit && $(<$SUITE/installed-commit) == $COMMIT ]] || fail "run step 70 first: zsh $HERE/70-suite.zsh"
SHORT=/tmp/agents-392-suite
CODE=0
(cd $SUITE/clone && bounded 420 env -i HOME=$SUITE/home PATH=$SUITE/venv/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$SHORT LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 GRAPHTRAJ_NATIVE_METADATA=1 \
  $SUITE/venv/bin/python -m pytest -p no:cacheprovider -q -rA --tb=short tests/test_runtime_connections.py -k 'test_installed_runtime_metadata or test_installed_dsh_accepts') > $OUT/metadata.txt 2>&1 || CODE=$?
grep -E '^(PASSED|FAILED|ERROR|SKIPPED)' $OUT/metadata.txt | cut -c1-200 | while read -r LINE; do
  case $LINE in
    PASSED*) check PASS "$LINE" ;;
    *) check FAIL "$LINE" ;;
  esac
done || true
tail -1 $OUT/metadata.txt
COUNT=$(grep -c 'listen EPERM' $OUT/metadata.txt || true)
note "listen EPERM lines outside the sandbox: $COUNT (413's inference was that only the sandbox gives it)"
step_end
