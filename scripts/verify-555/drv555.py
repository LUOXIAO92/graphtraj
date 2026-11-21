"""verify-555 demo driver: a stand-in for the native DSH process (standard library only).

steps.zsh copies this file into a fake DSH package (``BASE/demo/dsh/lib/bin.py``)
and runs it with the candidate venv's Python, because the real graftling DSH
host accepts only a parent whose executable and entry the plugin named. It then
starts, as its own children:

1. the real owning host ``python -m graftling.dsh.host --config <file>``, given
   the native Session header whose cwd is the demo workspace;
2. the real stdio MCP entry ``agents-mcp`` (the venv's console script) with
   ``GRAFTLING_CONNECTION`` set to that host's channel, fed one JSON-RPC line
   per demo request.

Usage: python <bin.py> <demo.json> <transcript.jsonl>. ``demo.json`` holds
``{"config", "workspace", "agents_mcp", "cases": [{"name", "request"}]}``.
Prints one line per case: its name and the tool result (structuredContent).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> None:
    """Run the host and agents-mcp, print and record each case's result."""
    demo       = json.load(open(sys.argv[1], encoding='utf-8'))
    transcript = open(sys.argv[2], 'w', encoding='utf-8')
    launch     = {'header': {'version': 4, 'id': 'dsh-main-555', 'cwd': demo['workspace'], 'isSeeded': False},
                  'model': 'none'}

    # The real owning host: it verifies that this process is its parent.
    host = subprocess.Popen([sys.executable, '-m', 'graftling.dsh.host', '--config', demo['config']],
                            cwd=demo['workspace'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    host.stdin.write(json.dumps(launch) + '\n')
    host.stdin.flush()
    first = host.stdout.readline()
    if not first:
        print('HOST REFUSED:', host.stderr.read().strip())
        raise SystemExit(1)
    address = json.loads(first)['connection']
    print(f'owning host: graftling.dsh.host pid {host.pid}, channel {address}')

    # The real agents-mcp stdio entry, a direct child of this "native DSH".
    lines = [json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {}})]
    lines += [json.dumps({'jsonrpc': '2.0', 'id': index + 1, 'method': 'tools/call',
                          'params': {'name': 'agents', 'arguments': case['request']}})
              for index, case in enumerate(demo['cases'])]
    env = {**os.environ, 'GRAFTLING_CONNECTION': address, 'DSH_SESSION_ID': 'dsh-main-555',
           'DSH_AGENT_SOURCE': 'main'}
    mcp = subprocess.run([demo['agents_mcp']], cwd=demo['workspace'], env=env, input='\n'.join(lines) + '\n',
                         capture_output=True, text=True, timeout=120)
    for line in lines:
        transcript.write(json.dumps({'sent': json.loads(line)}) + '\n')
    replies = [json.loads(line) for line in mcp.stdout.splitlines()]
    for reply in replies:
        transcript.write(json.dumps({'received': reply}, ensure_ascii=False) + '\n')
    print('agents-mcp serverInfo:', json.dumps(replies[0]['result']['serverInfo']))
    for case, reply in zip(demo['cases'], replies[1:]):
        result = reply['result']
        print(f"\n[{case['name']}] isError={result['isError']}")
        print('  request:', json.dumps(case['request'], ensure_ascii=False))
        print('  result: ', json.dumps(result['structuredContent'], ensure_ascii=False))

    host.stdin.close()
    print(f'\nowning host exit: {host.wait(30)}; agents-mcp exit: {mcp.returncode}')


if __name__ == '__main__':
    main()
