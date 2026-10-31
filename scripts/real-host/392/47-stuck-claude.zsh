#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 47-stuck-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/47-stuck-claude.zsh
# 415: a stuck real child when a Claude host exits.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 47-stuck-claude 8 'none' 'the Claude host process ends with a stuck child; the stop-unconfirmed line is in host.log, not in the Session'
prepare_checks
need_claude_project
run_checks stuck_all claude
step_end
