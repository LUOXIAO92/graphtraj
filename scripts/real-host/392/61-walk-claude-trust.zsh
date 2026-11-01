#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 61-walk-claude-trust. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/61-walk-claude-trust.zsh
# The empty project of install/claude-code.md: Claude Code's folder trust, so the next step's dialog is only the MCP one.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 61-walk-claude-trust 2 "'Do you trust the files in this folder?' -> choose 'Yes, proceed'; then type /exit" 'the walk project is trusted'
venv_check
find_hosts
PROJECT=$AG/walk-claude
mkdir -p $PROJECT
what_to_type "Claude Code now starts in the empty project $PROJECT." \
  "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'." \
  "Then type /exit and press Enter."
(cd $PROJECT && $CLAUDE) || note "claude exit $?"
touch $PROJECT/.trust-392-done
note "folder trust: the choice is not confirmed here; step 62's run shows it. $PROJECT"
step_end
