#!/bin/sh
# Authorized Main continues the two original real host Sessions; creates no child.
set -eu
: "${CLAUDE352_PYTHON:?Use the exact corrected standalone interpreter}"
: "${CLAUDE352_PROJECT:?Use the original isolated project}"
: "${CLAUDE352_EXECUTABLE:?Use the same existing native launcher}"
cd "$CLAUDE352_PROJECT"
case "${1:-notices}" in
  notices)
    "$CLAUDE352_EXECUTABLE" --allowedTools mcp__agents__agents --print --verbose --output-format stream-json --model claude-opus-5-5 --resume a8bdbac3-bc56-4679-9002-821e1680aeff --plugin-dir "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" --mcp-config "$CLAUDE352_PROJECT/.mcp.json" > "$CLAUDE352_PROJECT/evidence/notices-r4.jsonl" 2> "$CLAUDE352_PROJECT/evidence/notices-r4.stderr" <<'CLAUDE352_PROMPT'
Continue the original Task352 validation using only agents MCP and the existing Agent agent-d305cae8dc574c5785e6b8dc78d1ec03. Do not create, replace or retire an Agent. Describe resume/wait/status if needed. Resume that same Agent with: "Recall the original word I asked you to remember and reply with that word followed by NOTICE-RESULT352. Do not run tools." Wait up to30 seconds for completion. Inspect this and one following status result for main_notices containing the child's exact text. Report which public result or unsolicited plugin turn actually supplied it and whether it appears once, along with actual original native Session and new execution IDs. A null last_message is deliberate when the same text is delivered in a notice; verify actual notice content instead of trusting its delivered marker. Do not send the child another message to force delivery.
CLAUDE352_PROMPT
    ;;
  permissions)
    "$CLAUDE352_EXECUTABLE" --allowedTools mcp__agents__agents --print --verbose --output-format stream-json --model claude-opus-5-5 --resume 66bba2db-040c-4d2c-84fe-7e32f634481b --plugin-dir "$CLAUDE352_PROJECT/.claude/skills/agents-claude-host" --mcp-config "$CLAUDE352_PROJECT/.mcp.json" > "$CLAUDE352_PROJECT/evidence/permissions-r4.jsonl" 2> "$CLAUDE352_PROJECT/evidence/permissions-r4.stderr" <<'CLAUDE352_PROMPT'
Continue Task352 only through agents MCP, using the existing permission-child Agent agent-7cb6373d9c414ccc9ae80789b86afbfe and its captured explicit default/manual native permission mode. Do not create, replace, retire or reconfigure a child. Describe send/wait/requests/reply if needed. Send that Agent exactly: "Use the native Write tool, not Bash, to create the new file /private/tmp/task352-native-8e58e85/permission-deny352.txt containing exactly PERMISSION352. Do not change any existing file or use any other tool. If native permission is denied, report DENIED352 and stop; do not retry or use an alternate tool." Wait until a request or completion, then inspect requests. If a real Write permission request is pending, reply deny with message "Task352 explicit native refusal validation". Wait for standby, and report the original request's exact request_token/request_id, the reply result, final actual child text/notice and native Session ID. If no request appears, clearly say requests/reply remains unverified and preserve the actual outcome. Never manufacture a request or allow one. Do not retry with another tool or broader permission.
CLAUDE352_PROMPT
    ;;
  *) echo 'Use notices or permissions' >&2; exit 2;;
esac
