"""Task 549: the raw MCP CallToolResults of the GraphTraj server, no host and no model.

  python -I probe549.py <out.json> <server command...>     (run from a GraphTraj project root)
Sends initialize and the six progressive-disclosure calls over stdio and saves each response.
"""
from __future__ import annotations

import json
import subprocess
import sys

CALLS = [
    ('agents', {'action': 'discover'}),
    ('agents', {'action': 'describe', 'feature': 'wait'}),
    ('agents', {'action': 'describe', 'feature': 'wait', 'schema': True}),
    ('tasks', {'action': 'discover'}),
    ('tasks', {'action': 'describe', 'feature': 'task-delivery'}),
    ('tasks', {'action': 'describe', 'feature': 'task-delivery', 'schema': True}),
]


def main() -> int:
    out, command = sys.argv[1], sys.argv[2:]
    messages = [
        {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
         'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'probe549', 'version': '0'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
    ] + [{'jsonrpc': '2.0', 'id': i + 1, 'method': 'tools/call', 'params': {'name': t, 'arguments': a}}
         for i, (t, a) in enumerate(CALLS)]
    proc = subprocess.run(command, input=''.join(json.dumps(m) + '\n' for m in messages),
                          capture_output=True, text=True, timeout=120)
    responses = {}
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        responses[message.get('id')] = message
    saved = [{'tool': t, 'arguments': a, 'response': responses.get(i + 1, {'error': 'no response'})}
             for i, (t, a) in enumerate(CALLS)]
    with open(out, 'w') as handle:
        json.dump(saved, handle, ensure_ascii=False, indent=1)
    missing = [i + 1 for i in range(len(CALLS)) if i + 1 not in responses]
    print(f'server probe: {len(CALLS) - len(missing)}/{len(CALLS)} responses saved to {out}')
    if missing:
        print('stderr tail:', proc.stderr[-800:])
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
