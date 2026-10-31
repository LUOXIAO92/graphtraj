"""Independent Claude Main entry using native mod identity and agents MCP."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import faulthandler
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import TextIO
from uuid import UUID

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, __version__, bind
from agent_swarm.connection import connection_operation, host_alive, worker_connection
from agent_swarm.discovery import handle_request
from agent_swarm.process import process_ancestors, process_executable
from agent_swarm.calls import on_discard, stop_requested
from agent_swarm.mcp import serve, serve_concurrent, respond, tool_documents, result_response, error_response
from agent_swarm.notices import notice_id
from agent_swarm.shutdown import exit_if_owned_unconfirmed, stop_owned
from .native_host import NativeCalls
from .driver import ClaudeDriver
from .plugin import claude_host_plugin, kept_host_paths, write_adoption

if os.name != 'nt':
    import fcntl


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


def report_missing_host(channel_file: Path, owner: dict | None = None) -> None:
    """Exit the mod's context step with the refusal reason in one line, never a traceback.

    ``owner`` is another Claude's live channel: this project's host is then running, not missing.
    """
    record = channel_file.parent.parent / REFUSAL_FILE
    try:
        reason = json.loads(record.read_text(encoding='utf-8'))
        print(f"{reason['code']}: {reason['message']}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError):
        if owner is not None:
            print("The agents host of another Claude Code session (Claude Code pid "
                  f"{owner.get('parent')}) owns this project.", file=sys.stderr)
        else:
            print('The agents host for this project is not running; see '
                  f"{channel_file.parent.parent / 'host.log'}.", file=sys.stderr)
    raise SystemExit(1)


def live_channel(channel_file: Path) -> dict | None:
    """Return the channel's record while its host is alive; anything else is stale.

    A host holds the lock on its address for its whole life and the kernel
    releases it when the host dies, so unlike a PID this stays right for a host
    killed alone and for a PID reused after a reboot.
    """
    try:
        endpoint = json.loads(channel_file.read_text(encoding='utf-8'))
        return endpoint if host_alive(endpoint['address']) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def context_endpoint(channel_file: Path) -> dict:
    """Return the channel of this Claude process's live host, or exit reporting why there is none."""
    endpoint = live_channel(channel_file)
    if endpoint is None or endpoint.get('parent') != os.getppid():
        report_missing_host(channel_file, endpoint)
    return endpoint


def require_free_channel(channel_file: Path) -> None:
    """Refuse while another live host serves this channel; a stale file does not count."""
    owner = live_channel(channel_file)
    if owner is not None:
        raise AgentsError('host-busy', f'{channel_file}: another agents host is serving this project for '
                          f"Claude Code pid {owner.get('parent')}. Close that Claude Code session.")


def remove_stale_channel(channel_file: Path) -> None:
    """Remove a dead host's channel file and the control directory it names beside it."""
    try:
        address = Path(json.loads(channel_file.read_text(encoding='utf-8'))['address'])
        beside = (address.name.startswith('control-')
                  and address.parent.resolve() == channel_file.parent.resolve())
    except (OSError, ValueError, KeyError, TypeError):
        beside = False
    channel_file.unlink()
    if beside:
        shutil.rmtree(address, ignore_errors=True)


