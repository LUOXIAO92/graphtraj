#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 11-matrix-codex: 392's matrix row for the codex host, with the renamed package. Run in a plain macOS Terminal:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/11-matrix-codex.zsh
# Codex host x all four; its own native requests are answered by the script, nothing to type.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 11-matrix-codex 25 none 'matrix.txt shows PASS (9 of 9) for each of the 4 cells of the codex row, and no old name in the host output'
prepare_checks
need_claude_project
run_checks matrix codex
old_names
step_end
