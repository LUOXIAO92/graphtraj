#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 82-residual-387-hosts. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/82-residual-387-hosts.zsh
# 387: real Pi, DSH, Claude Code and Codex hosts receive a hold from a reviewer; a reviewed Pi child under a Pi host (410), a reviewed DSH child under DSH (411, 413).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 82-residual-387-hosts 25 none 'read the PASS, FAIL and CANNOT lines: 387: real Pi, DSH, Claude Code and Codex hosts receive a hold from a reviewer; a reviewed Pi child under a Pi host (410), a reviewed DSH child under DSH (411, 413).'
prepare_checks
need_claude_project
run_residual r387_hosts
step_end
