#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 95-claude-cd. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/95-claude-cd.zsh
# 437: a Claude member's native helper completes after a plain cd (scratch GraphTraj project, needs step 88),
# and a Claude host that does a plain cd into a project subdirectory can still use agents.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 95-claude-cd 25 none 'read the PASS, FAIL and CANNOT lines: 437: a Claude member helper after a plain cd, and a Claude host using agents after a plain cd into a project subdirectory'
prepare_checks
run_residual r437_main
run_scratch r437_member
step_end
