#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 49-stuck-pi. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/49-stuck-pi.zsh
# 414 residual: a stuck real child when a Pi host exits; a FAIL on the bound goes back to Main as a defect.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 49-stuck-pi 8 'none' 'the Pi host process ends with a stuck child, and one blocked call does not hold it past its bound'
prepare_checks
need_claude_project
run_checks stuck_all pi
step_end
