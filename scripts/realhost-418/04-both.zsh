#!/bin/zsh
# Step 04 (Main, no dialog): a project with both configuration --write material and
# the plugin keeps the configuration --write host; the plugin's host stands aside.
source ${0:A:h}/env.zsh
export GRAFTLING_PYTHON=$VENV/bin/python
{
  cd "$BOTH"
  "$VENV/bin/python" -m graftling.claude.host configuration --project "$BOTH" --claude "$CLAUDE" --write
  "$CLAUDE" plugin install graftling@graftling --scope project
  print "== claude -p"
  "$CLAUDE" -p --allowedTools "$TOOL" \
    "Call the $TOOL tool with action discover and print its result in two lines."
  print "== host.log"; cat "$BOTH/.agents-control/host.log"
} 2>&1 | tee "$OUT/04-both.txt"
cat <<NEXT

Success: host.log holds 'host-busy' and '$BOTH/.mcp.json starts this project's
agents host (configuration --write), so the graftling plugin host stands aside'.
Next, only if the Leader asks for it (user): zsh $STEPS/05-agents-context.zsh
NEXT
