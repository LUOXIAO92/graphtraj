#!/bin/sh
# rehearsal stub: echoes its arguments' shape and one fake tool call; no model, no network
for a in "$@"; do case $a in mcp__graftling__agents*|*mcp__graftling__agents*) t=mcp__graftling__agents;; *mcp__graphtraj__agents*) t=mcp__graphtraj__agents;; esac; done
echo "{\"type\":\"session\",\"sessionId\":\"stub-session-1\"}"
echo "{\"type\":\"tool_call\",\"name\":\"$t\",\"status\":\"completed\",\"isError\":false}"
echo "{\"type\":\"text\",\"text\":\"DONE-520-X stub\"}"
echo "stub dsh DSH_HOME=$DSH_HOME args: $*" >&2
