"""Independent control owner launched by Pi's trusted native extension.

The extension supplies its native Session association on the owned stdio
launch boundary. Model requests supply neither identity nor launch settings.
The host configuration is Task-free: ``root`` plus optional per-Runtime
settings (``pi``, ``claude``, ``codex``, ``dsh``); see PUBLIC_API.md 1.6.
The host builds the Pi child request from its verified native parent.

Private pipe protocol with the extension: stdin carries one Session event
line, then one ``{"ready": true}`` line when the Session can take held notices
and ``{"ack": <notice id>, "shown": bool}`` lines, then EOF at native shutdown;
stdout carries one ``{"connection"}`` line, then ``{"notice"}`` lines.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, TextIO

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import agents_connection
from agent_swarm.notices import notice_id
from agent_swarm.process import process_ancestors, process_arguments, process_executable
from .driver import PiDriver

# Top-level host configuration keys; each Runtime key holds that driver's settings.
CONFIG_KEYS = frozenset({'root', 'pi', 'claude', 'codex', 'dsh'})
# Generic Pi request fields a configuration may set (worktree_path is always cwd).
PI_TEXT = frozenset({'executable', 'provider', 'model', 'agent_dir', 'instructions', 'sandbox_python',
                     'sandbox_path', 'provider_domain', 'base_url', 'provider_api', 'api_key_env',
                     'reasoning_effort', 'native_directory', 'git_common_directory'})
PI_PATHS = frozenset({'read_paths', 'write_paths', 'deny_read', 'deny_write'})
PI_OTHER = frozenset({'worktree_access', 'allowed_domains', 'allow_mach_lookup', 'allow_mach_register',
                      'allow_local_binding', 'allow_unix_sockets'})
# How long a written notice waits for the extension's acknowledgement.
ACK_SECONDS = 10.0
from .session import current_connection, session_record, verify_main


def verify_native_parent(executable: Path) -> None:
    """Require the actual MCP parent to be the selected native Pi process.

    Native environment facts only constrain this OS-observed launch boundary;
    they do not establish it. Reuse the existing kernel process readers and
    reject shell-launched or unrelated clients even with copied Session env.
    """
    parent = os.getppid()
    actual = process_executable(parent)
    arguments = process_arguments(parent)
    expected = executable.resolve()
    selected_node = os.environ.get('AGENT_SWARM_PI_NODE')
    native_entry = os.environ.get('AGENT_SWARM_PI_ENTRY')
    direct = actual is not None and actual.resolve() == expected
    # Official setupCli sets process.title='pi', replacing kernel argv. Its
    # trusted extension still has process.argv[1]; constrain that observation
    # with both the actual kernel Node executable and the native title.
    titled_entry = (arguments and arguments[0] == 'pi' and native_entry
                    and Path(native_entry).resolve() == expected)
    node_script = (actual is not None and selected_node
                   and actual.resolve() == Path(selected_node).resolve()
                   and (titled_entry or len(arguments) > 1 and Path(arguments[1]).resolve() == expected))
    if parent <= 1 or parent != os.getppid() or not (direct or node_script):
        raise ValueError('The MCP pipe is not owned by the selected native Pi process.')


def bind_native_main(
    control: AgentControl,
    connection: dict,
    cwd: Path,
    native_event: dict | None = None,
) -> Callable:
    """Bind the extension's existing native root without writing an identity record.

    This is a trusted host API, not a model-callable adoption operation. Like
    nativeEntry, the caller obtains the association from Pi session_start.
    Never pass model arguments as ``connection`` or ``native_event``. A new
    Session is not yet on disk: the trusted extension supplies its SDK header
    on its private lifecycle pipe, as nativeEntry already does. Rebinding
    without that callback reads only the selected native file.
    """
    if connection.get('runtime') != 'pi':
        raise ValueError('The owning native Runtime must be Pi.')
    selected = {key: connection[key] for key in ('runtime', 'session', 'session_file')}
    if native_event is not None:
        selected.update(native_header=native_event['header'], native_entries=native_event['entries'])
    session = verify_main(selected)
    header = (native_event['header'] if native_event is not None else
              session_record(Path(selected['session_file']), session)[0])
    if Path(header['cwd']).resolve() != cwd.resolve():
        raise ValueError('The Pi native Session cwd does not match this host.')
    return bind(control, Caller('pi-native', None, session=session, runtime='pi'))


def read_configuration(document: object) -> tuple[Path, dict]:
    """Validate the Task-free host configuration; return the root and its settings.

    The pre-382 ``{"root", "adapter_request"}`` form is refused: the host
    now builds the Pi request itself, and Pi overrides go under ``pi``.
    """
    if not isinstance(document, dict):
        raise ValueError('The Pi host configuration must be a JSON object.')
    if 'adapter_request' in document:
        raise ValueError('adapter_request is no longer accepted: the Pi host builds the child request '
                         'itself. Put Pi overrides under "pi" (PUBLIC_API.md 1.6).')
    unknown = set(document) - CONFIG_KEYS
    if unknown:
        raise ValueError(f'Unknown Pi host configuration keys: {sorted(unknown)}; allowed: {sorted(CONFIG_KEYS)}.')
    root = document.get('root')
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError('The Pi host configuration needs an absolute data root "root".')
    settings = {key: document.get(key, {}) for key in ('pi', 'claude', 'dsh')}
    settings['codex'] = document.get('codex')
    for key, value in settings.items():
        if value is not None and not isinstance(value, dict):
            raise ValueError(f'"{key}" must be an object of {key} settings.')
    pi = settings['pi']
    unknown = set(pi) - PI_TEXT - PI_PATHS - PI_OTHER
    if unknown:
        raise ValueError(f'Unknown or fixed Pi settings: {sorted(unknown)} (worktree_path is always the cwd).')
    for field in PI_TEXT & set(pi):
        if not isinstance(pi[field], str) or not pi[field]:
            raise ValueError(f'Pi setting {field} must be a non-empty string.')
    for field in PI_PATHS & set(pi):
        if (not isinstance(pi[field], list)
                or not all(isinstance(path, str) and Path(path).is_absolute() for path in pi[field])):
            raise ValueError(f'Pi setting {field} must list absolute paths.')
    if pi.get('worktree_access', 'read') not in {'read', 'write'}:
        raise ValueError("Pi setting worktree_access must be 'read' or 'write'.")
    return Path(root), settings


def pi_request(overrides: Mapping[str, Any], cwd: Path, environment: Mapping[str, str]) -> dict:
    """Build the Pi child request from the verified native parent, then apply overrides.

    Parent model and provider are defaults only; ``create`` may choose
    another model. Worktree access is read unless the configuration says
    write, which also resolves the Git common directory. No path, domain or
    write grant is added beyond these documented defaults.
    """
    entry = environment.get('AGENT_SWARM_PI_ENTRY')
    if not entry:
        raise ValueError('The verified Pi entry is unavailable; start the host through the agents Pi extension.')
    request = {
        'executable': entry,
        'provider': environment.get('AGENT_SWARM_PI_PROVIDER', ''),
        'model': environment.get('AGENT_SWARM_PI_MODEL', ''),
        'worktree_path': str(cwd.resolve()),
        'agent_dir': environment.get('PI_CODING_AGENT_DIR') or str(Path.home() / '.pi/agent'),
        'instructions': '',
        'sandbox_python': sys.executable,
        'sandbox_path': environment.get('PATH', ''),
        'worktree_access': 'read',
    }
    request.update(overrides)
    if not request['provider'] or not request['model']:
        raise ValueError('The Pi parent has no selected model/provider; select one in Pi '
                         'or set pi.provider and pi.model in the host configuration.')
    if request['worktree_access'] == 'write' and 'git_common_directory' not in request:
        try:
            common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                    cwd=cwd, capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('Pi worktree_access write needs a Git worktree, or set '
                             'pi.git_common_directory.') from error
        request['git_common_directory'] = common
    return request


def runtime_drivers(cwd: Path, request: Mapping[str, Any], settings: Mapping[str, Any]) -> dict:
    """One driver per Runtime through its public constructor.

    Kept to one function so the Claude and Codex hosts (381) can share it.
    Claude defaults to read access and DSH to its read-only sandbox, like Pi;
    Codex needs its captured ``Run.settings`` (as ``agent_swarm.codex.host
    --settings`` takes), else its create fails with ``invalid-config``.
    Imported here so this module stays importable without their dependencies.
    """
    from agent_swarm.claude.driver import ClaudeDriver
    from agent_swarm.codex.driver import CodexDriver
    from agent_swarm.dsh.driver import DshDriver

    return {
        'pi': PiDriver(dict(request)),
        'claude': ClaudeDriver(cwd, {'worktree_access': 'read', **settings.get('claude', {})}),
        'codex': CodexDriver(settings.get('codex')),
        'dsh': DshDriver(cwd, {'sandbox': 'read-only', **settings.get('dsh', {})}),
    }


class Notices:
    """Push this Main's child messages, requests and system exceptions to the Pi extension.

    Each notice is one stdout line; the extension injects it into the Pi
    Session and acknowledges it on stdin. A notice acknowledged as shown is
    ``delivered``. One written but not acknowledged in time is
    ``unconfirmed``: it may have been shown, so it is never repeated. One that
    cannot be written, is refused by the extension, or is still waiting when
    the Session shuts down, is ``held``: it stays readable through ``status``
    and ``wait`` and the next host process for this Session delivers it.
    """

    def __init__(self, stream: TextIO, session: str, timeout: float = ACK_SECONDS) -> None:
        """Bind the extension's pipe and the verified Main Session."""
        self.stream = stream
        self.session = session
        self.timeout = timeout
        self.lock = threading.Lock()
        self.waiting: dict[str, list] = {}
        self.closing = False
        self.started = time.time()

    def write(self, document: dict) -> None:
        """Write one protocol line; serialized with notice writes."""
        with self.lock:
            self.stream.write(json.dumps(document) + '\n')
            self.stream.flush()

    def receive(self, notice: dict) -> bool | str:
        """Event receiver for AgentControl: called once per notice for this Main."""
        if notice['parent'] is not None or (notice.get('creator') or {}).get('session') != self.session:
            return False
        identity = notice_id(notice['execution'], notice['outcome'], notice.get('request'))
        message = notice['body'] or (notice.get('error') or {}).get('message') or notice['outcome']
        acknowledged = threading.Event()
        slot = [acknowledged, False]
        with self.lock:
            if self.closing:
                return 'held'
            self.waiting[identity] = slot
            try:
                self.stream.write(json.dumps({'notice': {
                    'id': identity, 'alias': notice['agent'], 'agent': notice['agent'],
                    'event': notice['outcome'], 'message': message,
                    'execution': notice['execution']}}) + '\n')
                self.stream.flush()
            except (OSError, ValueError):
                self.waiting.pop(identity, None)
                return 'held'
        if not acknowledged.wait(self.timeout):
            with self.lock:
                self.waiting.pop(identity, None)
            return 'unconfirmed'
        return True if slot[1] else 'held'

    def flush(self, control: AgentControl, caller: Caller) -> None:
        """Deliver the notices held for this Session, each once, from a new host process.

        Runs on its own thread: a delivery waits for an acknowledgement that
        the stdin loop reads. One a ``status`` or ``wait`` has shown meanwhile
        is no longer open and is not pushed. A notice refused here stays held
        for the next host process.
        """
        for notice in control.held_notices(caller):
            if not self.closing and control.notice_open(notice):
                result = self.receive(notice)
                control.settle_notice(notice, 'delivered' if result is True else
                                      'unconfirmed' if result == 'unconfirmed' else 'held')

    def acknowledge(self, identity: object, shown: bool) -> None:
        """Settle one written notice: injected into the Pi Session, or refused there."""
        with self.lock:
            slot = self.waiting.pop(identity, None)
        if slot is not None:
            slot[1] = shown
            slot[0].set()

    def hide_pushed(self, document: Mapping[str, Any]) -> None:
        """Hide a body this host is about to push, so the Main receives it once.

        AgentControl marks such an end ``queueing`` before calling the
        receiver, so a concurrent ``wait`` or ``status`` would otherwise show
        the body and the notice would repeat it. A held end being flushed is
        shown as ``queueing`` the same way, so it is not settled as read. Ends
        of earlier host processes, and any end once shutdown began, keep their body.
        """
        pending = [document]
        while pending:
            agent = pending.pop()
            last = agent.get('last_result') or {}
            flushing = notice_id(last.get('id'), last.get('outcome')) in self.waiting
            if (not self.closing and agent.get('parent') is None and (flushing or (
                    last.get('notification') == 'queueing' and (last.get('ended_at') or 0) >= self.started))):
                last.update(notification='queueing', last_message=None)
            pending.extend(agent.get('children', []))

    def close(self) -> None:
        """Stop pushing at native shutdown; unacknowledged notices stay held."""
        with self.lock:
            self.closing = True
            pending, self.waiting = list(self.waiting.values()), {}
        for slot in pending:
            slot[0].set()


