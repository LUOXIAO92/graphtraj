#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 71-flaky. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/71-flaky.zsh
# Repeats the listed tests (the definition's flaky tests, step 70's failures and 428's Seatbelt test), each on its own, outside the sandbox. Each failure's log is kept.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 71-flaky 25 none "each listed test has a pass and fail count and every failing run's log; 'FAIL' means it failed at least once"
if [[ -n ${AGENTS_392_DRY_BIN:-} ]]; then note 'dry run: needs step 70, not run'; step_end; fi
SUITE=$AG/suite
[[ -f $SUITE/installed-commit && $(<$SUITE/installed-commit) == $COMMIT ]] || fail "run step 70 first: zsh $HERE/70-suite.zsh"
SHORT=/tmp/agents-392-suite
TESTENV=(env -i HOME=$SUITE/home PATH=$SUITE/venv/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=$SHORT LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1)
# The count holds a run under ten seconds each for most; the slow ones come last. 20 runs, 387's and 408's sample sizes doubled.
for spec in \
    20:tests/test_standalone_session_capture.py::test_standalone_claude_archives_with_create_fields_and_stops_when_off \
    20:tests/test_dsh_standalone_child.py::test_a_dsh_childs_end_reaches_the_claude_main_once \
    20:tests/test_descendant_stop_control.py::test_native_root_owner_outlives_historical_checker_membership \
    10:tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations 10:tests/test_team_replacement.py::test_replacing_parent_keeps_old_descendants_stopped_and_bound_to_old_session \
    10:'tests/test_claude_review.py::test_refused_review_denies_and_asks_the_parent_once[decision1]' \
    10:tests/test_dsh_member_tools.py::test_seatbelt_enforces_the_written_grants \
    10:tests/test_claude_runtime.py::test_claude_later_prompt_hook_is_answered_during_one_slow_collection; do
  COUNT=${spec%%:*} ID=${spec#*:} NAME=${ID##*::} PASSED=0 FAILED=0
  say "$NAME, $COUNT runs"
  for number in {1..$COUNT}; do
    CODE=0
    (cd $SUITE/clone && bounded 180 $TESTENV $SUITE/venv/bin/python -m pytest -p no:cacheprovider -q -x --tb=short $ID) > $RUN/one.txt 2>&1 || CODE=$?
    if (( CODE == 0 )); then
      PASSED=$((PASSED+1))
    else
      FAILED=$((FAILED+1))
      cp $RUN/one.txt $OUT/$NAME.failure-$number.txt
    fi
  done
  check $( (( FAILED )) && print FAIL || print PASS) "$NAME: $PASSED passed, $FAILED failed of $COUNT$( (( FAILED )) && print -r -- "; error: $(grep -m1 '^E ' $OUT/$NAME.failure-*.txt(N[1]) | cut -c1-200)")"
done
step_end
