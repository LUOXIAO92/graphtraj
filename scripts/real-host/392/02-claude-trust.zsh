#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 02: trust the one scratch Claude project the later steps share.
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/02-claude-trust.zsh
#
# Interactive Claude Code inherits this Terminal's stdio (417). Claude Code never runs in the
# production Main here: this directory is empty until the host configuration is written.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
step_begin 02-claude-trust 2 "'Do you trust the files in this folder?' -> choose 'Yes, proceed'; then type /exit" 'the scratch project is trusted and its host files are written'

venv_check
find_hosts
PROJECT=$AG/claude-project
mkdir -p $PROJECT
if [[ -f $PROJECT/.trust-392-done ]]; then
  note "the project was trusted by an earlier run of this step"
else
  print -r -- ""
  print -r -- "Claude Code now starts once in the empty project $PROJECT."
  print -r -- "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'."
  print -r -- "Then type /exit and press Enter. Send no message. Any other dialog: press Esc."
  (cd $PROJECT && $CLAUDE) || note "claude exit $?"
fi
touch $PROJECT/.trust-392-done

# The file itself is public and holds no credential; 419: a later --write keeps what the steps set.
(cd $PROJECT && $VENV/bin/python -m agent_swarm.claude.host configuration --project $PROJECT --claude $CLAUDE --write) > $OUT/configuration.txt 2>&1 \
  && check PASS "configuration --write: $PROJECT/.mcp.json exists: $([[ -f $PROJECT/.mcp.json ]] && print yes || print no)" \
  || check FAIL "configuration --write: see configuration.txt"
cp $PROJECT/.mcp.json $OUT/mcp.json 2>/dev/null || true
step_end
