"""Native Claude Main's per-call association and single MCP control owner.

The trusted mod supplies current Session facts over the existing PID-verified
local transport. MCP arguments never select their caller. The native permission
chain still decides whether the MCP call is made; association does not approve it.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import threading
from typing import Callable
from uuid import UUID

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import connection_operation, worker_connection
from agent_swarm.discovery import handle_request
from agent_swarm.process import process_ancestors
from graphtraj.execution.agent_driver import AdapterDriver
from graphtraj.execution.runner_process import process_executable
from graphtraj.interfaces.agents import configured_archive
from graphtraj.runtimes.claude.mcp import serve


class NativeCalls:
    """Consume one current native association exactly once, never a startup ID."""

    def __init__(self, make_call: Callable[[str, Path], Callable], cwd: Path) -> None:
        """Bind the host's backend factory and permitted native working directory."""
        self.make_call = make_call
        self.cwd = cwd.resolve()
        self.pending: dict | None = None
        self.lock = threading.Lock()

    def context(self, document: dict) -> dict:
        """Accept only authenticated mod facts; this is not a model tool."""
        with self.lock:
            operation = document.get('operation')
            if operation == 'end':
                self.pending = None
                return {'ended': True}
            if operation != 'prepare' or set(document) != {'operation', 'session', 'cwd', 'agent', 'request'}:
                raise AgentsError('invalid-input', 'Expected one native per-call context.')
            if document['agent'] is not None:
                raise AgentsError('authority-denied', 'A native subagent cannot adopt the Main association.')
            if (not isinstance(document['session'], str)
                    or str(UUID(document['session'])) != document['session']
                    or Path(document['cwd']).resolve() != self.cwd
                    or not isinstance(document['request'], dict)):
                raise AgentsError('authority-denied', 'Native Session/cwd/request is invalid.')
            if self.pending is not None and self.pending != document:
                raise AgentsError('authority-denied', 'A different native call is already pending.')
            self.pending = copy.deepcopy(document)
            return {'prepared': True}

    def call(self, request: dict) -> AgentsResult:
        """Match the MCP request before consuming its host-supplied association."""
        with self.lock:
            native, self.pending = self.pending, None
        if native is None or native['request'] != request:
            raise AgentsError('authority-denied', 'No matching current native call association.')
        return handle_request(request, self.make_call(native['session'], self.cwd))


def native_parent(executable: Path) -> int:
    """Verify the actual native parent, not an environment assertion or PID flag."""
    parent = os.getppid()
    actual = process_executable(parent)
    if parent <= 1 or actual is None or actual.resolve() != executable.resolve():
        raise AgentsError('authority-denied', 'This host must be launched directly by the selected Claude CLI.')
    return parent


def main() -> None:
    """Serve MCP, or send one native mod context over its verified local channel."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['serve', 'context'])
    parser.add_argument('--config', required=True, type=Path)
    options = parser.parse_args()
    configuration = json.loads(options.config.read_text())
    if set(configuration) != {'root', 'cwd', 'claude', 'channel_file'}:
        raise ValueError('Expected root, cwd, claude and channel_file in the trusted host configuration.')
    root, cwd, executable, channel_file = (Path(configuration[key])
                                          for key in ('root', 'cwd', 'claude', 'channel_file'))
    if not all(path.is_absolute() for path in (root, cwd, executable, channel_file)):
        raise ValueError('Native host configuration paths must be absolute.')
    parent = native_parent(executable)
    if options.operation == 'context':
        endpoint = json.loads(channel_file.read_text())
        if endpoint['parent'] != parent:
            raise AgentsError('authority-denied', 'The context belongs to another native host.')
        print(json.dumps(connection_operation(endpoint['address'], json.load(sys.stdin), authenticate=True)))
        return
    if 'AGENT_SWARM_CONNECTION' in os.environ or 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        raise AgentsError('authority-denied', 'A bound child must use its existing owner, not adopt Main.')
    if Path.cwd().resolve() != cwd.resolve():
        raise ValueError('The native host cwd differs from the configured cwd.')
    control = AgentControl(root / '.graphtraj/swarm', {'claude': AdapterDriver(root, cwd)})
    archive = configured_archive(root)
    callers: dict[str, Callable] = {}

    def make_call(session: str, current: Path) -> Callable:
        """Retain the native root scope across calls and explicit Session resume."""
        if session not in callers:
            callers[session] = bind(control, Caller('claude-native', None, session, 'claude'), archive=archive)
        return callers[session]

    calls = NativeCalls(make_call, cwd)

    def authenticate(pid: int) -> None:
        """Require a live direct child of this same verified Claude process."""
        chain = process_ancestors(pid)
        if (os.getppid() != parent or len(chain) < 2 or chain[1] != parent
                or process_executable(parent) != executable.resolve()):
            raise AgentsError('authority-denied', 'The context sender is not owned by this native Claude host.')

    directory = channel_file.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with worker_connection(directory, calls.context, authenticate=authenticate) as address:
            # Exclusive creation prevents a second MCP owner replacing a live
            # association. A retained stale file requires explicit host cleanup.
            with channel_file.open('x') as stream:
                json.dump({'parent': parent, 'address': address}, stream)
            try:
                serve(sys.stdin, sys.stdout, cwd, native_call=calls.call)
            finally:
                channel_file.unlink()
    finally:
        for call in callers.values():
            status = call({'action': 'status'})
            if status.failed:
                raise RuntimeError('Cannot confirm native children before host shutdown.')
            pending = list(status.document['result']['agents'])
            owned = []
            while pending:
                agent = pending.pop()
                owned.append(agent)
                pending.extend(agent['children'])
            for agent in reversed(owned):
                if agent['state'] == 'active':
                    call({'action': 'interrupt', 'agent': agent['agent']})
                    stopped = call({'action': 'wait', 'agent': agent['agent'], 'timeout_seconds': 10})
                    if stopped.failed or stopped.document['result']['state'] != 'standby':
                        raise RuntimeError('Claude child stop was not confirmed at MCP shutdown.')


if __name__ == '__main__':
    main()
