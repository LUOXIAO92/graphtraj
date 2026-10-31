#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 84-residual-391. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/84-residual-391.zsh
# 391: real agent_sandbox without srt, real srt without node or rg, through real Pi and DSH hosts: what the parent reads.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 84-residual-391 15 none 'read the PASS, FAIL and CANNOT lines: 391: real agent_sandbox without srt, real srt without node or rg, through real Pi and DSH hosts: what the parent reads.'
prepare_checks

run_residual r391
step_end
