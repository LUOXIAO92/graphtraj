#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 11-matrix-codex. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/11-matrix-codex.zsh
# Codex host x all four; its own native requests are answered by the script, nothing to type.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 11-matrix-codex 25 'none' 'each of the 4 cells of the Codex row has PASS lines for create, status, send, interrupt, resume and retire'
prepare_checks
need_claude_project
run_checks matrix codex
step_end