def start(config: Path) -> tuple[Path, Notices, Callable, Callable, AgentControl, Caller]:
    """Verify the native parent and configuration; bind the Pi Main to its control.

    Returns the model-facing entry and the plain bound ``call``: only what the
    model reads settles a held notice, not this host's own shutdown.
    """
    if any(name in os.environ for name in (
        'AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE',
    )):
        raise ValueError('An already-bound child must use its existing connection, not adopt Main.')
    root, settings = read_configuration(json.loads(config.read_text(encoding='utf-8')))
    cwd = Path.cwd()
    request = pi_request(settings['pi'], cwd, os.environ)
    verify_native_parent(Path(os.environ['AGENT_SWARM_PI_ENTRY']))
    connection = current_connection()
    if connection is None:
        raise ValueError('Pi native Session association is unavailable.')
    event = json.loads(sys.stdin.readline())
    # bind_native_main verifies this Session before any child can exist.
    notices = Notices(sys.stdout, connection['session'])
    control = AgentControl(root, runtime_drivers(cwd, request, settings), event_receiver=notices.receive,
                           request_notices=True, hold_notices=True)
    call = bind_native_main(control, connection, cwd, event)
    # Fail at start, not mid-turn, when config.yml declares a connection
    # this machine cannot run; create re-checks the selected one.
    control.require_connections()

    def operate(request: dict) -> AgentsResult:
        """Serve one action; a body this host is pushing is hidden, a held one shown is settled."""
        result = call(request)
        found = result.document.get('result')
        if isinstance(found, dict):
            for agent in found.get('agents', [found]):
                notices.hide_pushed(agent)
            if not result.failed:
                control.settle_shown(request, result.document)
        return result

    return root, notices, operate, call, control, Caller('pi-native', None, session=connection['session'], runtime='pi')


