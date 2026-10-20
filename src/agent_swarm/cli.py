"""Independent CLI over the same authenticated callback used by MCP.

Run ``python -m agent_swarm.cli '<discovery/describe/execute JSON>'`` inside
an already bound host. The CLI never adopts an identity from its arguments,
creates a second control backend, or forwards to a GraphTraj Task owner.
"""
from __future__ import annotations

import argparse
import json

from agent_swarm.connection import call_owner
from agent_swarm.tool import AgentsError


def main() -> None:
    """Print one structured result and exit nonzero on a rejected request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', help='One discover, describe or execute JSON object.')
    arguments = parser.parse_args()
    try:
        request = json.loads(arguments.request)
        if not isinstance(request, dict):
            raise AgentsError('invalid-input', 'The request must be a JSON object.')
        result = call_owner(request)
        document, failed = result.document, result.failed
    except (AgentsError, json.JSONDecodeError) as error:
        code = error.code if isinstance(error, AgentsError) else 'invalid-input'
        document = {'error': {'code': code, 'message': str(error)}}
        failed = True
    print(json.dumps(document, ensure_ascii=False))
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
