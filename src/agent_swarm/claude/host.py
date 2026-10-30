"""Independent Claude Main entry using native mod identity and agents MCP."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import TextIO
from uuid import UUID

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, __version__, bind
from agent_swarm.connection import connection_operation, worker_connection
from agent_swarm.discovery import handle_request
from agent_swarm.process import process_ancestors, process_executable
from agent_swarm.calls import on_discard, stop_requested
from agent_swarm.mcp import serve, serve_concurrent, respond, tool_documents, result_response, error_response
from agent_swarm.notices import END_EVENTS, notice_id
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


REFUSAL_FILE = 'host-refusal.json'


@contextmanager
def ended_by_claude():
    """Log Claude Code ending the session (SIGINT) as one stop line, not a crash."""
    try:
        yield
    except KeyboardInterrupt:
        print(time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'agents host stopped: Claude Code ended the session (SIGINT).', flush=True)


def serve_until_ended(mcp_in: TextIO, mcp_out: TextIO, responder) -> None:
    """Serve MCP; Claude Code ending the session (SIGINT) is a stop, not a crash."""
    with ended_by_claude():
        serve(mcp_in, mcp_out, responder)


def report_missing_host(channel_file: Path) -> None:
    """Exit the mod's context step with the refusal reason in one line, never a traceback."""
    record = channel_file.parent.parent / REFUSAL_FILE
    try:
        reason = json.loads(record.read_text(encoding='utf-8'))
        print(f"{reason['code']}: {reason['message']}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError):
        print('The agents host for this project is not running; see '
              f"{channel_file.parent.parent / 'host.log'}.", file=sys.stderr)
    raise SystemExit(1)


def serve_refusal(error: Exception, log: Path, descriptors=tool_documents,
                  server: dict | None = None) -> None:
    """Keep a refused start readable instead of exiting before the MCP handshake.

    Claude Code reports only CONNECTION_CLOSED for a server that exits before
    it answers. The reason goes to ``log`` and to stderr, and the server then
    answers every call of the ``descriptors`` tools with it. No control,
    channel or Agent is created, so every startup check remains in force.
    """
    reason = {'code': getattr(error, 'code', 'host-unavailable'),
              'message': f'The agents host did not start: {error}'}
    print(reason['message'], file=sys.stderr, flush=True)
    mcp_in, mcp_out = isolate_stdio(log)
    print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), json.dumps(reason, ensure_ascii=False), flush=True)
    # The native mod's context step reads this instead of a missing channel.
    record = log.with_name(REFUSAL_FILE)
    record.write_text(json.dumps(reason, ensure_ascii=False), encoding='utf-8')

    def call(identity: object, params: dict) -> dict:
        """Answer each call with the startup reason; nothing is executed."""
        document = {'error': reason}
        return result_response(identity, {'content': [{'type': 'text', 'text': json.dumps(document, ensure_ascii=False)}],
                                          'structuredContent': document, 'isError': True})

    try:
        serve_until_ended(mcp_in, mcp_out, lambda message: respond(
            message, descriptors, call, server or {'name': 'agents', 'version': __version__}))
    finally:
        record.unlink(missing_ok=True)


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


def codex_driver(settings: dict, cwd: Path):
    """Build a Codex driver from a ``codex.host --settings`` document; refuse it now if invalid."""
    from agent_swarm.codex.driver import CodexDriver

    driver = CodexDriver(settings)
    driver.prepare('codex', Caller('claude-native', None))
    return driver


def dsh_driver(settings: dict, cwd: Path):
    """Build a DSH driver for children in ``cwd``; refuse missing or unsupported DSH now."""
    from agent_swarm.dsh.driver import DshDriver

    driver = DshDriver(cwd, settings)
    driver.prepare('dsh', Caller('claude-native', None))
    return driver


# Runtime name -> driver factory taking that Runtime's ``runtimes`` entry and
# the host's working directory. Pi is not supported by this host yet.
RUNTIME_DRIVERS = {'codex': codex_driver, 'dsh': dsh_driver}


