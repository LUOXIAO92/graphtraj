#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 44-sigkill-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/44-sigkill-claude.zsh
# 406: SIGKILL the host while an Agent runs, then the --resume start with the project's own .mcp.json.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 44-sigkill-claude 8 ''\''New MCP server found in .mcp.json: agents'\'' -> choose the option that uses this server; then you type /exit' 'the --resume start serves after SIGKILL and status tells what happened to the running Agent'
prepare_checks
need_claude_project
run_checks sigkill
step_end
