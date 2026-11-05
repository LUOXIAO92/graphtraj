#!/bin/zsh
# Step 00b (user, only when step 00 shows no login): log in under the scratch config dir.
# Dialog: the browser's Claude authorization page; choose "Authorize". Claude Code
# may first ask for a theme and to trust $PROJECT: pick any theme, "Yes, proceed".
source ${0:A:h}/env.zsh
cd "$PROJECT"
print 'Type /login, finish it in the browser, then type /exit.'
"$CLAUDE"
print "Next (Main): zsh $STEPS/00-preflight.zsh"
