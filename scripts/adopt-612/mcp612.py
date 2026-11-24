"""612: the new graftling 0.10 surface as Main's MCP entry serves it. Read only; starts nothing but the server.

usage: mcp612.py <label> <project directory> <P arguments as JSON> <command> [args...]

Starts the MCP server command in the project directory (an isolated project, never the Harness) and sends, as
newline-delimited JSON-RPC: initialize, tools/list, then four tools/call requests:
  3  subagents {"action": "discover"}                      -> is graftling 0.10's feature `models` listed? (information)
  4  tasks {"action": "describe", "feature": "runtime_connections", "schema": true}
  5  subagents execute models {"runtime": "claude"}        -> GraphTraj answers unavailable (agents.py, 611)
  6  tasks {"action": "discover"}                          -> runtime_connections is a tasks feature

CHECKs: tools/list is exactly subagents, tasks; runtime_connections is listed by tasks discover; its describe schema
has `provider` and the action `discover`, and P's arguments fit the schema (only known properties, the action in
its enum, every value a string); subagents' `models` answers an error naming runtime_connections (so P uses tasks).
The server is closed by closing its stdin, and killed only if it ignores that for 20 s (it is this probe's child).
"""
import json
import subprocess
import sys
import threading

label, project, p_arguments, command = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4:]
process = subprocess.Popen(command, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
replies = {}
done    = threading.Event()
LAST    = 6


def reader() -> None:
    """Collect every JSON-RPC answer by id; stop waiting once the last one arrived."""
    for line in process.stdout:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if 'id' in message:
            replies[message['id']] = message
            if message['id'] == LAST:
                done.set()


def call(number: int, name: str, arguments: dict) -> dict:
    """One tools/call request."""
    return {'jsonrpc': '2.0', 'id': number, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}


def document(number: int) -> tuple[bool, object, str]:
    """(is an error, structured document or None, text) of one tools/call answer."""
    answer = replies.get(number) or {}
    if 'error' in answer:
        return True, None, json.dumps(answer['error'])[:400]
    result = answer.get('result') or {}
    text   = ' '.join(item.get('text', '') for item in result.get('content', []) if isinstance(item, dict))
    return bool(result.get('isError')), result.get('structuredContent'), text


threading.Thread(target=reader, daemon=True).start()
for message in ({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'probe-612', 'version': '0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                call(3, 'subagents', {'action': 'discover'}),
                call(4, 'tasks', {'action': 'describe', 'feature': 'runtime_connections', 'schema': True}),
                call(5, 'subagents', {'action': 'execute', 'feature': 'models', 'arguments': {'runtime': 'claude'}}),
                call(6, 'tasks', {'action': 'discover'})):
    process.stdin.write(json.dumps(message) + '\n')
    process.stdin.flush()
done.wait(90)
process.stdin.close()
try:
    process.wait(20)
except subprocess.TimeoutExpired:
    process.kill()

checks = []


def check(name: str, ok: bool, detail: str = '') -> None:
    """Print one CHECK line and keep its outcome."""
    checks.append(ok)
    print(f"CHECK 612 {label} {name}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")


tools = sorted(tool.get('name') for tool in (replies.get(2) or {}).get('result', {}).get('tools', []))
print(f'{label} server: {" ".join(command[:3])} | tools: {tools}')
if not tools:
    print(f'{label} stderr tail: {process.stderr.read()[-400:]!r}')
check('MCP tools/list is exactly subagents, tasks', tools == ['subagents', 'tasks'])

# 3: graftling's own feature list as GraphTraj's subagents entry serves it (information).
failed, found, text = document(3)
features = sorted(item.get('feature') for item in ((found or {}).get('features') or []) if isinstance(item, dict))
print(f'{label} subagents discover (information): error {failed} | features: {features or text[:300]}')
print(f"REPORT 612 {label} subagents discover lists graftling's 'models': {'yes' if 'models' in features else 'no'}")

# 4 and 6: runtime_connections is a tasks feature; its schema takes what P sends.
failed, found, text = document(6)
listed = sorted(item.get('feature') for item in ((found or {}).get('features') or []) if isinstance(item, dict))
check('tasks discover lists runtime_connections', not failed and 'runtime_connections' in listed,
      'error' if failed else f'{len(listed)} features')
failed, found, text = document(4)
schema     = (found or {}).get('input_schema') or {}
properties = schema.get('properties') or {}
actions    = (properties.get('action') or {}).get('enum') or []
print(f'{label} tasks describe runtime_connections: error {failed} | properties {sorted(properties)} | action enum {actions}')
check("runtime_connections schema has 'provider' and the action 'discover'",
      not failed and 'provider' in properties and 'discover' in actions)
fits = (set(p_arguments) <= set(properties) and p_arguments.get('action') in actions
        and all(isinstance(value, str) and value for value in p_arguments.values()))
check(f"P's arguments {json.dumps(p_arguments)} fit the runtime_connections schema", fits)

# 5: GraphTraj refuses graftling's `models` and names its own route.
failed, found, text = document(5)
answer = json.dumps(found)[:300] if found else text[:300]
print(f'{label} subagents execute models: error {failed} | {answer}')
check("subagents 'models' is refused and names runtime_connections (P uses tasks)",
      failed and 'runtime_connections' in (answer + text))
sys.exit(0 if all(checks) else 1)
