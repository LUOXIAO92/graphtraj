#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 46-shutdown-request. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/46-shutdown-request.zsh
# 414: a real child with an unanswered request while a Pi or DSH host exits.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 46-shutdown-request 8 'none' 'a child with an unanswered request stops when a Pi or DSH host exits, without a hang'
prepare_checks
need_claude_project
run_checks shutdown_pi_dsh
step_end
