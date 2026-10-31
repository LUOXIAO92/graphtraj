#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 87-residual-419. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/87-residual-419.zsh
# 419: configuration --write again on a real project keeps LANGUAGE-style env and the declared data root, and the host still starts.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 87-residual-419 5 none 'read the PASS, FAIL and CANNOT lines: 419: configuration --write again on a real project keeps LANGUAGE-style env and the declared data root, and the host still starts.'
prepare_checks
need_claude_project
run_residual r419
step_end
