#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 43-esc-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/43-esc-claude.zsh
# 404: interactive Claude Code; host.log shows what the client sent.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 43-esc-claude 2 'none expected; attended: when the screen says PRESS ESC NOW you press Esc once, then type /exit and Enter' 'the summary answers whether Esc sends notifications/cancelled, shows no agents context cleanup failed line, and the wait call ended'
prepare_checks
need_claude_project
run_checks esc
step_end
