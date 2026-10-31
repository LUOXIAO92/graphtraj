#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 48-stuck-codex. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/48-stuck-codex.zsh
# 415: a stuck real child when a Codex host exits.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 48-stuck-codex 8 'none' 'the Codex host process ends with a stuck child; the stop-unconfirmed line is on stderr and in --output'
prepare_checks
need_claude_project
run_checks stuck_all codex
step_end
