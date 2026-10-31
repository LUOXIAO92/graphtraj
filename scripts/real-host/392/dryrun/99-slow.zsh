#!/bin/zsh
# Dry run only: a step that outlives a short limit. Its foreground sleep ends by itself, because the
# team's sandbox cannot list processes for the runner to signal, so this shows the TERM trap saving.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 99-slow 1 none 'never finishes under a short limit'
check PASS "slow step started"
sleep 12
check PASS "slow step went on after the TERM, which it must not"
step_end
