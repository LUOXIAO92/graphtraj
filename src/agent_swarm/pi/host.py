"""Independent control owner launched by Pi's trusted native extension.

The extension supplies its native Session association on the owned stdio
launch boundary. Model requests supply neither identity nor launch settings.
The host configuration is Task-free: ``root`` plus optional per-Runtime
settings (``pi``, ``claude``, ``codex``, ``dsh``); see PUBLIC_API.md 1.6.
The host builds the Pi child request from its verified native parent.

Private pipe protocol with the extension: stdin carries one Session event
line, then ``{"ack": <notice id>, "shown": bool}`` lines, then EOF at native shutdown;
stdout carries one ``{"connection"}`` line, then ``{"notice"}`` lines.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, TextIO

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import agents_connection
from agent_swarm.notices import notice_id
from agent_swarm.process import process_ancestors, process_arguments, process_executable
from agent_swarm.runtime import RuntimeAdapterError
from .driver import PiDriver
from .execution import _validate, child_path

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
    check_pi_settings(settings['pi'])
    return Path(root), settings


def check_pi_settings(pi: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` naming an unknown or fixed Pi setting or a wrong field type."""
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


def pi_child_driver(settings: Mapping[str, Any], cwd: Path, root: Path) -> PiDriver:
    """Build the Pi driver of a host with no Pi parent, or refuse it at that host's start.

    The Claude Code and Codex hosts pass their ``runtimes.pi`` entry, working
    directory and data root. With no parent to inherit from, ``provider`` and
    ``model`` are required and ``executable`` defaults to ``pi`` on this PATH;
    the rest follows :func:`pi_request`. Only what would fail every child is
    checked. A login or Pi's catalog is not: a provider can authenticate through
    Pi's own models.json and a catalog query can take 30 seconds, so those
    failures keep surfacing at ``create``.

    Raises
    ------
    AgentsError
        ``invalid-config`` for a wrong setting and ``runtime-unavailable`` for
        a missing dependency, naming the field or the setting that fixes it.
    """
    try:
        check_pi_settings(settings)
    except ValueError as error:
        raise AgentsError('invalid-config', str(error)) from None
    for field in ('provider', 'model'):
        if field not in settings:
            raise AgentsError('invalid-config', f'runtimes.pi.{field} is required: '
                                                'this host has no Pi parent to inherit it from.')

    # The owner denies reading the data root and refuses a denied path inside
    # a readable one (pi/execution.py), so this layout would fail every create.
    worktree, data = cwd.resolve(), root.resolve()
    if data.is_relative_to(worktree):
        raise AgentsError('invalid-config', f'The agents data root {data} lies inside the Pi worktree {worktree}, '
                                            'which a Pi child must be able to read. Move root outside it.')

    executable = shutil.which(settings.get('executable', 'pi'))
    if executable is None:
        raise AgentsError('runtime-unavailable', f"The Pi executable {settings.get('executable', 'pi')} was not "
                                                 'found. Install Pi or set runtimes.pi.executable.')
    executable = os.path.abspath(executable)
    try:
        request = pi_request({**settings, 'executable': executable}, cwd,
                             {**os.environ, 'AGENT_SWARM_PI_ENTRY': executable})
        _validate(request)
    except ValueError as error:
        raise AgentsError('invalid-config', str(error)) from None
    except RuntimeAdapterError as error:
        raise AgentsError('invalid-config', error.message) from None

    # Check what launch.py and srt will actually find: the child's PATH, and
    # this directory as the import path launch.py gets as its script directory.
    path = child_path(request['sandbox_path'])
    python = request['sandbox_python']
    try:
        subprocess.run([python, '-c', 'import agent_sandbox'], cwd=Path(__file__).parent,
                       env={**os.environ, 'PATH': path}, capture_output=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise AgentsError('runtime-unavailable',
                          f'Pi children need agent_sandbox, but {python} cannot import it. '
                          'Install agent-sandbox there or set runtimes.pi.sandbox_python.') from None
    for tool in ('srt', 'node'):
        if shutil.which(tool, path=path) is None:
            raise AgentsError('runtime-unavailable', f"Pi children need {tool}, but it is not on the PATH they get "
                                                     "(the host Python's directory, then sandbox_path). "
                                                     'Install it or set runtimes.pi.sandbox_path.')
    variable = settings.get('api_key_env')
    if variable is not None and not os.environ.get(variable):
        raise AgentsError('runtime-unavailable', f'The environment variable {variable} is unset or empty. '
                                                 'Set it or change runtimes.pi.api_key_env.')
    return PiDriver(request)


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
    """Push this Main's child messages and system exceptions to the Pi extension.

    Each notice is one stdout line; the extension injects it into the Pi
    Session and acknowledges it on stdin. A notice acknowledged as shown is
    ``delivered``. One written but not acknowledged in time is
    ``unconfirmed``. One that cannot be written, is refused by the
    extension, or is still waiting when the Session shuts down, is
    ``unavailable`` and stays readable
    through ``status`` and ``wait``.
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
        """Event receiver for AgentControl: called once per end that needs this Main."""
        if notice['parent'] is not None or (notice.get('creator') or {}).get('session') != self.session:
            return False
        identity = notice_id(notice['execution'], notice['outcome'])
        message = notice['body'] or (notice.get('error') or {}).get('message') or notice['outcome']
        acknowledged = threading.Event()
        slot = [acknowledged, False]
        with self.lock:
            if self.closing:
                return False
            self.waiting[identity] = slot
            try:
                self.stream.write(json.dumps({'notice': {
                    'id': identity, 'alias': notice['agent'], 'agent': notice['agent'],
                    'event': notice['outcome'], 'message': message,
                    'execution': notice['execution']}}) + '\n')
                self.stream.flush()
            except (OSError, ValueError):
                self.waiting.pop(identity, None)
                return False
        if not acknowledged.wait(self.timeout):
            with self.lock:
                self.waiting.pop(identity, None)
            return 'unconfirmed'
        return slot[1]

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
        the body and the notice would repeat it. Ends of earlier host
        processes, and any end once shutdown began, keep their body.
        """
        pending = [document]
        while pending:
            agent = pending.pop()
            last = agent.get('last_result') or {}
            if (not self.closing and agent.get('parent') is None and last.get('notification') == 'queueing'
                    and (last.get('ended_at') or 0) >= self.started):
                last['last_message'] = None
            pending.extend(agent.get('children', []))

    def close(self) -> None:
        """Stop pushing at native shutdown; unacknowledged notices become unavailable."""
        with self.lock:
            self.closing = True
            pending, self.waiting = list(self.waiting.values()), {}
        for slot in pending:
            slot[0].set()


def start(config: Path) -> tuple[Path, Notices, Callable]:
    """Verify the native parent and configuration; bind the Pi Main to its control."""
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
    control = AgentControl(root, runtime_drivers(cwd, request, settings), event_receiver=notices.receive)
    call = bind_native_main(control, connection, cwd, event)
    # Fail at start, not mid-turn, when config.yml declares a connection
    # this machine cannot run; create re-checks the selected one.
    control.require_connections()

    def operate(request: dict) -> AgentsResult:
        """Serve one action; a body this host is pushing is hidden from its result."""
        result = call(request)
        found = result.document.get('result')
        if isinstance(found, dict):
            for agent in found.get('agents', [found]):
                notices.hide_pushed(agent)
        return result

    return root, notices, operate


def main() -> None:
    """Keep one control owner alive until the trusted extension closes its pipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    options = parser.parse_args()
    try:
        root, notices, call = start(options.config)
    except (AgentsError, OSError, ValueError, KeyError) as error:
        # The extension shows this line as the Pi Session's extension error.
        print(json.dumps({'error': {'code': getattr(error, 'code', 'invalid-config'), 'message': str(error)}}),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    parent = os.getppid()

    def authenticate(caller_pid: int) -> None:
        """Accept only direct clients of the verified native parent, not child Runtimes."""
        chain = process_ancestors(caller_pid)
        if os.getppid() != parent or len(chain) < 2 or chain[1] != parent:
            raise AgentsError('authority-denied', 'The client is not owned by this native Pi host.')

    try:
        with agents_connection(root / 'live' / 'pi-host', call, authenticate) as address:
            notices.write({'connection': address})
            # Only acknowledgements and lifecycle EOF travel over this private
            # extension pipe. Model requests use the shared authenticated bridge.
            for line in sys.stdin:
                message = json.loads(line)
                if (not isinstance(message, dict) or set(message) != {'ack', 'shown'}
                        or not isinstance(message['shown'], bool)):
                    raise ValueError('The native host pipe only accepts notice acknowledgements and close.')
                notices.acknowledge(message['ack'], message['shown'])
    finally:
        # Closing the extension pipe ends this owner's execution lifetime.
        # Stop pushing first: ends caused by this shutdown are recorded, not shown.
        notices.close()
        # Preserve identities and Sessions; use the same public stop path.
        status = call({'action': 'status'})
        if not status.failed:
            pending = list(status.document['result']['agents'])
            owned = []
            while pending:
                agent = pending.pop()
                owned.append(agent)
                pending.extend(agent['children'])
            # Stop descendants before their parents so no nested execution
            # outlives the single control owner when its MCP pipe closes.
            for agent in reversed(owned):
                if agent['state'] == 'active':
                    call({'action': 'interrupt', 'agent': agent['agent']})
                    result = call({'action': 'wait', 'agent': agent['agent'], 'timeout_seconds': 10})
                    if result.failed or result.document['result']['state'] == 'active':
                        raise RuntimeError('Native child stop was not confirmed before host shutdown.')


if __name__ == '__main__':
    main()
