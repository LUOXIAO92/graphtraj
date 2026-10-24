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
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable, TextIO
from uuid import UUID

from agent_swarm.claude import native_host
from agent_swarm import AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import connection_operation, worker_connection
from agent_swarm.discovery import handle_request
from agent_swarm.process import process_ancestors
from graphtraj.execution.runner_process import process_executable
from graphtraj.interfaces.agents import GraphTrajAgents, configured_archive
from graphtraj.runtimes.claude.mcp import serve


from agent_swarm.claude.native_host import NativeCalls as NativeCallsBase


class NativeCalls(NativeCallsBase):
    """Supply GraphTraj's durable Main notice queue to the native association."""

    def notices(self, document: dict) -> dict:
        """Let the mod push queued notices into the idle Main, acknowledging after submit.

        Only the authenticated mod of this same Claude process reaches this.
        """
        from graphtraj.execution.main_continuity import acknowledge_notices, pending_notices

        session = document.get('session')
        if (self.runner is None or not isinstance(session, str) or str(UUID(session)) != session
                or set(document) - {'operation', 'session', 'position'}):
            raise AgentsError('invalid-input', 'Expected one native notice operation.')
        if document['operation'] == 'notices':
            notices, position = pending_notices(self.runner, 'claude', session)
            return {'notices': notices, 'position': position}
        if type(document.get('position')) is not int:
            raise AgentsError('invalid-input', 'Expected the position returned by notices.')
        acknowledge_notices(self.runner, 'claude', session, document['position'])
        return {'acknowledged': True}


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


def main_calls(root: Path, backend: object, archive: object) -> Callable[[str, Path], Callable]:
    """Return the per-Session factory serving one verified Main's agents and tasks calls.

    Each call runs as Main (Runner caller ``None``) with this Session's host
    connection, so dispatched roots record it as their owner. A Session's
    first control call in this process claims Main (``main_continuity``); after
    another Main continues the project, its control calls are refused until a
    new host process. ``backend`` is the same ``agents`` backend the Codex Main
    uses (``GraphTrajAgents``: every Runtime driver and Task member Sessions).
    Queued member notices not yet delivered are returned with each result and
    acknowledged only once that result is built; a pickup failure is reported
    beside the result and never fails the executed call.
    """
    from graphtraj.execution.main_continuity import acknowledge_notices, claimable, pending_notices
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
            callers[session] = bind(backend, Caller('claude-native', None, session, 'claude'), archive=archive)
        connection = {'runtime': 'claude', 'session': session, 'runner': str(runner)}

        def call(tool: str, request: dict) -> AgentsResult:
            """Run one call as this Main; return queued Main notices with it."""
            entry = None if session in claimed else (lambda: claimed.add(session))
            with claimable(entry), parent_connection(connection), runtime_caller(runner, None):
                if tool == 'agents':
                    result = handle_request(request, callers[session])
                else:
                    result = handle_task(request, cwd=root)
            try:
                notices, position = pending_notices(runner, 'claude', session)
            except Exception as error:
                return AgentsResult({**result.document, 'main_notices_error': str(error)}, failed=result.failed)
            if not notices:
                return result
            result = AgentsResult({**result.document, 'main_notices': notices}, failed=result.failed)
            try:
                acknowledge_notices(runner, 'claude', session, position)
            except Exception as error:
                # Unacknowledged notices are offered again; never fail the call.
                result.document['main_notices_error'] = str(error)
            return result

        return call

    return make_call


def isolate_stdio(log: Path) -> tuple[TextIO, TextIO]:
    """Reserve the MCP stdio for this host and send everything else to ``log``.

    Returns private streams over the original stdin/stdout. File descriptors
    0, 1 and 2 then point at /dev/null and the log, so stray output of any
    Task operation or subprocess can neither corrupt nor consume the MCP
    channel, and tracebacks are kept for diagnosis.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    mcp_in  = os.fdopen(os.dup(0), 'r', encoding='utf-8')
    mcp_out = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    sink = open(log, 'a', encoding='utf-8', buffering=1)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    os.dup2(sink.fileno(), 1)
    os.dup2(sink.fileno(), 2)
    sys.stdout = sys.stderr = sink
    faulthandler.enable(sink)
    return mcp_in, mcp_out


def adoption_material(root: Path, claude: Path) -> dict[str, object]:
    """Return every file a user adopts to host Claude Code Main in one project.

    Keys are absolute paths; a value is JSON content or, for the mod, its
    text. Nothing is written or trusted here: Claude Code loads the plugin
    directory under ``.claude/skills/`` and its own project MCP approval and
    trust prompts decide adoption. The host configuration names the Claude
    CLI that must launch this host.
    """
    # Keep the user's stable launcher (for example ~/.local/bin/claude), not the
    # versioned file it selects now: serve resolves it when it checks its parent,
    # so a Claude Code self-update does not invalidate this configuration.
    root, claude = root.resolve(), Path(os.path.abspath(claude))
    config = root / '.graphtraj' / 'claude-host' / 'config.json'
    plugin = root / '.claude' / 'skills' / 'graphtraj-claude-host'
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
        (plugin / '.claude-plugin' / 'plugin.json').as_posix(): {
            'name': 'graphtraj-claude-host', 'version': '1',
            'description': 'GraphTraj Main host context for the agents and tasks MCP entries.',
        },
        (plugin / 'hooks' / 'hooks.json').as_posix(): {'modules': ['./host_context.mjs']},
        (plugin / 'hooks' / 'host_context.mjs').as_posix():
            Path(native_host.__file__).with_name('host_context.mjs').read_text(encoding='utf-8'),
    }


def write_adoption(material: dict[str, object]) -> None:
    """Write printed adoption material: JSON values as JSON, the mod as text.

    An existing JSON file keeps its other settings: each top-level object
    (for example ``env`` or ``mcpServers``) is merged one level deep.
    """
    for path, content in material.items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(content, str) and target.exists():
            existing = json.loads(target.read_text(encoding='utf-8'))
            for key, value in content.items():
                existing[key] = ({**existing[key], **value}
                                 if isinstance(value, dict) and isinstance(existing.get(key), dict) else value)
            content = existing
        target.write_text(content if isinstance(content, str) else json.dumps(content, indent=2) + '\n',
                          encoding='utf-8')


def main() -> None:
    """Serve MCP, send one native mod context, or print adoption material."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['serve', 'context', 'configuration'])
    parser.add_argument('--write', action='store_true', help='Write the configuration material.')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--project', type=Path, help='Harness Project Root for configuration.')
    parser.add_argument('--claude', type=Path, help='Claude CLI executable for configuration.')
    options = parser.parse_args()
    if options.operation == 'configuration':
        if options.project is None or options.claude is None:
            parser.error('configuration requires --project and --claude')
        material = adoption_material(options.project, options.claude)
        if options.write:
            write_adoption(material)
        print(json.dumps(material if not options.write else sorted(material), indent=2, ensure_ascii=False))
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
    # The same agents view and control as the Codex Main: every Runtime driver,
    # continued Main roots (MainRoots) and Task member Sessions.
    agents = GraphTrajAgents(root, cwd)
    control = agents.control
    make_call = main_calls(root, agents, configured_archive(root))
    calls = NativeCalls(make_call, cwd, root / '.graphtraj' / 'runner')

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
                mcp_in, mcp_out = isolate_stdio(directory.parent / 'host.log')
                serve(mcp_in, mcp_out, cwd, native_call=calls.call)
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
