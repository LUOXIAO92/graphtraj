#!/bin/zsh
# Step 05 (user, only if needed): /agents-context in an interactive session.
# Dialog: "Do you trust the files in this folder?"; choose "Yes, proceed".
source ${0:A:h}/env.zsh
export GRAFTLING_PYTHON=$VENV/bin/python
cd "$PROJECT"
print 'Type /agents-context, then /exit.'
script -q "$OUT/05-agents-context.typescript" "$CLAUDE"
print "Success: lines 'graftling 0.5.0 at $VENV/bin/python' and 'MCP agents registered'; recorded in $OUT/05-agents-context.typescript"
