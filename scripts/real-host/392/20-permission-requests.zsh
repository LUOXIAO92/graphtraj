#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 20-permission-requests. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/20-permission-requests.zsh
# Permission requests. Messages are in every matrix cell; system failures are step 21.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 20-permission-requests 8 'none' 'a real Pi child'\''s and a real Claude child'\''s ask_parent reach the parent once and the answer comes back'
prepare_checks
need_claude_project
run_checks exchanges
step_end
