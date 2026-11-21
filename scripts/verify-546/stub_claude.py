"""Rehearsal stand-in for `claude` (verify-546 only). Everything it prints is invented; it calls no MCP server.

Init carries the real field names: mcp_servers (the server names of the --mcp-config file), tools, plugins,
plugin_warnings. Untrusted cwd (no file .stub-trusted, which the rehearsal's simulated Tu creates): only builtin
plugins and the 'project-scope-suppressed-untrusted' warning, and an agents call returns authority-denied, as Main
saw on 00 at 22:02. Trusted: plugin graphtraj-claude-host, no warning, the agents call succeeds.
READY prompt -> 'READY-546-CLAUDE'. Gate prompt -> 'READY-546-GATE'. PROBE-546 -> one invented agents status call.
Any other prompt (B/A's Main): reads the cwd project's .graphtraj/roles.yml; no role -> create returns the product's
real invalid-config error JSON (INVALID path); a role -> invented create success, one send (submitted), wait (valid
path; no agent record exists, so the verdict is NOT-HIT).
"""
import json
import os
import sys

if sys.argv[1:2] == ['--version']:
    print('0.0.0 (stub 546)')
    sys.exit(0)
prompt = sys.stdin.read()
model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'stub'
servers = []
if '--mcp-config' in sys.argv:
    with open(sys.argv[sys.argv.index('--mcp-config') + 1]) as handle:
        servers = sorted(json.load(handle)['mcpServers'])
trusted = os.path.exists('.stub-trusted')


def emit(value):
    print(json.dumps(value), flush=True)


emit({'type': 'system', 'subtype': 'init', 'model': model, 'apiKeySource': 'stub',
      'tools': ['Read'] + [f'mcp__{name}__agents' for name in servers],
      'mcp_servers': [{'name': name, 'status': 'connected'} for name in servers],
      'plugins': [{'name': 'cc-plugin-builtin-stub'}] + ([{'name': 'graphtraj-claude-host'}] if trusted else []),
      'plugin_warnings': [] if trusted else [{
          'type': 'project-scope-suppressed-untrusted',
          'message': '1 project-scope directory under ./.claude/skills/ was skipped because this workspace was not '
                     'trusted (stub text)'}]})
if prompt.startswith('PROBE-546'):
    call = {'action': 'execute', 'feature': 'status', 'arguments': {}}
    text = ('action: status\nresult:\n  agents: []  # stub, invented' if trusted else
            'action: status\nerror:\n  code: authority-denied\n  message: No matching current native call association (stub)')
    emit({'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': 'stub-1', 'name': 'mcp__graphtraj__agents', 'input': call}]}})
    emit({'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': 'stub-1', 'is_error': not trusted,
         'content': [{'type': 'text', 'text': text}]}]}})
    emit({'type': 'result', 'result': 'PROBE-546 DONE'})
elif 'READY-546-CLAUDE' in prompt:
    emit({'type': 'result', 'result': 'READY-546-CLAUDE'})
elif 'READY-546-GATE' in prompt:
    emit({'type': 'result', 'result': 'READY-546-GATE'})
else:
    # B/A's Main. Without a role in .graphtraj/roles.yml: create fails with the product's real error JSON (as Main saw
    # at 22:12) and the Main stops. With one: an invented create success, then one invented send (submitted).
    import yaml
    roles = (yaml.safe_load(open('.graphtraj/roles.yml')) or {}).get('roles') or {}

    def tool(n, args, result, error=False):
        emit({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': f'stub-{n}', 'name': 'mcp__graphtraj__agents',
             'input': {'action': 'execute', **args}}]}})
        emit({'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': f'stub-{n}', 'is_error': error,
             'content': [{'type': 'text', 'text': json.dumps(result)}]}]}})

    create = {'feature': 'create', 'arguments': {'runtime': 'claude', 'name': 'probe546',
                                                 'instruction': 'Reply with exactly the word: first'}}
    if not roles:
        tool(1, create, {'error': {'code': 'invalid-config', 'message': "Configure one role named 'claude' or "
                                   "exactly one role using it; found none."}}, error=True)
        emit({'type': 'result', 'result': 'SEND: none (create failed)'})
    else:
        tool(1, create, {'action': 'create', 'result': {'agent': 'agent-stub546', 'execution': 'exec-stub-1',
                                                        'state': 'active'}})
        tool(2, {'feature': 'send', 'arguments': {'agent': 'agent-stub546', 'message': 'Reply with exactly the word: second'}},
             {'action': 'send', 'result': {'execution': 'exec-stub-1', 'delivery': {'delivery': 'submitted'}}})
        tool(3, {'feature': 'wait', 'arguments': {'agent': 'agent-stub546', 'timeout_seconds': 120}},
             {'action': 'wait', 'result': {'state': 'standby', 'timed_out': False}})
        emit({'type': 'result', 'result': 'SEND 1: submitted'})
