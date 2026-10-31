#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 12-matrix-pi. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/12-matrix-pi.zsh
# Pi host x all four; the Pi x Pi cell is 382's Task-free Pi child.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 12-matrix-pi 25 'none' 'each of the 4 cells of the Pi row has PASS lines for create, status, send, interrupt, resume and retire'
prepare_checks
need_claude_project
run_checks matrix pi
step_end
