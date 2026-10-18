"""Authenticated local file transport, extracted from Runner's existing pipe.

No Task mappings, Runtime routing, control state or identity records live here.
The host supplies the business callback and kernel-PID authentication rule.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Callable, Iterator

from agent_swarm.tool import AgentsError, AgentsResult

if os.name != 'nt':
    import fcntl

OPERATION_TIMEOUT_SECONDS = 10.0
CONNECTION_ENV = 'AGENT_SWARM_CONNECTION'


def call_owner(request: dict) -> AgentsResult:
    """Call the independent host bound to this process, without Task fallback.

    The environment locates the channel; its owner verifies the kernel PID
    and any native Session assertions before invoking the existing callback.
    Missing or conflicting connections never create a caller or controller.
    """
    if CONNECTION_ENV in os.environ and 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        raise AgentsError('authority-denied', 'Both independent and GraphTraj connections are present.')
    address = os.environ.get(CONNECTION_ENV)
    if not address:
        raise AgentsError('authority-denied', 'The owning Agent connection is unavailable.')
    native = client_native_context()
    document = {'request': request, 'native': native} if native is not None else request
    result = connection_operation(address, document, authenticate=True, await_accepted=True)
    return AgentsResult(result['document'], failed=result['failed'])


@contextmanager
def worker_connection(
    directory: Path,
    operate: Callable[[dict], dict],
    *,
    authenticate: Callable[[int], None] | None = None,
) -> Iterator[str]:
    """Serve local requests without requiring a listening network/socket permission."""
    if os.name == 'nt':
        raise AgentsError('authority-denied', 'Windows does not support the authenticated local control pipe.')
    stop = threading.Event()
    with tempfile.TemporaryDirectory(prefix='control-', dir=directory) as address:
        # Held for the host's lifetime; the kernel releases it if the host dies.
        host_lock = os.open(address, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(host_lock, fcntl.LOCK_EX)

        def serve() -> None:
            """Publish complete responses while native work continues on its own loop."""
            while not stop.is_set():
                for entry in Path(address).iterdir():
                    try:
                        descriptor = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    except OSError:
                        continue
                    try:
                        _answer_request(descriptor, operate, authenticate)
                    finally:
                        os.close(descriptor)
                stop.wait(0.01)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield address
        finally:
            stop.set()
            thread.join()
            # A caller removes its request directory after consuming the reply.
            # Keep acknowledged results available across fast native completion.
            deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
            while any(Path(address).iterdir()) and time.monotonic() < deadline:
                time.sleep(0.01)
            os.close(host_lock)


def _host_alive(address: str) -> bool:
    """Observe the serving host's channel lock without taking it over."""
    try:
        descriptor = os.open(address, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return True  # Unobservable here; the reply or channel removal still ends the wait.
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def _answer_request(
    directory: int,
    operate: Callable[[dict], dict],
    authenticate: Callable[[int], None] | None,
) -> None:
    """Pin the request directory and never follow caller-controlled file links."""
    try:
        descriptor = os.open('request.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError:
        return
    try:
        with os.fdopen(descriptor) as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError('A control request must be a regular file with one link.')
            if authenticate is not None:
                authenticate(record_lock_owner(stream.fileno()))
            request = json.load(stream)
        os.unlink('request.json', dir_fd=directory)
        result = operate(request)
    except AgentsError as error:
        result = {'error': {'code': error.code, 'message': error.message}}
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, OSError):
            # The reply keeps its format; the host keeps where the call failed.
            traceback.print_exc(file=sys.stderr)
        result = {'error': {'code': 'operation-failed', 'message': str(error)}}
    try:
        descriptor = os.open('response.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream)
        os.replace('response.tmp', 'response.json', src_dir_fd=directory, dst_dir_fd=directory)
        try:
            os.unlink('request.json', dir_fd=directory)
        except FileNotFoundError:
            pass
    except OSError:
        pass  # Caller EOF does not cancel an accepted native operation.


def connection_operation(
    address: str,
    document: dict,
    *,
    authenticate: bool = False,
    response_timeout: float = OPERATION_TIMEOUT_SECONDS,
    await_accepted: bool = False,
) -> dict:
    """Exchange one request, bounding its reply wait without changing ownership.

    Ordinary controls retain the default deadline. A caller hosting a finite
    observation may include that observation's duration in its response wait.
    This timeout neither cancels an accepted operation nor grants execution time.
    """
    if (type(response_timeout) not in (int, float)
            or not math.isfinite(response_timeout) or response_timeout <= 0):
        raise AgentsError('invalid-input', 'response_timeout must be finite and positive.')
    if os.name == 'nt':
        raise AgentsError('authority-denied', 'Windows does not support the authenticated local control pipe.')

    try:
        with tempfile.TemporaryDirectory(dir=address) as directory:
            request = Path(directory) / 'request.tmp'
            with request.open('w') as stream:
                if authenticate:
                    fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                stream.write(json.dumps(document))
                stream.flush()
                os.replace(request, request.with_suffix('.json'))
                response_file = Path(directory) / 'response.json'
                accepted_file = request.with_suffix('.json')
                deadline = time.monotonic() + response_timeout
                while not response_file.is_file():
                    if await_accepted and not accepted_file.exists():
                        # The host removes the request when it accepts it. A
                        # long native operation is then awaited until its reply
                        # or until the host closes this channel.
                        if (not Path(directory).is_dir()
                                or time.monotonic() >= deadline and not _host_alive(address)):
                            raise TimeoutError('The Session host closed before replying; '
                                               'the accepted operation is unconfirmed.')
                    elif time.monotonic() >= deadline:
                        raise TimeoutError('Session control timed out; delivery is unconfirmed.')
                    time.sleep(0.01)
                response = json.loads(response_file.read_text())
        if 'error' in response:
            raise AgentsError(response['error']['code'], response['error']['message'])
        return response
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AgentsError(
            'operation-failed', 'The mapped Session owner did not acknowledge the operation: ' + str(error),
        ) from error


def record_lock_owner(descriptor: int) -> int:
    """Read the POSIX write-lock owner from the kernel, failing closed elsewhere.

    Darwin and Linux use different native ``struct flock`` field orderings.
    The client holds a whole-file lock until it consumes the host response.
    """
    if sys.platform == 'darwin':
        fields = [('start', ctypes.c_int64), ('length', ctypes.c_int64),
                  ('pid', ctypes.c_int), ('type', ctypes.c_short), ('whence', ctypes.c_short)]
    elif sys.platform.startswith('linux'):
        fields = [('type', ctypes.c_short), ('whence', ctypes.c_short),
                  ('start', ctypes.c_int64), ('length', ctypes.c_int64), ('pid', ctypes.c_int)]
    else:
        raise AgentsError('authority-denied', 'This platform cannot verify CLI request ownership.')

    class FileLock(ctypes.Structure):
        """Native ABI record used only for F_GETLK, never caller supplied data."""
        _fields_ = fields

    query = FileLock()
    query.type = fcntl.F_WRLCK
    owner = FileLock.from_buffer_copy(fcntl.fcntl(descriptor, fcntl.F_GETLK, bytes(query)))
    if owner.type != fcntl.F_WRLCK or owner.pid <= 0:
        raise AgentsError('authority-denied', 'The CLI request has no live kernel-verified owner.')
    return owner.pid


@contextmanager
def agents_connection(
    directory: Path,
    call: Callable[[dict], AgentsResult],
    authenticate: Callable[[int], None],
    *,
    native_context: Callable[[], dict | None] | None = None,
) -> Iterator[str]:
    """Serve one bound caller, optionally checking host-owned native Session facts.

    Native facts only constrain the existing binding. They never select an
    Agent or substitute for kernel-PID authentication. The host obtains its
    expected context from the actual native Session, not child environment.
    """
    from agent_swarm.discovery import handle_request

    def operate(request: dict) -> dict:
        """Reuse shared discovery and the host's existing business callback."""
        if native_context is not None:
            if not isinstance(request, dict) or set(request) != {'request', 'native'}:
                raise AgentsError('authority-denied', 'The native Session context is required.')
            verify_native_context(request['native'], native_context())
            request = request['request']
        elif isinstance(request, dict) and 'native' in request:
            raise AgentsError('authority-denied', 'This channel has no matching native Session binding.')
        result = handle_request(request, call)
        return {'document': result.document, 'failed': result.failed}

    directory.mkdir(parents=True, exist_ok=True)
    with worker_connection(directory, operate, authenticate=authenticate) as address:
        yield address


def client_native_context() -> dict | None:
    """Capture the DSH client's assertions; the owning host must verify them."""
    if 'DSH_SESSION_ID' not in os.environ and 'DSH_AGENT_SOURCE' not in os.environ:
        return None
    return {'runtime': 'dsh', 'session': os.environ.get('DSH_SESSION_ID'),
            'source': os.environ.get('DSH_AGENT_SOURCE'), 'cwd': str(Path.cwd())}


def verify_native_context(actual: object, expected: object) -> None:
    """Require exact native facts from the already-authenticated host's Session."""
    if (not isinstance(expected, dict) or set(expected) != {'runtime', 'session', 'source', 'cwd'}
            or expected['runtime'] != 'dsh' or expected['source'] not in {'main', 'child'}
            or not isinstance(expected['session'], str) or not expected['session']
            or not isinstance(expected['cwd'], str) or not Path(expected['cwd']).is_absolute()
            or actual != expected):
        raise AgentsError('authority-denied', 'Native Session/source/cwd do not match this bound caller.')
