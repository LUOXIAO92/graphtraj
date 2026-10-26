"""Independent Claude Main entry using native mod identity and agents MCP."""
from __future__ import annotations
import argparse
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import TextIO
from uuid import UUID

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import connection_operation, worker_connection
from agent_swarm.discovery import handle_request
from agent_swarm.process import process_ancestors, process_executable
from agent_swarm.mcp import serve, respond, tool_documents, result_response, error_response
from .native_host import NativeCalls
from .driver import ClaudeDriver

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



class IndependentCalls(NativeCalls):
    """Bind the verified native Main and retain its execution notices until ACK."""

    def __init__(self, root: Path, cwd: Path, settings: dict) -> None:
        """Own one independent backend; no project configuration is discovered."""
        self.queue: dict[str, list[dict]] = {}
        self.acknowledged: dict[str, int] = {}
        # Sessions whose notices the mod read and has not yet submitted.
        self.pushing: set[str] = set()
        self.callers: dict[str, object] = {}
        self.control = AgentControl(root, {'claude': ClaudeDriver(cwd, settings)},
                                    event_receiver=self.receive)
        super().__init__(self.make_call, cwd)

    def make_call(self, session: str, cwd: Path):
        """Bind only a Session already verified by NativeCalls.context."""
        if session not in self.callers:
            self.callers[session] = bind(self.control, Caller('claude-native', None, session, 'claude'))
        def call(tool: str, request: dict) -> AgentsResult:
            """Expose agents only through the verified native association."""
            if tool != 'agents':
                raise AgentsError('invalid-input', 'The independent host exposes agents only.')
            result = handle_request(request, self.callers[session])
            # Reuse the native host's next-result delivery when prompt push is
            # unavailable (notably print mode); the mod renders this same fact.
            # Notices a push holds are delivered by that push or after its release.
            with self.lock:
                if session in self.pushing:
                    return result
                queue = self.queue.get(session, [])
                notices = queue[self.acknowledged.get(session, 0):]
                if not notices:
                    return result
                result = AgentsResult({**result.document, 'main_notices': notices}, failed=result.failed)
                self.acknowledged[session] = len(queue)
            return result
        return call

    def receive(self, event: dict) -> bool:
        """Queue the same completion fact for the native mod's prompt submission."""
        for session, caller in list(self.callers.items()):
            result = caller({'action': 'status', 'agent': event['agent']})
            if result.failed:
                continue
            with self.lock:
                self.queue.setdefault(session, []).append({'event': {
                    'alias': event['agent'], 'event': event['outcome'], 'message': event['body']}})
            return True
        return False

    def notices(self, document: dict) -> dict:
        """Return then acknowledge or release queued notices using the existing mod protocol.

        Read notices stay out of results until the mod acknowledges them after
        its submission, or releases them when submission failed.
        """
        session = document.get('session')
        if (not isinstance(session, str) or str(UUID(session)) != session
                or set(document) - {'operation', 'session', 'position'}):
            raise AgentsError('invalid-input', 'Expected one native notice operation.')
        queue = self.queue.get(session, [])
        acknowledged = self.acknowledged.get(session, 0)
        if document['operation'] == 'notices':
            if queue[acknowledged:]:
                self.pushing.add(session)
            return {'notices': queue[acknowledged:], 'position': len(queue)}
        if document['operation'] == 'release':
            self.pushing.discard(session)
            return {'released': True}
        position = document.get('position')
        if type(position) is not int or not acknowledged <= position <= len(queue):
            raise AgentsError('invalid-input', 'Expected the position returned by notices.')
        self.acknowledged[session] = position
        self.pushing.discard(session)
        return {'acknowledged': True}


def adoption_material(root: Path, claude: Path) -> dict[str, object]:
    """Return native plugin/MCP configuration without modifying trust or credentials."""
    root = root.resolve()
    config = root / '.agents-control' / 'claude-host.json'
    plugin = root / '.claude' / 'skills' / 'agents-claude-host'
    return {
        str(config): {'root': str(config.parent), 'cwd': str(root),
                      'claude': os.path.abspath(claude),
                      'channel_file': str(config.parent / 'live' / 'channel.json'), 'settings': {}},
        str(root / '.mcp.json'): {'mcpServers': {'agents': {
            'command': sys.executable,
            'args': ['-m', 'agent_swarm.claude.host', 'serve', '--config', str(config)],
        }}},
        str(root / '.claude/settings.local.json'): {'env': {
            'GRAPHTRAJ_CLAUDE_HOST_PYTHON': sys.executable,
            'GRAPHTRAJ_CLAUDE_HOST_CONFIG': str(config),
        }},
        str(plugin / '.claude-plugin/plugin.json'): {'name': 'agents-claude-host', 'version': '1',
            'description': 'Native Claude context for independent agents MCP.'},
        str(plugin / 'hooks/hooks.json'): {'modules': ['./host_context.mjs']},
        str(plugin / 'hooks/host_context.mjs'): Path(__file__).with_name('host_context.mjs').read_text(),
    }