def claim_channel(channel_file: Path, endpoint: dict) -> bool:
    """Publish this host's channel; return whether it replaced a dead host's file.

    The directory lock makes check, removal and creation one step, so two hosts
    starting over one stale file cannot both serve. Only starting hosts take it,
    each for this one step. The loser sees the winner's live channel.
    """
    lock = os.open(channel_file.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require_free_channel(channel_file)
        replaced = os.path.lexists(channel_file)
        if replaced:
            remove_stale_channel(channel_file)
        # Exclusive creation still stops a host that does not take this lock.
        with channel_file.open('x') as stream:
            json.dump(endpoint, stream)
        return replaced
    finally:
        os.close(lock)


def log_replaced_channel(channel_file: Path) -> None:
    """Keep one line in host.log saying this start replaced a dead host's channel."""
    print(time.strftime('%Y-%m-%dT%H:%M:%S%z'),
          f'agents host replaced a stale channel of a dead host: {channel_file}', flush=True)


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


def codex_driver(settings: dict, cwd: Path, root: Path):
    """Build a Codex driver from a ``codex.host --settings`` document; refuse it now if invalid."""
    from agent_swarm.codex.driver import CodexDriver

    driver = CodexDriver(settings)
    driver.prepare('codex', Caller('claude-native', None))
    return driver


def dsh_driver(settings: dict, cwd: Path, root: Path):
    """Build a DSH driver for children in ``cwd``; refuse missing or unsupported DSH now."""
    from agent_swarm.dsh.driver import DshDriver

    driver = DshDriver(cwd, settings)
    driver.prepare('dsh', Caller('claude-native', None))
    return driver


def pi_driver(settings: dict, cwd: Path, root: Path):
    """Build a Pi driver for children in ``cwd``; refuse settings or dependencies no child could run with."""
    from agent_swarm.pi.host import pi_child_driver

    return pi_child_driver(settings, cwd, root)


# Runtime name -> driver factory taking that Runtime's ``runtimes`` entry, the
# host's working directory and its data root.
RUNTIME_DRIVERS = {'codex': codex_driver, 'dsh': dsh_driver, 'pi': pi_driver}


def runtime_drivers(cwd: Path, settings: dict, runtimes: object, root: Path) -> dict:
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
        drivers[name] = RUNTIME_DRIVERS[name](entry, cwd, root)
    return drivers


class IndependentCalls(NativeCalls):
    """Bind the verified native Main and hold its execution notices until one reader claims them."""

    def __init__(self, root: Path, cwd: Path, settings: dict, runtimes: dict | None = None) -> None:
        """Own one independent backend; no project configuration is discovered."""
        self.queue: dict[str, list[dict]] = {}
        self.claimed: dict[str, dict[str, dict]] = {}
        # Each queued notice as the core knows it, for settling it by id.
        self.documents: dict[str, dict] = {}
        self.callers: dict[str, object] = {}
        self.control = AgentControl(root, runtime_drivers(cwd, settings, {} if runtimes is None else runtimes, root),
                                    event_receiver=self.receive, request_notices=True, hold_notices=True)
        super().__init__(self.make_call, cwd)

    def attach(self, session: str) -> None:
        """Bind a Session once and queue what was held for it while it was stopped. Hold the lock."""
        if session in self.callers:
            return
        caller = Caller('claude-native', None, session, 'claude')
        self.callers[session] = bind(self.control, caller)
        for notice in self.control.held_notices(caller):
            self.enqueue(session, notice)

    def enqueue(self, session: str, event: dict) -> None:
        """Queue one notice for the Main's mod, once per id. Hold the lock."""
        identity = notice_id(event['execution'], event['outcome'], event.get('request'))
        self.documents[identity] = event
        queue = self.queue.setdefault(session, [])
        if all(notice['id'] != identity for notice in queue):
            message = event['body'] or (event.get('error') or {}).get('message') or event['outcome']
            queue.append({'id': identity, 'event': {'alias': event['agent'], 'event': event['outcome'],
                                                    'message': message, 'execution': event['execution']}})

    def make_call(self, session: str, cwd: Path):
        """Bind only a Session already verified by NativeCalls.context."""
        with self.lock:
            self.attach(session)
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
            seen = [] if result.failed else self.control.settle_shown(request, result.document)
            with self.lock:
                notices = self.claim(session)
            for notice in notices:
                self.control.settle_notice(self.documents[notice['id']], 'delivered')
            on_discard(lambda: self.restore(session, notices, seen))
            if not notices:
                return result
            return AgentsResult({**result.document, 'main_notices': notices}, failed=result.failed)
        return call

    def receive(self, event: dict) -> bool | str:
        """Queue an end or native request its creating Main must handle for that Main's mod to submit.

        It stays held in the core until the mod acknowledges it or a result carries
        it, so a Session that is stopped now, or stops first, gets it on its next run.
        """
        if event['parent'] is not None:
            return False
        session = (event.get('creator') or {}).get('session')
        with self.lock:
            if session in self.callers:
                self.enqueue(session, event)
        return 'held'

    def claim(self, session: str) -> list[dict]:
        """Take this Session's queued notices once, skipping any settled or withdrawn meanwhile. Hold the lock."""
        taken, self.queue[session] = self.queue.get(session, []), []
        taken = [notice for notice in taken if self.control.notice_open(self.documents[notice['id']])]
        self.claimed.setdefault(session, {}).update((notice['id'], notice) for notice in taken)
        return taken

    def restore(self, session: str, notices: list[dict], seen: list[dict]) -> None:
        """Undo one result's hand-over when its caller cancelled before reading it."""
        documents = [self.documents[notice['id']] for notice in notices] + seen
        with self.lock:
            for document in documents:
                self.control.settle_notice(document, 'held', reopen=True)
                self.enqueue(session, document)

    def notices(self, document: dict) -> dict:
        """Serve the mod's claim, requeue and acknowledge protocol; the caller holds the lock.

        The mod acknowledges after a submission. A crash between the two
        delivers that notice once more on the next run, never loses it.
        """
        session = document.get('session')
        if (not isinstance(session, str) or str(UUID(session)) != session
                or set(document) - {'operation', 'session', 'position', 'ids'}):
            raise AgentsError('invalid-input', 'Expected one native notice operation.')
        if document['operation'] == 'notices':
            self.attach(session)
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
        ids = document.get('ids', [])
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise AgentsError('invalid-input', 'Expected the submitted notice ids.')
        for item in ids:
            if item in self.claimed.get(session, {}):
                self.control.settle_notice(self.documents[item], 'delivered')
        return {'acknowledged': True}


def adoption_material(root: Path, claude: Path) -> dict[str, object]:
    """Return native plugin/MCP configuration without modifying trust or credentials."""
    root = root.resolve()
    config = root / '.agents-control' / 'claude-host.json'
    plugin = root / '.claude' / 'skills' / 'agents-claude-host'
    kept = kept_host_paths(config, root, {'root': str(config.parent),
                                          'channel_file': str(config.parent / 'live' / 'channel.json')})
    return {
        str(config): {'root': kept['root'], 'cwd': str(root),
                      'claude': os.path.abspath(claude),
                      'channel_file': kept['channel_file'], 'settings': {}},
        str(root / '.mcp.json'): {'mcpServers': {'agents': {
            'command': sys.executable,
            'args': ['-m', 'agent_swarm.claude.host', 'serve', '--config', str(config)],
        }}},
        str(root / '.claude/settings.local.json'): {'env': {
            'GRAPHTRAJ_CLAUDE_HOST_PYTHON': sys.executable,
            'GRAPHTRAJ_CLAUDE_HOST_CONFIG': str(config),
        }},
        **claude_host_plugin(plugin, 'agents-claude-host', 'Native Claude context for independent agents MCP.'),
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
        endpoint = context_endpoint(channel_file)
        native_parent(Path(endpoint['executable']), stage='context')
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
        require_free_channel(channel_file)
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
    refused = None
    try:
        with worker_connection(directory, calls.context, authenticate=authenticate) as address:
            try:
                replaced = claim_channel(channel_file, {'parent': parent, 'executable': str(executable),
                                                        'address': address})
            except (AgentsError, OSError) as error:
                refused = error
            else:
                try:
                    mcp_in, mcp_out = isolate_stdio(directory.parent / 'host.log')
                    if replaced:
                        log_replaced_channel(channel_file)
                    with ended_by_claude():
                        serve_concurrent(mcp_in, mcp_out, lambda message: respond(
                            message, tool_documents, call, {'name': 'agents', 'version': __version__}))
                finally:
                    channel_file.unlink()
    finally:
        # A refused start has no children, and its stdout is still the MCP channel.
        if refused is None:
            unconfirmed = stop_owned(calls.control)
            # Its absence from the log means a stop was unconfirmed (that line is
            # in the log) or the process was killed before this point.
            if not unconfirmed:
                print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'agents host recorded its children stopped.', flush=True)
            exit_if_owned_unconfirmed(unconfirmed)
    if refused is not None:
        serve_refusal(refused, directory.parent / 'host.log')


if __name__ == '__main__':
    main()
