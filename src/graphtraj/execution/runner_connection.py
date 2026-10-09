"""Private file-based control of an existing Session Worker."""

from __future__ import annotations

import json
import ctypes
import os
import stat
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator

if os.name != 'nt':
    import fcntl

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_process import OPERATION_TIMEOUT_SECONDS
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


_parent_connection: ContextVar[str | dict | None] = ContextVar('parent_connection', default=None)


@contextmanager
def parent_connection(address: str | dict | None) -> Iterator[None]:
    """Bind the owning host's existing receiver to launches in this call only."""
    token = _parent_connection.set(address)
    try:
        yield
    finally:
        _parent_connection.reset(token)


def current_parent_connection() -> str | dict | None:
    """Return trusted host context, never a model-supplied operation parameter."""
    return _parent_connection.get()


def inherited_parent_connection() -> str | dict | None:
    """Decode the launcher's private environment, retaining old callback addresses."""
    address = os.environ.get('GRAPHTRAJ_PARENT_CONNECTION')
    return json.loads(address) if address and address.startswith('{') else address


@contextmanager
def worker_connection(
    directory: Path,
    operate: Callable[[dict], dict],
    *,
    authenticate: Callable[[int], None] | None = None,
) -> Iterator[str]:
    """Serve local requests without requiring a listening network/socket permission."""
    if os.name == 'nt':
        raise RunnerError('authority-denied', 'Windows does not support the authenticated Runner control pipe.')
    stop = threading.Event()
    with tempfile.TemporaryDirectory(prefix='control-', dir=directory) as address:
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
    except (RunnerError, RuntimeAdapterError) as error:
        result = {'error': {'code': error.code, 'message': error.message}}
    except (OSError, ValueError, KeyError, TypeError) as error:
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


def session_operation(mapping: dict, operation: str, **arguments: object) -> dict:
    """Ask the owner to control the exact mapped native execution and await its reply."""
    try:
        return connection_operation(mapping['control_directory'], {
            'operation': operation, 'session': mapping['session'],
            'execution_id': mapping['execution_id'], **arguments,
        })
    except (KeyError, TypeError) as error:
        raise RunnerError('operation-failed', 'The mapped Session control identity is invalid.') from error


def connection_operation(
    address: str | dict, document: dict, *, authenticate: bool = False,
) -> dict:
    """Exchange one request with an existing owner, retaining acknowledgement semantics."""
    if isinstance(address, dict):
        from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

        try:
            return select_runtime_adapter(address['runtime']).send_host_event(address, document)
        except RuntimeAdapterError as error:
            raise RunnerError(error.code, error.message) from error

    if os.name == 'nt':
        raise RunnerError('authority-denied', 'Windows does not support the authenticated Runner control pipe.')

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
                deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
                while not response_file.is_file():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Session control timed out; delivery is unconfirmed.')
                    time.sleep(0.01)
                response = json.loads(response_file.read_text())
        if 'error' in response:
            raise RunnerError(response['error']['code'], response['error']['message'])
        return response
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RunnerError(
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
        raise RunnerError('authority-denied', 'This platform cannot verify CLI request ownership.')

    class FileLock(ctypes.Structure):
        """Native ABI record used only for F_GETLK, never caller supplied data."""
        _fields_ = fields

    query = FileLock()
    query.type = fcntl.F_WRLCK
    owner = FileLock.from_buffer_copy(fcntl.fcntl(descriptor, fcntl.F_GETLK, bytes(query)))
    if owner.type != fcntl.F_WRLCK or owner.pid <= 0:
        raise RunnerError('authority-denied', 'The CLI request has no live kernel-verified owner.')
    return owner.pid
