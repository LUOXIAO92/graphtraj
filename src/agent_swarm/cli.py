"""Independent CLI over the same authenticated callback used by MCP.

Run ``python -m agent_swarm.cli '<discovery/describe/execute JSON>'`` inside
an already bound host. The CLI never adopts an identity from its arguments or
creates a second control backend. Without its own owner connection, an
installed host package (entry point group ``agent_swarm.hosts``) may claim the
call with the same dispatch its MCP ``agents`` entry uses.
"""
from __future__ import annotations

import argparse
from importlib.metadata import entry_points
import json
import os
from pathlib import Path
from typing import Callable

from agent_swarm.connection import CONNECTION_ENV, call_owner
from agent_swarm.discovery import handle_request
from agent_swarm.tool import AgentsError, AgentsResult


def host_dispatch() -> Callable[[dict], AgentsResult] | None:
    """Return the first installed host's dispatch that claims this process, if any."""
    if CONNECTION_ENV in os.environ:
        return None
    for entry in entry_points(group='agent_swarm.hosts'):
        dispatch = entry.load()(Path.cwd())
        if dispatch is not None:
            return dispatch
    return None


def main() -> None:
    """Print one structured result and exit nonzero on a rejected request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', help='One discover, describe or execute JSON object.')
    arguments = parser.parse_args()
    try:
        request = json.loads(arguments.request)
        if not isinstance(request, dict):
            raise AgentsError('invalid-input', 'The request must be a JSON object.')
        dispatch = host_dispatch()
        result = handle_request(request, dispatch) if dispatch is not None else call_owner(request)
        document, failed = result.document, result.failed
    except (AgentsError, json.JSONDecodeError) as error:
        code = error.code if isinstance(error, AgentsError) else 'invalid-input'
        document = {'error': {'code': code, 'message': str(error)}}
        failed = True
    print(json.dumps(document, ensure_ascii=False))
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
