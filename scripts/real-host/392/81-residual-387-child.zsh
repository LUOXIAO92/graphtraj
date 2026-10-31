#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 81-residual-387-child. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/81-residual-387-child.zsh
# 387: a real reviewer's deny; a child with no api_key_env whose reviewer uses DEEPSEEK_API_KEY. This process is the parent.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 81-residual-387-child 15 none 'read the PASS, FAIL and CANNOT lines: 387: a real reviewers deny; a child with no api_key_env whose reviewer uses DEEPSEEK_API_KEY. This process is the parent.'
prepare_checks

run_residual r387_api
step_end
