"""593 (from 579's mcp579.py): real-entry probe of an MCP stdio server: initialize, tools/list, then one tools/call of
the OLD tool name. Read only.

usage: mcp593.py <label> <project directory> <command> [args...]

Starts the command in the project directory with stdin/stdout pipes, sends `initialize`, `notifications/initialized`,
`tools/list` and `tools/call` with name `agents` and arguments {"action": "discover"} (newline-delimited JSON-RPC), and
prints the server info, the tool names and the old-name answer. Two CHECKs: the tool names are exactly `subagents` and
`tasks` (Main's host exposes them as mcp__graphtraj__subagents/tasks; 591/592), and `agents` is an unknown tool: the
call answers a JSON-RPC error or a result with isError true, never a normal result (no alias). The server is closed by
closing its stdin; it is never signalled unless it ignores that for 20 s (it is this probe's own child).
"""
import json
import subprocess
import sys
import threading

label, project, command = sys.argv[1], sys.argv[2], sys.argv[3:]
process = subprocess.Popen(command, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
replies = {}
done = threading.Event()


def reader():
    for line in process.stdout:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if 'id' in message:
            replies[message['id']] = message
            if message['id'] == 3:
                done.set()


threading.Thread(target=reader, daemon=True).start()
for message in ({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'probe-593', 'version': '0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}):
    process.stdin.write(json.dumps(message) + '\n')
    process.stdin.flush()
done.wait(60)
process.stdin.close()
try:
    process.wait(20)
except subprocess.TimeoutExpired:
    process.kill()
info = (replies.get(1) or {}).get('result', {}).get('serverInfo')
tools = sorted(tool.get('name') for tool in (replies.get(2) or {}).get('result', {}).get('tools', []))
old = replies.get(3) or {}
old_error = old.get('error') or ((old.get('result') or {}).get('isError') is True and old.get('result'))
print(f'{label} server: {" ".join(command[:3])} | serverInfo: {info} | tools: {tools}')
print(f'{label} tools/call agents: {json.dumps(old)[:300] if old else "no answer"}')
if not tools:
    print(f'{label} stderr tail: {process.stderr.read()[-400:]!r}')
ok = tools == ['subagents', 'tasks']
print(f"CHECK 593 {label} MCP tools/list is exactly subagents, tasks: {'PASS' if ok else 'FAIL'}")
unknown = bool(old) and bool(old_error)
print(f"CHECK 593 {label} MCP tool agents is unknown (error answer, no alias): {'PASS' if unknown else 'FAIL'}")
sys.exit(0 if ok and unknown else 1)
