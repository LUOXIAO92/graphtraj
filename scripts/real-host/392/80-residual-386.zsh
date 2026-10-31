#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 80-residual-386. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/80-residual-386.zsh
# 386: a third-party provider child with a real reviewer; Codex deny and escalate in three approval forms; reviewed Claude and Codex children under real Pi and DSH hosts.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/residual.zsh
step_begin 80-residual-386 35 none 'read the PASS, FAIL and CANNOT lines: 386: a third-party provider child with a real reviewer; Codex deny and escalate in three approval forms; reviewed Claude and Codex children under real Pi and DSH hosts.'
prepare_checks
need_claude_project
run_residual r386
step_end