def runtime_drivers(cwd: Path, settings: dict, runtimes: object) -> dict:
    """Return the host's own Claude driver plus one driver per ``runtimes`` entry."""
    if not isinstance(runtimes, dict) or not all(isinstance(entry, dict) for entry in runtimes.values()):
        raise AgentsError('invalid-config', 'runtimes must map each Runtime name to its driver settings object.')
    drivers = {'claude': ClaudeDriver(cwd, settings)}
    for name, entry in runtimes.items():
        if name == 'claude':
            raise AgentsError('invalid-config', 'Claude children take the host settings, not runtimes.claude.')
        if name not in RUNTIME_DRIVERS:
            raise AgentsError('unsupported-runtime',
                              f'The Claude Code host does not support Runtime {name!r} yet.')
        drivers[name] = RUNTIME_DRIVERS[name](entry, cwd)
    return drivers


class IndependentCalls(NativeCalls):
    """Bind the verified native Main and hold its execution notices until one reader claims them."""

    def __init__(self, root: Path, cwd: Path, settings: dict, runtimes: dict | None = None) -> None:
        """Own one independent backend; no project configuration is discovered."""
        self.queue: dict[str, list[dict]] = {}
        self.claimed: dict[str, dict[str, dict]] = {}
        self.ended: dict[str, set[str]] = {}
        self.callers: dict[str, object] = {}
        self.control = AgentControl(root, runtime_drivers(cwd, settings, {} if runtimes is None else runtimes),
                                    event_receiver=self.receive, request_notices=True)
        super().__init__(self.make_call, cwd)

    def make_call(self, session: str, cwd: Path):
        """Bind only a Session already verified by NativeCalls.context."""
        with self.lock:
            if session not in self.callers:
                self.callers[session] = bind(self.control, Caller('claude-native', None, session, 'claude'))
        def call(tool: str, request: dict) -> AgentsResult:
            """Expose agents only through the verified native association."""
            if tool != 'agents':
                raise AgentsError('invalid-input', 'The independent host exposes agents only.')
            result = handle_request(request, self.callers[session])
            # Reuse the native host's next-result delivery when prompt push is
            # unavailable (notably print mode); the mod renders this same fact.
            # A cancelled call's result is never shown, so it hands over nothing.
            if stop_requested():
                return result
            seen = [] if result.failed else seen_ends(request, result.document)
            with self.lock:
                self.ended.setdefault(session, set()).update(seen)
                notices = self.claim(session)
            on_discard(lambda: self.restore(session, notices, seen))
            if not notices:
                return result
            return AgentsResult({**result.document, 'main_notices': notices}, failed=result.failed)
        return call

    def receive(self, event: dict) -> bool | str:
        """Queue an end or native request its creating Main must handle for that Main's mod to submit."""
        session = (event.get('creator') or {}).get('session')
        if event['parent'] is not None or session not in self.callers:
            return False
        message = event['body'] or (event.get('error') or {}).get('message') or event['outcome']
        with self.lock:
            self.queue.setdefault(session, []).append({
                'id': notice_id(event['execution'], event['outcome'], event.get('request')),
                'event': {'alias': event['agent'], 'event': event['outcome'],
                          'message': message, 'execution': event['execution']}})
        return 'queued'

    def claim(self, session: str) -> list[dict]:
        """Take this Session's queued notices once; an end already shown is skipped. Hold the lock."""
        taken, self.queue[session] = self.queue.get(session, []), []
        ended = self.ended.get(session, set())
        taken = [notice for notice in taken if not (notice['event']['execution'] in ended
                                                    and notice['event']['event'] in END_EVENTS)]
        self.claimed.setdefault(session, {}).update((notice['id'], notice) for notice in taken)
        return taken

    def restore(self, session: str, notices: list[dict], seen: list[str]) -> None:
        """Undo one result's hand-over when its caller cancelled before reading it."""
        with self.lock:
            self.ended.get(session, set()).difference_update(seen)
            self.queue.setdefault(session, []).extend(notices)

    def notices(self, document: dict) -> dict:
        """Serve the mod's claim/requeue protocol; the caller holds the lock."""
        session = document.get('session')
        if (not isinstance(session, str) or str(UUID(session)) != session
                or set(document) - {'operation', 'session', 'position', 'ids'}):
            raise AgentsError('invalid-input', 'Expected one native notice operation.')
        if document['operation'] == 'notices':
            return {'notices': self.claim(session), 'position': 0}
        if document['operation'] == 'requeue':
            ids = document.get('ids')
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise AgentsError('invalid-input', 'Expected the notice ids to queue again.')
            claimed = self.claimed.get(session, {})
            waiting = {notice['id'] for notice in self.queue.get(session, [])}
            again = [claimed[item] for item in ids if item in claimed and item not in waiting]
            self.queue.setdefault(session, []).extend(again)
            return {'requeued': len(again)}
        if type(document.get('position')) is not int:
            raise AgentsError('invalid-input', 'Expected the position returned by notices.')
        return {'acknowledged': True}


