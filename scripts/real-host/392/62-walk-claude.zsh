#!/bin/zsh
[ -n "$ZSH_VERSION" ] || exec /bin/zsh "$0" "$@"
# Task 392 real-host step 62-walk-claude. Run in a plain macOS Terminal, outside any sandbox:
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/62-walk-claude.zsh
# install/claude-code.md as written, from a wheel-only install: generate, start, see that it worked, quit.
source /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/392-agents-standalone-combined-acceptance/scripts/real-host/392/common.zsh
# You type four things in the Session; the script prints them first. Claude Code keeps this Terminal (417).
step_begin 62-walk-claude 8 "Claude Code's project MCP server prompt for 'agents' -> choose to use this MCP server (Yes / Use this)" 'the plugin files are written, /agents-context and /mcp show agents, a Claude child answers, host.log ends with the stopped line'
venv_check
find_hosts
PROJECT=$AG/walk-claude
[[ -f $PROJECT/.trust-392-done ]] || fail "run 61-walk-claude-trust first: zsh $HERE/61-walk-claude-trust.zsh"
AGENTS_VENV=$VENV
say "generate the plugin files, as written"
cd $PROJECT
"$AGENTS_VENV/bin/python" -m agent_swarm.claude.host configuration \
  --project "$PROJECT" --claude "$(command -v claude)" --write | tee $OUT/configuration.txt
for file in .mcp.json .agents-control/claude-host.json .claude/settings.local.json .claude/skills/agents-claude-host/.claude-plugin/plugin.json .claude/skills/agents-claude-host/hooks/hooks.json .claude/skills/agents-claude-host/hooks/host_context.mjs; do
  [[ -f $PROJECT/$file ]] && check PASS "claude-code.md lists $file: written" || check FAIL "claude-code.md lists $file: not written"
done
cp .mcp.json $OUT/mcp.json; cp .agents-control/claude-host.json $OUT/claude-host.json
print -r -- ""
print -r -- "Claude Code starts now, as the note says: cd $PROJECT; claude"
print -r -- "Dialog: the project MCP server prompt for 'agents' -> accept it."
print -r -- "Then type these, one at a time:"
print -r -- "  /agents-context"
print -r -- "  /mcp                  (look for agents, then press Esc)"
print -r -- "  Use the agents tool to create a Claude child with model $CLAUDE_MODEL that answers one word, then wait for it. Show state and last_result.outcome."
print -r -- "  /exit"
(cd $PROJECT && claude) || note "claude exit $?"
print -r -- ""
print -n -- "Did /agents-context print the current Session and 'MCP agents registered'? [y/n] "; read -r ANSWER_CONTEXT
print -n -- "Did /mcp list agents? [y/n] "; read -r ANSWER_MCP
note "the user reports /agents-context showed the binding: ${ANSWER_CONTEXT:-no answer}"
note "the user reports /mcp listed agents: ${ANSWER_MCP:-no answer}"
LOG=$PROJECT/.agents-control/host.log
if [[ -f $LOG ]]; then
  cp $LOG $OUT/host.log
  grep -q 'agents host recorded its children stopped.' $LOG \
    && check PASS "claude-code.md: host.log says agents host recorded its children stopped." \
    || check FAIL "claude-code.md: host.log lacks the stopped line; last line: $(tail -1 $LOG | cut -c1-200)"
else
  check FAIL "claude-code.md: no host.log at $LOG"
fi
SLUG=${PROJECT//[\/.]/-}
TRANSCRIPT=($HOME/.claude/projects/$SLUG/*.jsonl(Nom[1]))
if (( ${#TRANSCRIPT} )); then
  cp $TRANSCRIPT $OUT/transcript.jsonl
  grep -q 'standby' $OUT/transcript.jsonl && grep -q '"outcome' $OUT/transcript.jsonl \
    && check PASS "claude-code.md: the transcript shows the child's standby and outcome" \
    || check FAIL "claude-code.md: the transcript shows no child's end; read transcript.jsonl"
else
  check FAIL "no transcript under $HOME/.claude/projects/$SLUG"
fi
step_end
