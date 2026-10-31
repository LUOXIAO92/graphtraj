#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 45-pi-parent. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/45-pi-parent.zsh
# 410: a Pi child that is itself a parent.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 45-pi-parent 12 'none' 'a Pi child takes its child'\''s end once by steering, it stays delivered after a stop, and a resume with a held notice returns within 30 s'
prepare_checks
need_claude_project
run_checks pi_parent
step_end
