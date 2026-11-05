#!/bin/zsh
# Step 00 (Main, no dialog): Claude Code version and login under the scratch config
# dir, a checkout of exactly COMMIT, and a scratch venv with this commit's wheel.
source ${0:A:h}/env.zsh
{
  print "== claude --version"; "$CLAUDE" --version
  print "== login (one-line claude -p under $CLAUDE_CONFIG_DIR)"
  ( cd "$PROJECT" && "$CLAUDE" -p 'In one line: your exact model id, then the word READY.' ) 2>&1 | tail -n 3
  print "== checkout of $COMMIT"
  rm -rf "$CHECKOUT" && mkdir -p "$CHECKOUT"
  git -C "$REPO" archive "$COMMIT" | tar -x -C "$CHECKOUT"
  print -r -- "$COMMIT" > "$SCRATCH/commit"
  print "== scratch venv from this commit's wheel (dependencies from the network)"
  rm -rf "$VENV" "$SCRATCH/wheels"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip wheel -q --no-deps -w "$SCRATCH/wheels" "$CHECKOUT/src/graftling"
  "$VENV/bin/python" -m pip install -q "$SCRATCH"/wheels/graftling-*.whl
  "$VENV/bin/python" -c 'import sys, graftling, graftling.claude.host; print(sys.version.split()[0], graftling.__version__, graftling.__file__)'
} 2>&1 | tee "$OUT/00-preflight.txt"
cat <<NEXT

Success: a claude version, a line with a model id and READY, and a line
'<python> 0.5.0 $VENV/lib/.../graftling/__init__.py'.
If the login line says 'Not logged in' or 'Invalid API key', the user runs:
  zsh $STEPS/00b-login.zsh
Then, or otherwise next:
  zsh $STEPS/01-install.zsh
NEXT
