#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 30-approval-layers. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/30-approval-layers.zsh
# One measure of each of the four layers, on a real Claude parent in print mode, so no dialog reaches the Terminal.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 30-approval-layers 20 'none' 'workspace, native approval (Claude, relayed Codex), review plugin and return to parent each have PASS lines'
prepare_checks
need_claude_project
run_checks approvals
step_end
