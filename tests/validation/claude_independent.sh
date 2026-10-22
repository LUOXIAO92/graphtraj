#!/bin/sh
# Run by the authorized native host operator, never by a delegated test wrapper.
set -eu
: "${CLAUDE352_PYTHON:?Set the exact standalone candidate venv interpreter}"
: "${CLAUDE352_PROJECT:?Set a new isolated directory}"
: "${CLAUDE352_EXECUTABLE:?Set the existing Claude launcher; do not copy credentials}"
phase=${1:-prepare}
mkdir -p "$CLAUDE352_PROJECT/evidence"
case "$phase" in
  prepare)
    "$CLAUDE352_PYTHON" -I -c 'import importlib.util,sys,agent_swarm; assert importlib.util.find_spec("graphtraj") is None; print(sys.executable); print(agent_swarm.__file__)' > "$CLAUDE352_PROJECT/evidence/installation.txt"
    "$CLAUDE352_PYTHON" -I -m agent_swarm.claude.host configuration --project "$CLAUDE352_PROJECT" --claude "$CLAUDE352_EXECUTABLE" --write > "$CLAUDE352_PROJECT/evidence/configuration.txt"
    "$CLAUDE352_EXECUTABLE" plugin validate "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" > "$CLAUDE352_PROJECT/evidence/plugin-validation.txt" 2>&1
    ;;
  lifecycle)
    cd "$CLAUDE352_PROJECT"
    "$CLAUDE352_EXECUTABLE" --print --verbose --output-format stream-json --model claude-opus-5-5 --plugin-dir "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" --mcp-config "$CLAUDE352_PROJECT/.mcp.json" > "$CLAUDE352_PROJECT/evidence/lifecycle-r2.jsonl" 2> "$CLAUDE352_PROJECT/evidence/lifecycle-r2.stderr" <<'CLAUDE352_PROMPT'
You are the authorized native test host for independent agents. Use only the agents MCP entry. Discover and describe the needed features. Create one Claude child named validation-child with instruction: "Remember the exact secret word AZURE352 within this native Session. Call agents MCP discover, then describe status, then execute status. Reply READY352 and wait for another instruction. Do not edit files or create children." Record returned Agent, native Session and execution IDs. Wait for completion and report the child response and actual notification if delivered. Send that same child: "Recall the word from memory, then use Bash to sleep 60 seconds before replying." Wait 3 seconds, inspect requests; deny any pending permission request explicitly, then interrupt the original active execution. Wait up to 30 seconds for standby and report its terminal result. Resume the same Agent with "What word did I ask you to remember? Reply with it and SESSION352 only; do not use Bash." Wait for completion and verify the same native Session ID and remembered word. Read status and requests. Do not retire, re-create or replace the child. Report all exact IDs, actual child results, notification observations and any error; a send ACK is not terminal proof.
CLAUDE352_PROMPT
    ;;
  permissions)
    # Explicitly select manual native review for a NEW child to exercise requests/reply.
    "$CLAUDE352_PYTHON" -I -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1])/".agents-control/claude-host.json"; d=json.loads(p.read_text()); d["settings"]["permission_mode"]="default"; p.write_text(json.dumps(d,indent=2)+"\n")' "$CLAUDE352_PROJECT"
    cd "$CLAUDE352_PROJECT"
    "$CLAUDE352_EXECUTABLE" --print --verbose --output-format stream-json --model claude-opus-5-5 --plugin-dir "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" --mcp-config "$CLAUDE352_PROJECT/.mcp.json" > "$CLAUDE352_PROJECT/evidence/permissions-r2.jsonl" 2> "$CLAUDE352_PROJECT/evidence/permissions-r2.stderr" <<'CLAUDE352_PROMPT'
Use only agents MCP. Discover/describe create, wait, requests, reply. Create one Claude child named permission-child with instruction "Run Bash command printf PERMISSION352, and report its result or native denial. Do not change files." Wait until a request or completion; inspect requests. If a native request appears, reply deny with message "Task352 explicit native refusal validation". Wait for standby and report exact request/reply and final result. If no native request appears, report that requests/reply remains unverified. Do not manufacture a request, grant broad permission, retry with bypass or create other children.
CLAUDE352_PROMPT
    ;;
  *) echo 'Use prepare, lifecycle or permissions' >&2; exit 2;;
esac
