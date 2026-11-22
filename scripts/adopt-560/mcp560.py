"""560: real-entry probe of an MCP stdio server: initialize, then tools/list. Read only.

usage: mcp560.py <label> <project directory> <command> [args...]

Starts the command in the project directory with stdin/stdout pipes, sends `initialize`, `notifications/initialized`
and `tools/list` (newline-delimited JSON-RPC), and prints the server info and tool names. CHECK passes when the tool
names are exactly `agents` and `tasks` (the server Main's host exposes as mcp__graphtraj__agents/tasks). The server is
closed by closing its stdin; it is never signalled unless it ignores that for 20 s (it is this probe's own child).
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
            if message['id'] == 2:
                done.set()


threading.Thread(target=reader, daemon=True).start()
for message in ({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'probe-560', 'version': '0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}):
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
print(f'{label} server: {" ".join(command[:3])} | serverInfo: {info} | tools: {tools}')
if not tools:
    print(f'{label} stderr tail: {process.stderr.read()[-400:]!r}')
ok = tools == ['agents', 'tasks']
print(f"CHECK 560 {label} MCP tools/list is exactly agents, tasks: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