def stop_children(call: Callable) -> None:
    """Interrupt every active child, descendants first, through the public stop path.

    No nested execution outlives the single control owner when its MCP pipe closes.
    """
    status = call({'action': 'status'})
    if status.failed:
        return
    pending = list(status.document['result']['agents'])
    owned = []
    while pending:
        agent = pending.pop()
        owned.append(agent)
        pending.extend(agent['children'])
    for agent in reversed(owned):
        if agent['state'] == 'active':
            call({'action': 'interrupt', 'agent': agent['agent']})
            result = call({'action': 'wait', 'agent': agent['agent'], 'timeout_seconds': 10})
            if result.failed or result.document['result']['state'] == 'active':
                raise RuntimeError('Native child stop was not confirmed before host shutdown.')


def main() -> None:
    """Keep one control owner alive until the trusted extension closes its pipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    options = parser.parse_args()
    try:
        root, notices, operate, call, control, caller = start(options.config)
    except (AgentsError, OSError, ValueError, KeyError) as error:
        # The extension shows this line as the Pi Session's extension error.
        print(json.dumps({'error': {'code': getattr(error, 'code', 'invalid-config'), 'message': str(error)}}),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    parent = os.getppid()
    flusher = threading.Thread(target=notices.flush, args=(control, caller), daemon=True)

    def authenticate(caller_pid: int) -> None:
        """Accept only direct clients of the verified native parent, not child Runtimes."""
        chain = process_ancestors(caller_pid)
        if os.getppid() != parent or len(chain) < 2 or chain[1] != parent:
            raise AgentsError('authority-denied', 'The client is not owned by this native Pi host.')

    try:
        with agents_connection(root / 'live' / 'pi-host', operate, authenticate) as address:
            notices.write({'connection': address})
            # Only readiness, acknowledgements and lifecycle EOF travel over this
            # private extension pipe. Model requests use the shared authenticated bridge.
            for line in sys.stdin:
                message = json.loads(line)
                if message == {'ready': True}:
                    if flusher.ident is None:
                        flusher.start()
                    continue
                if (not isinstance(message, dict) or set(message) != {'ack', 'shown'}
                        or not isinstance(message['shown'], bool)):
                    raise ValueError('The native host pipe only accepts readiness, notice acknowledgements and close.')
                notices.acknowledge(message['ack'], message['shown'])
    finally:
        # Closing the extension pipe ends this owner's execution lifetime.
        # Stop pushing first: ends caused by this shutdown are held, not shown.
        control.close_notices()
        notices.close()
        if flusher.ident is not None:
            flusher.join(10)
        # Preserve identities and Sessions; use the same public stop path.
        stop_children(call)


if __name__ == '__main__':
    main()
