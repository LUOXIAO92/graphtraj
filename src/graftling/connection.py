"""Authenticated local file transport, extracted from Runner's existing pipe.

No Task mappings, Runtime routing, control state or identity records live here.
The host supplies the business callback and kernel-PID authentication rule.
"""
from __future__ import annotations

import contextvars
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

from graftling.calls import pause
from graftling.tool import AgentsError, AgentsResult

if os.name != 'nt':
    import fcntl

OPERATION_TIMEOUT_SECONDS = 10.0
# A repeating failure of the channel's polling pass logs at most this often.
SERVE_LOG_SECONDS = 60.0
CONNECTION_ENV = 'GRAFTLING_CONNECTION'


def call_owner(request: dict, *, metadata: dict | None = None) -> AgentsResult:
    """Call the independent host bound to this process, without Task fallback.

    The environment locates the channel; its owner verifies the kernel PID
    and any native Session assertions before invoking the existing callback.
    A missing connection never creates a caller or controller.
    """
    address = os.environ.get(CONNECTION_ENV)
    if not address:
        raise AgentsError('authority-denied', 'The owning Agent connection is unavailable.')
    native = client_native_context(metadata)
    document = {'request': request, 'native': native} if native is not None else request
    result = connection_operation(address, document, authenticate=True, await_accepted=True)
    return AgentsResult(result['document'], failed=result['failed'])


