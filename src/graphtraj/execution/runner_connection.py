"""Private file-based control of an existing Session Worker."""

from __future__ import annotations

import json
import math
import os
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
def worker_connection(
    directory: Path,
    operate: Callable[[dict], dict],
    *,
    authenticate: Callable[[int], None] | None = None,
) -> Iterator[str]:
    """Keep Runner errors and callbacks over the shared file transport."""
    from agent_swarm import AgentsError, worker_connection as connection

    def invoke(callback: Callable, value: object) -> object:
        """Translate existing host failures at the transport boundary."""
        try:
            return callback(value)
        except (RunnerError, RuntimeAdapterError) as error:
            raise AgentsError(error.code, error.message) from error

    try:
        with connection(directory, lambda request: invoke(operate, request),
                        authenticate=(lambda pid: invoke(authenticate, pid)) if authenticate else None) as address:
            yield address
    except AgentsError as error:
        raise RunnerError(error.code, error.message) from error


def session_operation(
    mapping: dict, operation: str, *, response_timeout: float = OPERATION_TIMEOUT_SECONDS,
    **arguments: object,
) -> dict:
    """Ask the owner to control the exact mapped native execution and await its reply."""
    try:
        return connection_operation(mapping['control_directory'], {
            'operation': operation, 'session': mapping['session'],
            'execution_id': mapping['execution_id'], **arguments,
        }, response_timeout=response_timeout)
    except (KeyError, TypeError) as error:
        raise RunnerError('operation-failed', 'The mapped Session control identity is invalid.') from error


def connection_operation(
    address: str | dict,
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
    """
    if (type(response_timeout) not in (int, float)
            or not math.isfinite(response_timeout) or response_timeout <= 0):
        raise RunnerError('invalid-input', 'response_timeout must be finite and positive.')
    if isinstance(address, dict):
        from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

        try:
            return select_runtime_adapter(address['runtime']).send_host_event(address, document)
        except RuntimeAdapterError as error:
            raise RunnerError(error.code, error.message) from error

    from agent_swarm import AgentsError, connection_operation as exchange

    try:
        return exchange(address, document, authenticate=authenticate,
                        response_timeout=response_timeout, await_accepted=await_accepted, stoppable=stoppable)
    except AgentsError as error:
        raise RunnerError(error.code, error.message) from error


def record_lock_owner(descriptor: int) -> int:
    """Preserve the public Runner import for the shared kernel lock proof."""
    from agent_swarm import AgentsError, record_lock_owner as owner

    try:
        return owner(descriptor)
    except AgentsError as error:
        raise RunnerError(error.code, error.message) from error
