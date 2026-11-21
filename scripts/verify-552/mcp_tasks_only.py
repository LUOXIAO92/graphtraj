"""Task 552: stdio relay that exposes only the `tasks` tool of the real production graphtraj-mcp (DSH S only).

  python -I mcp_tasks_only.py <graphtraj-mcp> [args...]

Why: DSH's `@deepseek-ai/dsh-mcp-client` row has no per-tool allow-list (its README config table lists transport,
serverName, command/args/env/cwd, url/headers, timeouts, reconnect only), and the production server publishes both
`agents` and `tasks` (graphtraj/interfaces/mcp.py docstring: 'Only agents and tasks are published'). Claude S uses
`--disallowedTools mcp__graphtraj__agents`, Codex S `mcp_servers.graphtraj.enabled_tools=["tasks"]`; DSH S gets this.

Every line is relayed unchanged, except: a `tools/list` result loses every tool whose name is not `tasks`, and a
client `tools/call` whose name is not `tasks` is answered here with a JSON-RPC error and never reaches the server.
Standard library only.
"""
import json
import subprocess
import sys
import threading

ALLOWED = 'tasks'


def main(command):
    server = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    pending_lists = set()
    lock = threading.Lock()

    def to_client(line):
        with lock:
            sys.stdout.write(line if line.endswith('\n') else line + '\n')
            sys.stdout.flush()

    def pump():
        for line in server.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                to_client(line)
                continue
            if isinstance(message, dict) and message.get('id') in pending_lists and 'result' in message:
                pending_lists.discard(message['id'])
                tools = message['result'].get('tools') or []
                message['result']['tools'] = [t for t in tools if t.get('name') == ALLOWED]
                line = json.dumps(message)
            to_client(line)

    threading.Thread(target=pump, daemon=True).start()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if isinstance(message, dict):
            if message.get('method') == 'tools/list':
                pending_lists.add(message.get('id'))
            elif message.get('method') == 'tools/call' and (message.get('params') or {}).get('name') != ALLOWED:
                to_client(json.dumps({'jsonrpc': '2.0', 'id': message.get('id'), 'error': {
                    'code': -32602, 'message': f"Unknown tool: {(message.get('params') or {}).get('name')}"}}))
                continue
        server.stdin.write(line if line.endswith('\n') else line + '\n')
        server.stdin.flush()
    server.stdin.close()
    return server.wait()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
