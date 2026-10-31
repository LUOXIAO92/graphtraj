#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 86-residual-412. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/86-residual-412.zsh
# 412, 387: a reviewed Pi child from a path with spaces under real srt and wrap_command; the key in no argv; auth.json holds the name.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 86-residual-412 6 none 'read the PASS, FAIL and CANNOT lines: 412, 387: a reviewed Pi child from a path with spaces under real srt and wrap_command; the key in no argv; auth.json holds the name.'
prepare_checks

run_residual r412
step_end
