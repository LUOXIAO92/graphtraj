#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 10-matrix-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/10-matrix-claude.zsh
# Claude Code host x Claude, Codex, Pi, DSH children; print mode; matrix.txt holds the row. The Pi cell declares no connection (408).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 10-matrix-claude 25 'none' 'each of the 4 cells of the Claude Code row has PASS lines for create, status, send, interrupt, resume and retire'
prepare_checks
need_claude_project
run_checks matrix claude
step_end
