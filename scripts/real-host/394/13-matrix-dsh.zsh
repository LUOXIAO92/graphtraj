#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 13-matrix-dsh: 392's matrix row for the dsh host, with the renamed package. Run in a plain macOS Terminal:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/13-matrix-dsh.zsh
# DSH host (headless, --patch, as in 392) x all four; DEEPSEEK_BASE_URL stays as this shell has it (411).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 13-matrix-dsh 25 none 'matrix.txt shows PASS (9 of 9) for each of the 4 cells of the dsh row, and no old name in the host output'
prepare_checks
need_claude_project
run_checks matrix dsh
old_names
step_end
