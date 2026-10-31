#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 31-archive. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/31-archive.zsh
# The archive switch on the standalone Claude host, for a Claude and a DSH child.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 31-archive 8 'none' 'on writes a version 5 archive with extra_fields; off writes no new one and keeps the earlier one'
prepare_checks
need_claude_project
run_checks archive
step_end
