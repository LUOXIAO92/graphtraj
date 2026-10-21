"""Native Claude Main's per-call association and single MCP control owner.

The trusted mod supplies current Session facts over the existing PID-verified
local transport. MCP arguments never select their caller. The native permission
chain still decides whether the MCP call is made; association does not approve it.

The verified Main continues the project's Main working state through the
shared ``main_continuity`` record. Claude has no native entry event this host
can observe, so a Session's first control call in this host process is its
entry; reads never take control. ``agents`` and ``tasks`` share that identity.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import threading
import time
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
            if operation != 'prepare' or set(document) != {'operation', 'tool', 'session', 'cwd', 'agent', 'request'}:
                raise AgentsError('invalid-input', 'Expected one native per-call context.')
            if document['tool'] not in {'agents', 'tasks'}:
                raise AgentsError('invalid-input', 'Expected the agents or tasks entry.')
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

    def call(self, request: dict, tool: str = 'agents') -> AgentsResult:
        """Match the MCP request before consuming its host-supplied association."""
        with self.lock:
            native, self.pending = self.pending, None
        if native is None or native['request'] != request or native['tool'] != tool:
            raise AgentsError('authority-denied', 'No matching current native call association.')
        return self.make_call(native['session'], self.cwd)(tool, request)


def native_parent(executable: Path, *, stage: str = 'serve') -> int:
    """Verify the actual native parent, not an environment assertion or PID flag."""
    parent = os.getppid()
    actual = process_executable(parent)
    expected = executable.resolve()
    if parent <= 1 or actual is None or actual.resolve() != expected:
        # Keep only process/path facts, never argv, environment or credentials.
        facts = {'stage': stage, 'parent_pid': parent,
                 'observed_executable': str(actual) if actual is not None else None,
                 'expected_executable': str(expected)}
        raise AgentsError('authority-denied',
                          'This host must be launched directly by the selected Claude CLI. '
                          + json.dumps(facts, sort_keys=True))
    return parent


def main_calls(root: Path, control: AgentControl, archive: object) -> Callable[[str, Path], Callable]:
    """Return the per-Session factory serving one verified Main's agents and tasks calls.

    Each call runs as Main (Runner caller ``None``) with this Session's host
    connection, so dispatched roots record it as their owner. A Session's
    first control call in this process claims Main (``main_continuity``); after
    another Main continues the project, its control calls are refused until a
    new host process. Queued member notices are returned with the next result.
    """
    from graphtraj.execution.main_continuity import claimable, take_notices
    from graphtraj.execution.runner_connection import parent_connection
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request as handle_task

    runner = root / '.graphtraj' / 'runner'
    callers: dict[str, Callable] = {}
    # Sessions that already entered as Main in this process.
    claimed: set[str] = set()

    def make_call(session: str, current: Path) -> Callable:
        """Bind one verified Main Session; the model request never selects it."""
        if session not in callers:
            callers[session] = bind(control, Caller('claude-native', None, session, 'claude'), archive=archive)
        connection = {'runtime': 'claude', 'session': session, 'runner': str(runner)}

        def call(tool: str, request: dict) -> AgentsResult:
            """Run one call as this Main; return queued Main notices with it."""
            entry = None if session in claimed else (lambda: claimed.add(session))
            with claimable(entry), parent_connection(connection):
                if tool == 'agents':
                    result = handle_request(request, callers[session])
                else:
                    with runtime_caller(runner, None):
                        result = handle_task(request, cwd=root)
            notices = take_notices(runner, 'claude', session)
            if notices:
                result = AgentsResult({**result.document, 'main_notices': notices}, failed=result.failed)
            return result

        return call

    return make_call


def adoption_material(root: Path, claude: Path) -> dict:
    """Return the files a user adopts to host Claude Code Main in one project.

    Nothing is written or trusted here: the user places the material and
    Claude Code's own project MCP approval and mod trust decide adoption.
    The host configuration names the Claude CLI that must launch this host.
    """
    root, claude = root.resolve(), claude.resolve()
    config = root / '.graphtraj' / 'claude-host' / 'config.json'
    python = Path(sys.executable)
    return {
        config.as_posix(): {
            'root': str(root), 'cwd': str(root), 'claude': str(claude),
            'channel_file': str(config.parent / 'live' / 'channel.json'),
        },
        (root / '.mcp.json').as_posix(): {'mcpServers': {'agents': {
            'command': str(python),
            'args': ['-m', 'graphtraj.runtimes.claude.host', 'serve', '--config', str(config)],
        }}},
        (root / '.claude' / 'settings.local.json').as_posix(): {'env': {
            'GRAPHTRAJ_CLAUDE_HOST_PYTHON': str(python),
            'GRAPHTRAJ_CLAUDE_HOST_CONFIG': str(config),
        }},
        'mod': str(Path(__file__).with_name('host_context.mjs')),
    }


def main() -> None:
    """Serve MCP, send one native mod context, or print adoption material."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['serve', 'context', 'configuration'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--project', type=Path, help='Harness Project Root for configuration.')
    parser.add_argument('--claude', type=Path, help='Claude CLI executable for configuration.')
    options = parser.parse_args()
    if options.operation == 'configuration':
        if options.project is None or options.claude is None:
            parser.error('configuration requires --project and --claude')
        print(json.dumps(adoption_material(options.project, options.claude), indent=2, ensure_ascii=False))
        return
    if options.config is None:
        parser.error(f'{options.operation} requires --config')
    configuration = json.loads(options.config.read_text())
    if set(configuration) != {'root', 'cwd', 'claude', 'channel_file'}:
        raise ValueError('Expected root, cwd, claude and channel_file in the trusted host configuration.')
    root, cwd, executable, channel_file = (Path(configuration[key])
                                          for key in ('root', 'cwd', 'claude', 'channel_file'))
    if not all(path.is_absolute() for path in (root, cwd, executable, channel_file)):
        raise ValueError('Native host configuration paths must be absolute.')
    if options.operation == 'context':
        endpoint = json.loads(channel_file.read_text())
        # The owner already verified its CLI at startup. A launcher symlink
        # may move during an update while that same native process is alive.
        # Use its pinned executable, never whichever version is selected now.
        parent = native_parent(Path(endpoint['executable']), stage='context')
        if endpoint['parent'] != parent:
            raise AgentsError('authority-denied', 'The context belongs to another native host.')
        print(json.dumps(connection_operation(endpoint['address'], json.load(sys.stdin), authenticate=True)))
        return
    executable = executable.resolve()
    parent = native_parent(executable)
    if 'AGENT_SWARM_CONNECTION' in os.environ or 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        raise AgentsError('authority-denied', 'A bound child must use its existing owner, not adopt Main.')
    if Path.cwd().resolve() != cwd.resolve():
        raise ValueError('The native host cwd differs from the configured cwd.')
    from graphtraj.execution.main_continuity import MainRoots

    runner = root / '.graphtraj' / 'runner'
    control = AgentControl(root / '.graphtraj/swarm', {'claude': AdapterDriver(root, cwd)},
                           roots=MainRoots(runner))
    make_call = main_calls(root, control, configured_archive(root))
    calls = NativeCalls(make_call, cwd)

    def authenticate(pid: int) -> None:
        """Require a live direct child of this same verified Claude process."""
        chain = process_ancestors(pid)
        if (os.getppid() != parent or len(chain) < 2 or chain[1] != parent
                or process_executable(parent) != executable):
            raise AgentsError('authority-denied', 'The context sender is not owned by this native Claude host.')

    directory = channel_file.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with worker_connection(directory, calls.context, authenticate=authenticate) as address:
            # Exclusive creation prevents a second MCP owner replacing a live
            # association. A retained stale file requires explicit host cleanup.
            with channel_file.open('x') as stream:
                json.dump({'parent': parent, 'executable': str(executable), 'address': address}, stream)
            try:
                serve(sys.stdin, sys.stdout, cwd, native_call=calls.call)
            finally:
                channel_file.unlink()
    finally:
        # Stop the native work this process runs, whichever Main created it.
        deadline = time.monotonic() + 10
        for agent in control.interrupt_owned():
            while control.owns_running(agent):
                if time.monotonic() > deadline:
                    raise RuntimeError('Claude child stop was not confirmed at MCP shutdown.')
                time.sleep(0.05)


if __name__ == '__main__':
    main()
