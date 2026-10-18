"""Controlled MCP peer for the installed DSH client, not a product dispatcher."""
import json
import os
import sys

from agent_swarm.tool import Caller, Outcome, bind


class Backend:
    """Echo actual host context only after common business validation."""

    def operate(self, action: str, arguments: dict, binding: object) -> Outcome:
        """Return observable native context supplied by the DSH plugin."""
        return Outcome(result={'operation': action, 'caller': binding.caller.session,
                               'source': os.environ.get('DSH_AGENT_SOURCE')})


execute = bind(Backend(), Caller('fixture', None, os.environ.get('DSH_SESSION_ID', 'native-parent'), 'dsh'))
schema = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['discover', 'describe', 'execute']},
    'query': {'type': 'string'}, 'feature': {'type': 'string'}, 'arguments': {'type': 'object'},
}, 'required': ['action'], 'additionalProperties': False}
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'controlled-peer', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'agents', 'description': 'Controlled progressive peer', 'inputSchema': schema}]}
    elif method == 'tools/call':
        args = params['arguments']
        if args['action'] == 'discover':
            document, failed = {'features': [{'name': 'status', 'description': 'Read status'}]}, False
        elif args['action'] == 'describe':
            document, failed = {'name': 'status', 'input_schema': {
                'type': 'object', 'properties': {'agent': {'type': 'string'}}, 'additionalProperties': False,
            }}, False
        else:
            answer = execute({'action': args['feature'], **args.get('arguments', {})})
            document, failed = answer.document, answer.failed
        result = {'content': [{'type': 'text', 'text': json.dumps(document)}],
                  'structuredContent': document, 'isError': failed}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