@contextmanager
def worker_connection(
    directory: Path,
    operate: Callable[[dict], dict],
    *,
    authenticate: Callable[[int], None] | None = None,
    close_seconds: float | None = None,
) -> Iterator[str]:
    """Serve local requests without requiring a listening network/socket permission.

    By default closing waits for every accepted request and then for callers to
    take their replies. ``close_seconds`` caps all of that for a host that must
    end: a request still running then keeps its daemon thread until the process
    ends, and its caller is told the operation is unconfirmed.
    """
    if os.name == 'nt':
        raise AgentsError('authority-denied', 'Windows does not support the authenticated local control pipe.')
    stop = threading.Event()
    closing = threading.Event()
    with tempfile.TemporaryDirectory(prefix='control-', dir=directory) as address:
        # Held for the host's lifetime; the kernel releases it if the host dies.
        host_lock = os.open(address, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(host_lock, fcntl.LOCK_EX)

        accepted: dict[str, threading.Thread] = {}

        def refuse_closed(request: dict) -> dict:
            """Reject late requests without invoking the operation during close."""
            raise AgentsError('request-not-accepted', 'The Session control channel is closing.')

        def answer(name: str, descriptor: int) -> None:
            """Answer one request in its own empty context, then release its slot."""
            try:
                _answer_request(descriptor, refuse_closed if closing.is_set() else operate, authenticate)
            finally:
                os.close(descriptor)
                del accepted[name]

        def take_requests() -> None:
            """Answer each request on its own thread so a slow one cannot block others."""
            for entry in Path(address).iterdir():
                if entry.name in accepted:
                    continue
                try:
                    descriptor = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                except OSError:
                    continue
                try:
                    os.stat('request.json', dir_fd=descriptor, follow_symlinks=False)
                except OSError:
                    os.close(descriptor)  # Not yet sent, or already answered.
                    continue
                try:
                    # A fresh Context keeps caller identity ContextVars per request.
                    accepted[entry.name] = worker = threading.Thread(
                        target=contextvars.Context().run, args=(answer, entry.name, descriptor), daemon=True)
                    worker.start()
                except BaseException:
                    # The request is still unclaimed, so a later pass can take it.
                    accepted.pop(entry.name, None)
                    os.close(descriptor)
                    raise

        def serve() -> None:
            """Keep polling until stopped: one failed pass must not refuse every later call."""
            next_log = 0.0
            while not stop.is_set():
                try:
                    take_requests()
                except BaseException as error:  # noqa: BLE001 - this thread's last line of defence
                    if time.monotonic() >= next_log:
                        next_log = time.monotonic() + SERVE_LOG_SECONDS
                        _log_failure(error)
                stop.wait(0.01)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield address
        finally:
            closing.set()
            limit = None if close_seconds is None else time.monotonic() + close_seconds

            def join_accepted() -> None:
                """Let each request taken finish and publish its reply, up to ``limit``."""
                for running in list(accepted.values()):
                    running.join(None if limit is None else max(0.0, limit - time.monotonic()))

            join_accepted()
            # A caller removes its request directory after consuming the reply.
            # Keep acknowledged results available across fast native completion.
            deadline = limit if limit is not None else time.monotonic() + OPERATION_TIMEOUT_SECONDS
            while any(Path(address).iterdir()) and time.monotonic() < deadline:
                time.sleep(0.01)
            stop.set()
            thread.join()
            join_accepted()
            os.close(host_lock)


def host_alive(address: str) -> bool:
    """Observe the serving host's channel lock without taking it over."""
    try:
        descriptor = os.open(address, os.O_RDONLY | os.O_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True  # Unobservable here: never take a live host for a dead one.
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
            _log_failure(error)
        result = {'error': {'code': 'operation-failed', 'message': _failure_text(error)}}
    except BaseException as error:  # noqa: BLE001 - the caller waits on this reply for as long as the host lives
        result = _unexpected(error)
    try:
        # Serialised first, so a result that cannot be written is a refusal, not silence.
        reply = json.dumps(result)
    except BaseException as error:  # noqa: BLE001 - this reply must still be written
        reply = json.dumps(_unexpected(error))
    try:
        descriptor = os.open('response.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(reply)
        os.replace('response.tmp', 'response.json', src_dir_fd=directory, dst_dir_fd=directory)
        try:
            os.unlink('request.json', dir_fd=directory)
        except FileNotFoundError:
            pass
    except FileNotFoundError:
        pass  # Caller EOF does not cancel an accepted native operation.
    except OSError as error:
        # The caller cannot be told; the host keeps why it was left waiting.
        _log_failure(error)


def _log_failure(error: BaseException) -> None:
    """Keep where a failure happened; an unwritable host log never stops the channel."""
    try:
        traceback.print_exception(error, file=sys.stderr)
    except BaseException:  # noqa: BLE001 - diagnostics only
        pass


def _failure_text(error: BaseException) -> str:
    """Return the failure's own text, or its type name when it has none it can give."""
    try:
        return str(error)
    except BaseException:  # noqa: BLE001 - the reply needs some text
        return type(error).__name__


def _unexpected(error: BaseException) -> dict:
    """Keep where a failure happened in the host's log and name it to the caller."""
    _log_failure(error)
    try:
        code = getattr(error, 'code', None)
    except BaseException:  # noqa: BLE001 - the reply falls back to the general code
        code = None
    name = type(error).__name__
    text = _failure_text(error)
    return {'error': {'code': code if isinstance(code, str) and code else 'operation-failed',
                      'message': name if text == name else f'{name}: {text}'}}


def connection_operation(
    address: str,
    document: dict,
    *,
    authenticate: bool = False,
    response_timeout: float = OPERATION_TIMEOUT_SECONDS,
    await_accepted: bool = False,
    stoppable: bool = False,
) -> dict:
    """Exchange one request, bounding its reply wait without changing ownership.

    Ordinary controls retain the default deadline. A caller hosting a finite
    observation may include that observation's duration in its response wait.
    This timeout neither cancels an accepted operation nor grants execution time.
    ``stoppable`` lets the current call stop waiting; the owner still finishes.
    """
    if (type(response_timeout) not in (int, float)
            or not math.isfinite(response_timeout) or response_timeout <= 0):
        raise AgentsError('invalid-input', 'response_timeout must be finite and positive.')
    if os.name == 'nt':
        raise AgentsError('authority-denied', 'Windows does not support the authenticated local control pipe.')

    published = False
    try:
        with tempfile.TemporaryDirectory(dir=address) as directory:
            request = Path(directory) / 'request.tmp'
            with request.open('w') as stream:
                if authenticate:
                    fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                stream.write(json.dumps(document))
                stream.flush()
                os.replace(request, request.with_suffix('.json'))
                published = True
                response_file = Path(directory) / 'response.json'
                accepted_file = request.with_suffix('.json')
                deadline = time.monotonic() + response_timeout
                while not response_file.is_file():
                    if await_accepted and not accepted_file.exists():
                        # The host removes the request when it accepts it. A
                        # long native operation is then awaited until its reply
                        # or until the host closes this channel.
                        if (not Path(directory).is_dir()
                                or time.monotonic() >= deadline and not host_alive(address)):
                            raise TimeoutError('The Session host closed before replying; '
                                               'the accepted operation is unconfirmed.')
                    elif time.monotonic() >= deadline:
                        try:
                            # Removing an unclaimed request wins admission:
                            # the host must unlink it before calling operate.
                            accepted_file.unlink()
                        except FileNotFoundError:
                            raise TimeoutError('Session control timed out; delivery is unconfirmed.')
                        raise AgentsError('request-not-accepted', 'The Session host did not accept the request.')
                    if stoppable:
                        pause(0.01)
                    else:
                        time.sleep(0.01)
                response = json.loads(response_file.read_text())
        if 'error' in response:
            raise AgentsError(response['error']['code'], response['error']['message'])
        return response
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not published and isinstance(error, FileNotFoundError):
            raise AgentsError('request-not-accepted', 'The Session control channel closed before the request.') from error
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
    close_seconds: float | None = None,
) -> Iterator[str]:
    """Serve one bound caller, optionally checking host-owned native Session facts.

    Native facts only constrain the existing binding. They never select an
    Agent or substitute for kernel-PID authentication. The host obtains its
    expected context from the actual native Session, not child environment.
    ``close_seconds`` is :func:`worker_connection`'s.
    """
    from graftling.discovery import handle_request

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
    with worker_connection(directory, operate, authenticate=authenticate, close_seconds=close_seconds) as address:
        yield address


def client_native_context(metadata: dict | None = None) -> dict | None:
    """Capture native client assertions; the owning host must verify them."""
    runtime = os.environ.get('GRAFTLING_NATIVE_RUNTIME')
    if (runtime == 'codex' or runtime not in {'pi', 'dsh'}
            and 'DSH_SESSION_ID' not in os.environ and 'DSH_AGENT_SOURCE' not in os.environ
            and isinstance(metadata, dict) and 'threadId' in metadata):
        session = metadata.get('threadId') if isinstance(metadata, dict) else None
        return {'runtime': 'codex', 'session': session or os.environ.get('CODEX_THREAD_ID'),
                'cwd': str(Path.cwd())}
    if 'DSH_SESSION_ID' not in os.environ and 'DSH_AGENT_SOURCE' not in os.environ:
        return None
    return {'runtime': 'dsh', 'session': os.environ.get('DSH_SESSION_ID'),
            'source': os.environ.get('DSH_AGENT_SOURCE'), 'cwd': str(Path.cwd())}


def verify_native_context(actual: object, expected: object) -> None:
    """Require exact native facts from the already-authenticated host's Session."""
    if isinstance(expected, dict) and expected.get('runtime') == 'codex':
        if (set(expected) != {'runtime', 'session', 'cwd'} or actual != expected
                or not isinstance(expected['session'], str) or not expected['session']
                or not isinstance(expected['cwd'], str) or not Path(expected['cwd']).is_absolute()):
            raise AgentsError('authority-denied', 'Native Codex Session/cwd do not match this bound caller.')
        return
    if (not isinstance(expected, dict) or set(expected) != {'runtime', 'session', 'source', 'cwd'}
            or expected['runtime'] != 'dsh' or expected['source'] not in {'main', 'child'}
            or not isinstance(expected['session'], str) or not expected['session']
            or not isinstance(expected['cwd'], str) or not Path(expected['cwd']).is_absolute()
            or actual != expected):
        raise AgentsError('authority-denied', 'Native Session/source/cwd do not match this bound caller.')
