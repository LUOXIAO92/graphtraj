#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 90-residual-416-main. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/90-residual-416-main.zsh
# 416: a Main at the scratch project root creating a Pi child: is it RUNTIME_ACCESS_DENIED? The real project Main is not touched: one agent-runner main turn on Codex in the scratch project.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 90-residual-416-main 3 none 'read the PASS, FAIL and CANNOT lines: 416: a Main at the scratch project root creating a Pi child: is it RUNTIME_ACCESS_DENIED? The real project Main is not touched: one agent-runner main turn on Codex in the scratch project.'
prepare_checks
run_scratch r416_main
step_end
