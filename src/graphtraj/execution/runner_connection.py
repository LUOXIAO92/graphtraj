"""Private file-based control of an existing Session Worker."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator

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
def worker_connection(directory: Path, operate: Callable[[dict], dict]) -> Iterator[str]:
    """Serve local requests without requiring a listening network/socket permission."""
    stop = threading.Event()
    with tempfile.TemporaryDirectory(prefix='control-', dir=directory) as address:
        def serve() -> None:
            """Publish complete responses while native work continues on its own loop."""
            while not stop.is_set():
                for request_file in Path(address).glob('*/request.json'):
                    try:
                        request = json.loads(request_file.read_text())
                        request_file.unlink()
                        result = operate(request)
                    except RuntimeAdapterError as error:
                        result = {'error': {'code': error.code, 'message': error.message}}
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        result = {'error': {'code': 'operation-failed', 'message': str(error)}}
                    try:
                        pending = request_file.with_name('response.tmp')
                        pending.write_text(json.dumps(result))
                        os.replace(pending, request_file.with_name('response.json'))
                    except OSError:
                        pass  # Caller EOF does not cancel an accepted native operation.
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


def session_operation(mapping: dict, operation: str, **arguments: object) -> dict:
    """Ask the owner to control the exact mapped native execution and await its reply."""
    try:
        return connection_operation(mapping['control_directory'], {
            'operation': operation, 'session': mapping['session'],
            'execution_id': mapping['execution_id'], **arguments,
        })
    except (KeyError, TypeError) as error:
        raise RunnerError('operation-failed', 'The mapped Session control identity is invalid.') from error


def connection_operation(address: str | dict, document: dict) -> dict:
    """Exchange one request with an existing owner, retaining acknowledgement semantics."""
    if isinstance(address, dict):
        from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

        try:
            return select_runtime_adapter(address['runtime']).send_host_event(address, document)
        except RuntimeAdapterError as error:
            raise RunnerError(error.code, error.message) from error

    try:
        with tempfile.TemporaryDirectory(dir=address) as directory:
            request = Path(directory) / 'request.tmp'
            request.write_text(json.dumps(document))
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
