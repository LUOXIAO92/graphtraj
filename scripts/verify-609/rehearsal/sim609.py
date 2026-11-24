import json, sys
from pathlib import Path
from graftling import AgentControl, Caller, bind
from graftling.discovery import handle_request
class D:
    def require_available(self, c): pass
    def prepare(self, *a, **k): raise AssertionError('no child in this simulation')
root, out = Path(sys.argv[1]), sys.argv[2]
call = bind(AgentControl(root, {'pi': D()}), Caller('rehearsal', None, 'sim', 'pi'))
with open(out, 'w') as stream:
    for arguments, feature in (({'runtime': 'pi'}, 'models'),
                               ({'runtime': 'pi', 'name': 'l609-no-provider', 'instruction': 'Reply with exactly: L609'}, 'create'),
                               ({'runtime': 'pi', 'provider': 'anthropic', 'name': 'l609-undeclared', 'instruction': 'Reply with exactly: L609'}, 'create')):
        document = handle_request({'action': 'execute', 'feature': feature, 'arguments': arguments}, call).document
        stream.write(json.dumps({'type': 'tool_execution_end', 'result': {'content': [{'type': 'text', 'text': json.dumps(document)}]}}) + '\n')
