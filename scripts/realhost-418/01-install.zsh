#!/bin/zsh
# Step 01 (Main, no dialog): validate, add the local marketplace and install the
# plugin at project scope, without a session.
source ${0:A:h}/env.zsh
{
  print "== validate"; "$CLAUDE" plugin validate "$CHECKOUT"
  print "== marketplace add"; "$CLAUDE" plugin marketplace add "$CHECKOUT"
  print "== install"; ( cd "$PROJECT" && "$CLAUDE" plugin install graftling@graftling --scope project )
  print "== list"; ( cd "$PROJECT" && "$CLAUDE" plugin list )
  print "== $PROJECT/.claude/settings.json"; cat "$PROJECT/.claude/settings.json"
  print "\n== no prior configuration"; ls -a "$PROJECT"
} 2>&1 | tee "$OUT/01-install.txt"
cat <<NEXT

Success: validate passes, 'graftling@graftling' is listed as installed and
enabled, $PROJECT/.claude/settings.json enables graftling@graftling, and
$PROJECT has no .agents-control or .mcp.json.
If a 'claude plugin' line says 'unknown command', the user runs instead, in
  cd $PROJECT && CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR $CLAUDE
the commands '/plugin marketplace add $CHECKOUT' and
'/plugin install graftling@graftling' (dialog: install scope; choose project), then /exit.
Next: zsh $STEPS/02-missing-python.zsh
NEXT
