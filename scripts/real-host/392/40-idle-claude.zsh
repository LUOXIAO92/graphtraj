#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 40-idle-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/40-idle-claude.zsh
# 403: a parent alive and idle. Interactive Claude Code on this Terminal; you type only /exit.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 40-idle-claude 6 'none expected; you type /exit when it prints SEEN-NOTICE' 'the idle Claude Main receives one pushed notice'
prepare_checks
need_claude_project
run_checks idle_claude
step_end
