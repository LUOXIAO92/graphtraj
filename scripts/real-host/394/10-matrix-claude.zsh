#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 10-matrix-claude: 392's matrix row for the claude host, with the renamed package. Run in a plain macOS Terminal:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/10-matrix-claude.zsh
# Claude Code host x Claude, Codex, Pi, DSH children; print mode. The Pi cell declares no connection (408).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 10-matrix-claude 25 none 'matrix.txt shows PASS (9 of 9) for each of the 4 cells of the claude row, and no old name in the host output'
prepare_checks
need_claude_project
run_checks matrix claude
old_names
step_end
