#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 83-residual-387-exit. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/83-residual-387-exit.zsh
# 387 with 414: each host ends while an agents/review is unanswered. It must not hang, and the next host must show the end.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 83-residual-387-exit 25 none 'read the PASS, FAIL and CANNOT lines: 387 with 414: each host ends while an agents/review is unanswered. It must not hang, and the next host must show the end.'
prepare_checks
need_claude_project
run_residual r387_exit
step_end
