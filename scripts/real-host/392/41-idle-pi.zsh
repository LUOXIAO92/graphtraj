#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 41-idle-pi. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/41-idle-pi.zsh
# 403: a live Pi Session in RPC mode, idle after its first turn.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 41-idle-pi 6 'none' 'the idle Pi Session starts one turn for the notice'
prepare_checks
need_claude_project
run_checks idle_pi
step_end
