#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 21-system-failures. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/21-system-failures.zsh
# 421: real start failures on a real Pi parent. The resume failure runs its host under sandbox-exec with TCP binding denied, the listen EPERM DSH hit.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 21-system-failures 12 'none' 'real Claude and Pi start failures and a real resume start failure each notify the parent once, with the reason'
prepare_checks
need_claude_project
run_checks failures
step_end
