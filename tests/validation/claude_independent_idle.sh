#!/bin/sh
# Authorized Main operates this native terminal; no synthesized identity or trust.
set -eu
: "${CLAUDE352_PYTHON:?Use the exact standalone candidate interpreter}"
: "${CLAUDE352_PROJECT:?Use the same isolated native-validation directory}"
: "${CLAUDE352_EXECUTABLE:?Use the existing native Claude launcher}"
"$CLAUDE352_PYTHON" -I -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1])/".agents-control/claude-host.json"; d=json.loads(p.read_text()); d["settings"].pop("permission_mode",None); p.write_text(json.dumps(d,indent=2)+"\n")' "$CLAUDE352_PROJECT"
cd "$CLAUDE352_PROJECT"
printf '%s\n' 'After WAITING352 appears, do not type for 45 seconds. Record whether a plugin prompt arrives and the native host replies NOTICE352. Then enter /agents-context, record its output, then enter /exit. If native trust prompts appear, use ordinary user approval; never use bypass or allow-all. If no notice arrives by 45 seconds, preserve that failure and still use /agents-context then /exit.'
script -q "$CLAUDE352_PROJECT/evidence/idle-r3.typescript" "$CLAUDE352_EXECUTABLE" 'Use only agents MCP. Discover and describe create. Create exactly one Claude child named idle-notice-child with instruction "Run Bash sleep 12, then reply IDLE-PUSH352. Do not edit files, create children, or call other tools." When create returns, immediately reply WAITING352 and end your turn. Do not call wait/status or poll after creation. When a later plugin completion notice arrives, reply NOTICE352 followed by the sender Agent identifier and exact received child text. If a native permission request arrives instead, report it as unverified completion; do not broaden permissions or create another child.' --allowedTools mcp__agents__agents --model claude-opus-5-5 --plugin-dir "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" --mcp-config "$CLAUDE352_PROJECT/.mcp.json"