def seen_ends(request: dict, document: dict) -> list[str]:
    """Executions whose end one ``wait`` or ``status`` result showed the Main."""
    result = document.get('result')
    if (request.get('action') != 'execute' or request.get('feature') not in {'wait', 'status'}
            or not isinstance(result, dict) or result.get('state') != 'standby'
            or not isinstance(result.get('last_result'), dict)):
        return []
    return [result['last_result'].get('id')]


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
    # Until the configuration names the channel, a refusal is logged beside it.
    log = options.config.absolute().parent / 'host.log'
    try:
        configuration = json.loads(options.config.read_text())
        if set(configuration) - {'root', 'cwd', 'claude', 'channel_file', 'settings', 'runtimes'}:
            raise ValueError('Unknown native host configuration fields.')
        root, cwd, executable, channel_file = (Path(configuration[key])
                                              for key in ('root', 'cwd', 'claude', 'channel_file'))
        if not all(p.is_absolute() for p in (root, cwd, executable, channel_file)):
            raise ValueError('Native host paths must be absolute.')
    except Exception as error:
        if options.operation == 'context':
            raise
        serve_refusal(ValueError(f'{options.config}: {error}'), log)
        return
    if options.operation == 'context':
        if not channel_file.exists():
            report_missing_host(channel_file)
        endpoint = json.loads(channel_file.read_text())
        parent = native_parent(Path(endpoint['executable']), stage='context')
        if endpoint['parent'] != parent:
            raise AgentsError('authority-denied', 'The context belongs to another native host.')
        print(json.dumps(connection_operation(endpoint['address'], json.load(sys.stdin), authenticate=True)))
        return
    executable = executable.resolve()
    directory = channel_file.parent
    try:
        parent = native_parent(executable)
        if 'AGENT_SWARM_CONNECTION' in os.environ:
            raise AgentsError('authority-denied', 'A bound child must use its existing owner.')
        if Path.cwd().resolve() != cwd.resolve():
            raise ValueError(f'Claude Code was started in {Path.cwd().resolve()}, but this host is configured '
                             f'for {cwd.resolve()}. Start or resume Claude Code from {cwd.resolve()}.')
        if channel_file.exists():
            raise AgentsError('host-busy', f'{channel_file} exists: another agents host for this project is '
                              'running, or a previous one was killed. Close the other Claude Code session; '
                              'if none is running, delete the file.')
        calls = IndependentCalls(root, cwd, configuration.get('settings', {}), configuration.get('runtimes'))
        calls.control.require_connections()
    except Exception as error:
        serve_refusal(error, directory.parent / 'host.log')
        return

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

    directory.mkdir(parents=True, exist_ok=True)
    (directory.parent / REFUSAL_FILE).unlink(missing_ok=True)
    try:
        with worker_connection(directory, calls.context, authenticate=authenticate) as address:
            with channel_file.open('x') as stream:
                json.dump({'parent': parent, 'executable': str(executable), 'address': address}, stream)
            try:
                mcp_in, mcp_out = isolate_stdio(directory.parent / 'host.log')
                with ended_by_claude():
                    serve_concurrent(mcp_in, mcp_out, lambda message: respond(
                        message, tool_documents, call, {'name': 'agents', 'version': __version__}))
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
