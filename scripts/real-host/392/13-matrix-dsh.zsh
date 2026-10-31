#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 13-matrix-dsh. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/13-matrix-dsh.zsh
# DSH host (headless) x all four; DEEPSEEK_BASE_URL stays as this shell has it (411).
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 13-matrix-dsh 25 'none' 'each of the 4 cells of the DSH row has PASS lines for create, status, send, interrupt, resume and retire'
prepare_checks
need_claude_project
run_checks matrix dsh
step_end
