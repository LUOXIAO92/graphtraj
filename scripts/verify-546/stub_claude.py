"""Rehearsal stand-in for `claude` (verify-546 only). Everything it prints is invented; it calls no MCP server.

READY prompt -> init + 'READY-546-CLAUDE'. PROBE-546 prompt -> init listing mcp__graphtraj__agents, one invented agents
status tool_use/tool_result pair, 'PROBE-546 DONE'. Any other prompt (B/A's Main) -> init and a final text with no
agents call, so B/A print NOT-HIT.
"""
import json
import sys

if sys.argv[1:2] == ['--version']:
    print('0.0.0 (stub 546)')
    sys.exit(0)
prompt = sys.stdin.read()
model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'stub'


def emit(value):
    print(json.dumps(value), flush=True)


emit({'type': 'system', 'subtype': 'init', 'model': model, 'apiKeySource': 'stub',
      'tools': ['Read', 'mcp__graphtraj__agents'], 'mcp_servers': [{'name': 'graphtraj', 'status': 'stub'}]})
if prompt.startswith('PROBE-546'):
    call = {'action': 'execute', 'feature': 'status', 'arguments': {}}
    emit({'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': 'stub-1', 'name': 'mcp__graphtraj__agents', 'input': call}]}})
    emit({'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': 'stub-1', 'is_error': False,
         'content': [{'type': 'text', 'text': 'action: status\nresult:\n  agents: []  # stub, invented'}]}]}})
    emit({'type': 'result', 'result': 'PROBE-546 DONE'})
elif 'READY-546-CLAUDE' in prompt:
    emit({'type': 'result', 'result': 'READY-546-CLAUDE'})
else:
    emit({'type': 'result', 'result': 'stub: no agents call'})
