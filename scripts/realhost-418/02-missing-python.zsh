#!/bin/zsh
# Step 02 (Main, no dialog): with GRAFTLING_PYTHON naming no Python, the plugin's
# host says what to install and set.
source ${0:A:h}/env.zsh
rm -rf "$PROJECT/.agents-control"
{
  cd "$PROJECT"
  print "== claude mcp list (GRAFTLING_PYTHON=$SCRATCH/no-python)"
  GRAFTLING_PYTHON=$SCRATCH/no-python "$CLAUDE" mcp list
  print "== claude -p"
  print -r -- "Call the $TOOL tool with action discover and report its result or why it is unavailable, in two lines." \
    | GRAFTLING_PYTHON=$SCRATCH/no-python "$CLAUDE" -p --allowedTools "$TOOL"
  print "== host.log"; cat "$PROJECT/.agents-control/host.log"
} 2>&1 | tee "$OUT/02-missing-python.txt"
cat <<NEXT

Success: host.log holds 'graftling plugin: the agents host did not start:
GRAFTLING_PYTHON=$SCRATCH/no-python cannot run graftling (...)' naming the wheel
and GRAFTLING_PYTHON, and 'claude mcp list' shows plugin:graftling:agents failed.
If host.log does not exist, the server was never started: copy the 'mcp list' lines.
Next: zsh $STEPS/03-create-child.zsh
NEXT
