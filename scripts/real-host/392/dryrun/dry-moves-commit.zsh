#!/bin/zsh
# Dry run only: a step that changes the COMMIT file mid-run, as happened at 00:22 in the overnight run.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin dry-moves-commit 1 none "changes the COMMIT file during the run"
print -r -- 0000000000000000000000000000000000000392 > $HERE/COMMIT
check PASS "this step ran at $COMMIT and wrote another hash to the COMMIT file"
step_end