def main() -> None:
    """Serve the native-owned MCP entry or install/forward its existing mod binding."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['serve', 'context', 'configuration'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--claude', type=Path)
    parser.add_argument('--write', action='store_true')
    options = parser.parse_args()
    if options.operation == 'configuration':
        if options.project is None or options.claude is None:
            parser.error('configuration requires --project and --claude')
        material = adoption_material(options.project, options.claude)
        if options.write:
            write_adoption(material)
        print(json.dumps(sorted(material) if options.write else material, ensure_ascii=False, indent=2))
        return
    if options.config is None:
        parser.error('serve/context requires --config')
    configuration = json.loads(options.config.read_text())
    if set(configuration) - {'root', 'cwd', 'claude', 'channel_file', 'settings'}:
        raise ValueError('Unknown native host configuration fields.')
    root, cwd, executable, channel_file = (Path(configuration[key])
                                          for key in ('root', 'cwd', 'claude', 'channel_file'))
    if not all(p.is_absolute() for p in (root, cwd, executable, channel_file)):
        raise ValueError('Native host paths must be absolute.')
    if options.operation == 'context':
        endpoint = json.loads(channel_file.read_text())
        parent = native_parent(Path(endpoint['executable']), stage='context')
        if endpoint['parent'] != parent:
            raise AgentsError('authority-denied', 'The context belongs to another native host.')
        print(json.dumps(connection_operation(endpoint['address'], json.load(sys.stdin), authenticate=True)))
        return
    executable = executable.resolve()
    parent = native_parent(executable)
    if 'AGENT_SWARM_CONNECTION' in os.environ or 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        raise AgentsError('authority-denied', 'A bound child must use its existing owner.')
    if Path.cwd().resolve() != cwd.resolve():
        raise ValueError('The native host cwd differs from the configured cwd.')
    calls = IndependentCalls(root, cwd, configuration.get('settings', {}))

    def authenticate(pid: int) -> None:
        """Accept context only from the direct child of this same native process."""
        chain = process_ancestors(pid)
        if (os.getppid() != parent or len(chain) < 2 or chain[1] != parent
                or process_executable(parent) != executable):
            raise AgentsError('authority-denied', 'The sender is not owned by this native Claude host.')

    def call(identity: object, params: dict) -> dict:
        """Return one progressive tool result after native caller verification."""
        if params.get('name') != 'agents' or not isinstance(params.get('arguments', {}), dict):
            return error_response(identity, -32602, 'Expected agents and object arguments.')
        try:
            result = calls.call(params.get('arguments', {}))
        except Exception as error:
            result = AgentsResult({'error': {'code': getattr(error, 'code', 'operation-failed'),
                                            'message': str(error)}}, failed=True)
        return result_response(identity, {'content': [{'type': 'text', 'text': json.dumps(result.document, ensure_ascii=False)}],
                                          'structuredContent': result.document, 'isError': result.failed})

    directory = channel_file.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with worker_connection(directory, calls.context, authenticate=authenticate) as address:
            with channel_file.open('x') as stream:
                json.dump({'parent': parent, 'executable': str(executable), 'address': address}, stream)
            try:
                mcp_in, mcp_out = isolate_stdio(directory.parent / 'host.log')
                serve(mcp_in, mcp_out, lambda message: respond(
                    message, tool_documents, call, {'name': 'agents', 'version': '0.1.0'}))
            finally:
                channel_file.unlink()
    finally:
        deadline = time.monotonic() + 10
        for agent in calls.control.interrupt_owned():
            while calls.control.owns_running(agent):
                if time.monotonic() > deadline:
                    raise RuntimeError('Claude stop was not confirmed at MCP shutdown.')
                time.sleep(0.05)


if __name__ == '__main__':
    main()
