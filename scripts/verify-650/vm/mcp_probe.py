"""Task 650 O8 probe: a minimal stdio MCP server (standard library only). It first appends one JSON line naming the
Python that runs it (sys.executable, sys._base_executable, prefix, argv, parent pid) to the file given as its first
argument, then answers initialize, tools/list (no tools) and ping until stdin ends. Which Python ran tells how Claude
Code expanded ``${PROBE_650_PYTHON:-<base python>}`` in a plugin's mcpServers command."""
import json
import os
import sys

with open(sys.argv[1], 'a', encoding='utf-8') as record:
    record.write(json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'executable': sys.executable,
                             'base_executable': getattr(sys, '_base_executable', None), 'prefix': sys.prefix,
                             'argv': sys.orig_argv}) + '\n')
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if 'id' not in message:
        continue
    method = message.get('method')
    if method == 'initialize':
        result = {'protocolVersion': (message.get('params') or {}).get('protocolVersion', '2024-11-05'),
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'probe650', 'version': '0.0.1'}}
    elif method == 'tools/list':
        result = {'tools': []}
    else:
        result = {}
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}) + '\n')
    sys.stdout.flush()
