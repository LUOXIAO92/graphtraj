#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 42-hold-dsh. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/42-hold-dsh.zsh
# 403: DSH holding across a stopped headless Session.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 42-hold-dsh 6 'none' 'the end of a child stopped with DSH arrives once on resume'
prepare_checks
need_claude_project
run_checks hold_dsh
step_end
