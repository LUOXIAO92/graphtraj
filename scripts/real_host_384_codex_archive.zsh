#!/bin/zsh
# Task 384 real-host check: the independent Codex host, with normalized
# archiving on, writes a Session for the child it creates.
#
# Run in a plain Terminal (not inside an Agent sandbox):
#   zsh /Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/384-standalone-session-normalization/scripts/real_host_384_codex_archive.zsh [model]
#
# [model] is the Codex model to use; without it the script reads only the
# `model = "..."` line of ~/.codex/config.toml. Everything else is isolated in
# a new temporary directory: its own venv built from this Worktree's commit,
# its own working directory and its own agents data root. Codex uses your
# existing login; no credential is read, copied or printed by this script.
set -euo pipefail

WORKTREE=/Users/luoxiao/workspace/you-are-a-product-architect-delivery/.graphtraj/core/worktrees/384-standalone-session-normalization
COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
PYTHON=$(command -v python3.13 || command -v python3)
CODEX=$(command -v codex)
MODEL=${1:-$(sed -n 's/^model *= *"\(.*\)"$/\1/p' "$HOME/.codex/config.toml" 2>/dev/null | head -1)}
if [[ -z "$MODEL" ]]; then
  print -u2 "Pass a Codex model name as the first argument."
  exit 2
fi

RUN=$(mktemp -d /tmp/agents-384-real.XXXXXX)
WORK=$RUN/work
DATA=$RUN/data
mkdir -p "$WORK" "$DATA" "$RUN/src"
print "run directory: $RUN"
print "commit:        $COMMIT"
print "codex:         $CODEX"
print "model:         $MODEL"

# Dedicated venv with only agent-swarm from this commit (plus PyYAML and websockets).
git -C "$WORKTREE" archive "$COMMIT" src/agent_swarm | tar -x -C "$RUN/src"
"$PYTHON" -m venv "$RUN/venv"
"$RUN/venv/bin/python" -m pip install --quiet --disable-pip-version-check "$RUN/src/src/agent_swarm"
print "agents version: $("$RUN/venv/bin/python" -c 'import agent_swarm; print(agent_swarm.__version__)')"

# Archiving on in the isolated data root.
print 'save_normalized_sessions: true' > "$DATA/config.yml"
cat > "$RUN/settings.json" <<EOF
{"adapter_request": {"arguments": ["$CODEX"], "worktree_path": "$WORK",
  "session_parameters": {"cwd": "$WORK", "model": "$MODEL", "developerInstructions": "",
    "config": {"default_permissions": "work", "permissions": {"work": {
      "extends": ":workspace", "filesystem": {":workspace_roots": {".": "write"}}}}}}}}
EOF

cd "$WORK"
"$RUN/venv/bin/python" -m agent_swarm.codex.host --settings "$RUN/settings.json" --directory "$DATA" \
  --output "$RUN/parent-result.json" \
  'Use the agents MCP tool. First call action "create" with runtime "codex", instruction "Reply with exactly: TASK384-CHILD-READY. Do not use tools.", and extra_fields {"realhost": {"task": "384"}}. Then call action "wait" for the returned agent with timeout_seconds 180. Finally reply with the child reply text only.' \
  || print -u2 "The parent host exited with status $?; the archive check below still runs."

print "\n--- normalized Sessions under $DATA/sessions ---"
"$RUN/venv/bin/python" - "$DATA" <<'EOF'
import json, sys
from pathlib import Path
from agent_swarm import read_session

found = sorted(Path(sys.argv[1], 'sessions').glob('*/session.jsonl'))
if not found:
    print('NO session.jsonl was written')
    sys.exit(1)
for path in found:
    session = read_session(path)
    header = session['header']
    print('path:              ', path)
    print('header.version:    ', header['version'])
    print('header.id:         ', header['id'])
    print('extra_fields keys: ', sorted(header.get('extra_fields', {})))
    print('first event types: ', [event['type'] for event in session['events'][:8]])
EOF
