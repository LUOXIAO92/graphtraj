#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 394 real-host step 02: trust the one scratch Claude project the Claude matrix row uses (392's step 02).
# Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/02-claude-trust.zsh
# Interactive Claude Code inherits this Terminal. The project is empty until the host configuration is written.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/394-agents-rename-after-naming/scripts/real-host/394/common.zsh
step_begin 02-claude-trust 2 "Claude Code's 'Do you trust the files in this folder?' -> choose 'Yes, proceed', then type /exit (none when the project was trusted before)" 'the scratch project is trusted and .mcp.json names the agents server with no old name'

venv_check
find_hosts
PROJECT=$AG/claude-project
mkdir -p $PROJECT
if [[ -f $PROJECT/.trust-394-done ]]; then
  note "the project was trusted by an earlier run of this step; no dialog"
else
  what_to_type "Claude Code now starts once in the empty project $PROJECT." \
    "Dialog: 'Do you trust the files in this folder?' -> choose 'Yes, proceed'." \
    "Then type /exit and press Enter. Send no message. Any other dialog: press Esc."
  (cd $PROJECT && $CLAUDE) || note "claude exit $?"
  note "folder trust: the choice is not confirmed here; step 10 shows it. $PROJECT"
fi
touch $PROJECT/.trust-394-done

(cd $PROJECT && $VENV/bin/python -m graftling.claude.host configuration --project $PROJECT --claude $CLAUDE --write) > $OUT/configuration.txt 2>&1 \
  && check PASS "graftling.claude.host configuration --write: $PROJECT/.mcp.json exists: $([[ -f $PROJECT/.mcp.json ]] && print yes || print no)" \
  || check FAIL "graftling.claude.host configuration --write: see configuration.txt"
cp $PROJECT/.mcp.json $OUT/mcp.json 2>/dev/null || true
SERVERS=$($PY -I -c 'import json, sys; print(" ".join(json.load(open(sys.argv[1])).get("mcpServers", {})))' $PROJECT/.mcp.json 2>&1 || true)
[[ " $SERVERS " == *" agents "* ]] && check PASS ".mcp.json servers: $SERVERS (the steps allow mcp__agents__agents)" \
  || check FAIL ".mcp.json servers: $SERVERS; the matrix steps allow only mcp__agents__agents"
old_names
step_end
