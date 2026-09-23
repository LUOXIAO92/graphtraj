"""Codex native Session control over one explicitly owned stdio connection."""

from __future__ import annotations

import asyncio
import json
import math
import os
import select
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from graphtraj.execution.execution_budget import _duration
from graphtraj.runtimes.codex.codex_adapter import (
    CodexAdapterError,
    CodexNativeTrace,
    _reject_legacy_user_sandbox_config,
)
from graphtraj.runtimes.runtime_adapter import RuntimeContext, RuntimeExecutionResult


_DEFAULT_TIMEOUT = object()


def _native_id(value: Any) -> str:
    """Validate a nonempty native Session or execution identifier."""
    if not isinstance(value, str) or not value:
        raise ValueError('Missing or invalid native Session/execution ID')
    return value


def _native_turn(value: Any) -> dict[str, Any]:
    """Validate the native turn fields required for safe lifecycle handling."""
    if not isinstance(value, dict):
        raise ValueError('Missing native turn object')
    _native_id(value.get('id'))
    if value.get('status') not in ('inProgress', 'completed', 'interrupted', 'failed'):
        raise ValueError('Invalid native turn status')
    if not isinstance(value.get('items'), list):
        raise ValueError('Invalid native turn items')
    for item in value['items']:
        if not isinstance(item, dict) or (
            item.get('type') == 'agentMessage' and not isinstance(item.get('text'), str)
        ):
            raise ValueError('Invalid native turn item')
    return value


def _instant(value: Any) -> bool:
    """Accept only an event instant that names its own explicit UTC offset."""
    if not isinstance(value, str) or not value:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _elapsed_minutes(value: Any) -> bool:
    """Accept only a finite nonnegative elapsed duration in minutes."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _text_input(prompt: str) -> list[dict[str, str]]:
    """Reject empty instructions before changing native execution ownership."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'A nonempty text instruction is required.')
    return [{'type': 'text', 'text': prompt}]


class CodexRPCError(CodexAdapterError):
    """A native error reply with its method, request identity and unaltered error."""

    def __init__(self, method: str, request_id: int, native_error: dict[str, Any]) -> None:
        """Retain the native failure without inventing an execution outcome."""
        super().__init__('RUNTIME_RPC_ERROR',
                         f'Codex {method} request {request_id}: {native_error}',
                         terminal_confirmed=False)
        self.method = method
        self.request_id = request_id
        self.native_error = native_error


@dataclass(frozen=True)
class CodexSession:
    """Native conversation identity and rollout location for the collector."""

    thread_id: str
    rollout_path: Path | None


@dataclass(frozen=True)
class CodexExecution:
    """Native target for active input, interruption and result retrieval."""

    thread_id: str
    turn_id: str


@dataclass(frozen=True)
class CodexServerRequest:
    """A native approval, tool, input or connection request routed to the caller.

    The handler returns the native response object. Request parameters and IDs
    are preserved; handling a method does not imply GraphTraj has real-tested it.
    """

    request_id: int | str
    method: str
    params: dict[str, Any]


@dataclass
class _ExecutionState:
    result: asyncio.Future[RuntimeExecutionResult | CodexAdapterError] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    last_message: str | None = None
    terminal: bool = False
    handle: CodexExecution | None = None


class CodexAppServer:
    """Own a stdio service on one asyncio loop; close it explicitly or with async with.

    Session and execution completion leave the service running. All methods must
    run on the connection's event loop. ``command`` selects the installed Codex
    executable (or a controlled external stdio peer).
    """

    def __init__(
        self,
        *,
        cwd: Path,
        command: Sequence[str] = ("codex", "app-server", "--listen", "stdio://"),
        environment: Mapping[str, str] | None = None,
        request_timeout: float = 30,
        on_request: Callable[[CodexServerRequest], Awaitable[Mapping[str, Any] | None]] | None = None,
        request_handler_timeout: float | None | object = _DEFAULT_TIMEOUT,
        experimental_api: bool = False,
    ) -> None:
        """Configure an unopened service with immutable environment overrides."""
        if (
            not command or isinstance(command, (str, bytes))
            or any(not isinstance(part, str) for part in command)
            or not command[0]
            or isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(request_timeout) or request_timeout <= 0
            or type(experimental_api) is not bool
        ):
            raise CodexAdapterError(
                'RUNTIME_REQUEST_INVALID',
                'Supply a command and a finite positive request timeout.',
            )
        self._cwd = cwd
        self._command = tuple(command)
        self._environment = {**os.environ, **(environment or {})}
        self._default_connection = {
            name: os.environ.get(name) for name in ('OPENAI_BASE_URL', 'OPENAI_API_KEY')
        }
        self._timeout = request_timeout
        self._experimental_api = experimental_api
        # Existing callers retain the RPC deadline; managed human replies can wait
        # indefinitely without extending RPC or service-shutdown deadlines.
        self._handler_timeout = (
            request_timeout if request_handler_timeout is _DEFAULT_TIMEOUT
            else request_handler_timeout
        )
        if self._handler_timeout is not None and (
            isinstance(self._handler_timeout, bool)
            or not isinstance(self._handler_timeout, (int, float))
            or not math.isfinite(self._handler_timeout) or self._handler_timeout <= 0
        ):
            raise CodexAdapterError(
                'RUNTIME_REQUEST_INVALID',
                'The request handler timeout must be finite and positive, or None.',
            )
        self._on_request = on_request
        self._handlers: dict[int | str, asyncio.Task[None]] = {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._stderr = b''
        self._pending: dict[int, asyncio.Future[dict[str, Any] | CodexAdapterError]] = {}
        self._sequence = 0
        self._sessions: dict[str, CodexSession] = {}
        self._thread_parents: dict[str, str | None] = {}
        self._resuming: set[str] = set()
        self._turns: dict[tuple[str, str], _ExecutionState] = {}
        self._active: dict[str, str | None] = {}
        self._traces: dict[str, CodexNativeTrace] = {}
        self._trace_tasks: dict[str, asyncio.Task[None]] = {}
        self._failure: CodexAdapterError | None = None
        self._closed = False
        self._opened = False
        self._close_task: asyncio.Task[None] | None = None
        # ponytail: one observer drains these per-connection control records;
        # durable, incremental native record retention belongs to C.2.
        self._notifications: asyncio.Queue[dict[str, Any] | CodexAdapterError] = asyncio.Queue()

    async def __aenter__(self) -> CodexAppServer:
        """Open stdio and perform initialize/initialized before Session operations."""
        if self._opened or self._closed:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The connection cannot be opened twice.')
        _reject_legacy_user_sandbox_config(
            Path(self._environment.get('CODEX_HOME', Path.home() / '.codex'))
        )
        self._opened = True
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command, cwd=self._cwd, env=self._environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                # Native history and tool records exceed asyncio's 64 KiB default.
                limit=16 * 1024 * 1024,
            )
        except (OSError, ValueError) as error:
            raise CodexAdapterError('RUNTIME_START_FAILED', f'Cannot open Codex stdio: {error}') from error
        self._reader = asyncio.create_task(self._read())
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        try:
            await self._call('initialize', {
                'clientInfo': {'name': 'graphtraj', 'version': '0.1.0'},
                'capabilities': {'experimentalApi': self._experimental_api},
            })
            await self._send({'method': 'initialized', 'params': {}})
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Release the service even when caller work fails."""
        await self.close()

    async def close(self) -> None:
        """Close and reap this service; cancellation of a waiter leaves cleanup owned."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_connection())
        await asyncio.shield(self._close_task)

    async def _close_connection(self) -> None:
        """Bound EOF shutdown, then terminate only this explicitly owned service group."""
        self._closed = True
        self._fail(CodexAdapterError('RUNTIME_CONNECTION_CLOSED', 'Codex connection explicitly closed.',
                                    terminal_confirmed=False))
        for task in self._handlers.values():
            task.cancel()
        await asyncio.gather(*self._handlers.values(), return_exceptions=True)
        if self._process is not None:
            assert self._process.stdin is not None
            self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), self._timeout)
            except TimeoutError:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(self._process.pid, sig)
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(self._process.wait(), self._timeout)
                        break
                    except TimeoutError:
                        continue
                else:
                    raise CodexAdapterError(
                        'RUNTIME_SHUTDOWN_FAILED', 'Codex service did not exit after explicit close.',
                        terminal_confirmed=False,
                    )
            if self._reader is not None:
                await self._reader
            if self._stderr_reader is not None:
                await self._stderr_reader
        await self._finish_native_traces()

    @property
    def service_pid(self) -> int:
        """Identify the owned service for process cleanup, never execution status."""
        self._require_connection()
        assert self._process is not None
        return self._process.pid

    @property
    def stderr_tail(self) -> str:
        """Return the last 16 KiB of service diagnostics, including startup errors."""
        return self._stderr.decode('utf-8', errors='replace')

    async def _read_stderr(self) -> None:
        """Drain stderr so diagnostics cannot stall native control traffic."""
        assert self._process is not None and self._process.stderr is not None
        try:
            while chunk := await self._process.stderr.read(8192):
                # ponytail: keep only a diagnostic tail; C.2 owns full collection.
                self._stderr = (self._stderr + chunk)[-16384:]
        except OSError as error:
            self._fail(CodexAdapterError('RUNTIME_CONNECTION_FAILED', f'Reading Codex stderr failed: {error}',
                                        terminal_confirmed=False))

    async def create_session(
        self, context: RuntimeContext, *, approval_policy: str | dict[str, Any] | None = None,
    ) -> CodexSession:
        """Create a native conversation with the resolved Session configuration."""
        return await self._session('thread/start', context, approval_policy=approval_policy)

    async def resume_session(
        self,
        context: RuntimeContext,
        thread_id: str,
        *,
        approval_policy: str | dict[str, Any] | None = None,
    ) -> CodexSession:
        """Load native history into this connection using the supplied Context."""
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'A native thread ID is required to resume.')
        if thread_id in self._sessions or thread_id in self._resuming:
            raise CodexAdapterError(
                'RUNTIME_LIFECYCLE_INVALID',
                'This connection already owns or is resuming the Session.',
            )
        self._resuming.add(thread_id)
        try:
            return await self._session('thread/resume', context, thread_id, approval_policy=approval_policy)
        finally:
            self._resuming.discard(thread_id)

    async def _session(
        self,
        method: str,
        context: RuntimeContext,
        thread_id: str | None = None,
        *,
        approval_policy: str | dict[str, Any] | None = None,
    ) -> CodexSession:
        """Project a resolved Context without mutating service environment."""
        self._require_connection()
        if context.runtime != 'codex':
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'Codex requires a resolved Codex Context.')
        connection = {**self._default_connection, **context.runtime_environment()}
        if any(self._environment.get(key) != value for key, value in connection.items()):
            raise CodexAdapterError('RUNTIME_CONNECTION_MISMATCH',
                                    'Open a separate connection with this Context runtime_environment().')
        params = context.session_document()['adapter_request']
        if approval_policy is not None:
            params['approvalPolicy'] = approval_policy
        if thread_id is not None:
            # The native resume schema restores the original tool declarations;
            # it does not accept new dynamicTools for an existing Session.
            params.pop('dynamicTools', None)
            params['threadId'] = thread_id
            params['excludeTurns'] = True
        response = await self._call(method, params)
        try:
            thread = response['thread']
            returned_id = _native_id(thread['id'])
            if returned_id in self._sessions or (thread_id is not None and returned_id != thread_id):
                raise ValueError('Codex returned a different or already owned Session')
            path = thread.get('path')
            if path is not None and (not isinstance(path, str) or not Path(path).is_absolute()):
                raise ValueError('Invalid native rollout path')
            session = CodexSession(returned_id, Path(path) if path else None)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise self._protocol_failure(f'{method}: {error}') from error
        self._sessions[session.thread_id] = session
        return session

    def retain_native_trace(self, session: CodexSession, trace_file: Path) -> None:
        """Read one owned Session's native records through the given Trace entry.

        The Trace entry becomes a symbolic link to the Runtime-owned native
        rollout as soon as that file exists, and keeps reading it while the
        Session runs. Calling this once per connection Session preserves C.1's
        Session and execution handles unchanged.
        """

        self._require_session(session)
        if not isinstance(trace_file, Path):
            raise CodexAdapterError(
                'RUNTIME_REQUEST_INVALID', 'A Trace entry path is required.',
            )
        if session.thread_id in self._traces:
            raise CodexAdapterError(
                'RUNTIME_LIFECYCLE_INVALID', 'The Session already retains a native Trace.',
            )
        try:
            trace = CodexNativeTrace(
                trace_file,
                session.thread_id,
                session.rollout_path,
                Path(
                    self._environment.get(
                        'CODEX_HOME', Path.home() / '.codex',
                    )
                ),
            )
        except OSError as error:
            raise CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            ) from error
        self._traces[session.thread_id] = trace
        try:
            trace.collect()
        except OSError as error:
            raise CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            ) from error
        self._trace_tasks[session.thread_id] = asyncio.create_task(
            self._collect_native_trace(trace)
        )

    async def start_execution(self, session: CodexSession, prompt: str) -> CodexExecution:
        """Start an idle Session's next native turn."""
        self._require_session(session)
        return await self._start_execution(session, _text_input(prompt))

    async def _start_execution(
        self,
        session: CodexSession,
        inputs: list[dict[str, Any]],
    ) -> CodexExecution:
        """Start one idle Session turn after validating its native input."""
        self._require_session(session)
        if session.thread_id in self._active:
            raise CodexAdapterError(
                'RUNTIME_LIFECYCLE_INVALID', 'The Session already has an active execution.',
            )
        # Reserve the Session before yielding; native turn/start can otherwise
        # steer an existing execution instead of starting the requested new one.
        self._active[session.thread_id] = None
        try:
            result = await self._call('turn/start', {
                'threadId': session.thread_id, 'input': inputs,
            })
        except BaseException:
            self._active.pop(session.thread_id, None)
            raise
        try:
            turn = _native_turn(result.get('turn'))
        except ValueError as error:
            raise self._protocol_failure(f'turn/start: {error}') from error
        execution = CodexExecution(session.thread_id, turn['id'])
        state = self._turns.setdefault((execution.thread_id, execution.turn_id), _ExecutionState())
        state.handle = execution
        if turn['status'] != 'inProgress':
            self._complete(execution.thread_id, turn)
        if not state.terminal:
            self._active[session.thread_id] = execution.turn_id
        else:
            self._active.pop(session.thread_id, None)
        return execution

    async def send_input(self, execution: CodexExecution, prompt: str) -> None:
        """Steer exactly the expected active native execution."""
        self._require_active(execution)
        result = await self._call('turn/steer', {
            'threadId': execution.thread_id, 'expectedTurnId': execution.turn_id,
            'input': _text_input(prompt),
        })
        if result.get('turnId') != execution.turn_id:
            raise self._protocol_failure('turn/steer did not acknowledge the expected native turn ID')

    async def interrupt(self, execution: CodexExecution) -> None:
        """Request interruption of this turn; wait separately for its terminal result."""
        self._require_active(execution)
        await self._call('turn/interrupt', {
            'threadId': execution.thread_id, 'turnId': execution.turn_id,
        })

    def _require_session(self, session: CodexSession) -> None:
        """Reject handles from another connection."""
        self._require_connection()
        if not isinstance(session, CodexSession) or self._sessions.get(session.thread_id) is not session:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The Session belongs to another connection.')

    def _require_active(self, execution: CodexExecution) -> None:
        """Reject stale active control before sending a native request."""
        self._require_connection()
        self._execution_state(execution)
        if self._active.get(execution.thread_id) != execution.turn_id:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The target execution is not active.')

    async def wait(
        self, execution: CodexExecution, *, timeout: float | None = None,
    ) -> RuntimeExecutionResult:
        """Obtain this execution's result without ending its connection."""
        state = self._execution_state(execution)
        try:
            result = await asyncio.wait_for(asyncio.shield(state.result), timeout)
        except TimeoutError as error:
            raise CodexAdapterError(
                'RUNTIME_TIMEOUT', f'Waiting for {execution} timed out; it remains owned.',
                terminal_confirmed=False,
            ) from error
        try:
            self._collect_native_trace_once(execution.thread_id)
        except CodexAdapterError as error:
            result = error
        if isinstance(result, CodexAdapterError):
            if state.terminal and not result.terminal_confirmed:
                raise CodexAdapterError(result.code, result.message) from result
            raise result
        return result.copy()

    async def _collect_native_trace(self, trace: CodexNativeTrace) -> None:
        """Watch for one native rollout without blocking control-message processing."""

        try:
            while not self._closed:
                trace.collect()
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            raise
        except OSError:
            self._fail(CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            ))

    def _collect_native_trace_once(self, thread_id: str) -> None:
        """Link a terminal Session's rollout once before returning its result."""

        trace = self._traces.get(thread_id)
        if trace is None:
            return
        try:
            trace.collect()
        except OSError as error:
            failure = CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            )
            self._fail(failure)
            raise failure from error

    async def _finish_native_traces(self) -> None:
        """Stop background collection after one final link attempt."""

        for task in self._trace_tasks.values():
            task.cancel()
        await asyncio.gather(*self._trace_tasks.values(), return_exceptions=True)
        for thread_id in self._traces:
            self._collect_native_trace_once(thread_id)

    def _execution_state(self, execution: CodexExecution) -> _ExecutionState:
        """Resolve only a handle returned by this connection, even if IDs collide."""
        if isinstance(execution, CodexExecution):
            state = self._turns.get((execution.thread_id, execution.turn_id))
            if state is not None and state.handle is execution:
                return state
        raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The execution belongs to another connection.')

    async def read_thread_parent(self, thread_id: str) -> str | None:
        """Read immutable native parent identity over the owned Runtime connection.

        This reads metadata, never conversation turns. The identifier must come
        from a native callback when used for authorization; validating a caller's
        claimed identifier does not authenticate an ordinary CLI process.
        """
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'A native thread ID is required.')
        response = await self._call('thread/read', {
            'threadId': thread_id, 'includeTurns': False,
        })
        thread = response.get('thread')
        if (
            not isinstance(thread, dict)
            or thread.get('id') != thread_id
            or 'parentThreadId' not in thread
        ):
            raise self._protocol_failure('Native thread metadata does not identify its parent.')
        parent = thread['parentThreadId']
        if parent is not None and (not isinstance(parent, str) or not parent or parent == thread_id):
            raise self._protocol_failure('Native thread metadata has an invalid parent.')
        if thread_id in self._thread_parents and self._thread_parents[thread_id] != parent:
            raise self._protocol_failure('Native thread metadata changed its recorded parent.')
        self._thread_parents[thread_id] = parent
        return parent

    async def next_notification(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive a raw native notification; one observer drains this connection.

        These control notifications do not replace the native rollout. Consume
        them while connected if observation is needed; they retain native IDs.
        """
        if self._notifications.empty():
            self._require_connection()
        try:
            message = await asyncio.wait_for(self._notifications.get(), timeout)
        except TimeoutError as error:
            raise CodexAdapterError('RUNTIME_TIMEOUT', 'Waiting for a Codex notification timed out.',
                                    terminal_confirmed=False) from error
        if isinstance(message, CodexAdapterError):
            raise message
        return message

    def _require_connection(self) -> None:
        """Reject work after transport failure or outside the open lifetime."""
        if self._failure is not None:
            raise self._failure
        if self._process is None:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'Open the Codex connection first.')

    def _fail(self, error: CodexAdapterError) -> None:
        """Make background transport failure visible to every pending owner."""
        if self._failure is None:
            self._failure = error
            self._notifications.put_nowait(error)
        for future in [*self._pending.values(), *(state.result for state in self._turns.values())]:
            if not future.done():
                # Store errors as values until a public waiter observes them;
                # abandoned callers must not produce unobserved Future errors.
                future.set_result(self._failure)

    def _protocol_failure(self, message: str) -> CodexAdapterError:
        """Invalidate a connection whose native lifecycle can no longer be trusted."""
        error = CodexAdapterError('RUNTIME_PROTOCOL_ERROR', message, terminal_confirmed=False)
        self._fail(error)
        return error

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Correlate a client request while the reader consumes interleaved events."""
        self._require_connection()
        self._sequence += 1
        request_id = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(self._timeout):
                await self._send({'id': request_id, 'method': method, 'params': params})
                response = await asyncio.shield(future)
        except TimeoutError as error:
            failure = CodexAdapterError(
                'RUNTIME_TIMEOUT',
                f'Codex {method} request {request_id} timed out; close this connection.',
                terminal_confirmed=False,
            )
            self._fail(failure)
            raise failure from error
        except asyncio.CancelledError:
            self._fail(CodexAdapterError(
                'RUNTIME_REQUEST_CANCELLED',
                f'Codex {method} request {request_id} was abandoned; close this connection.',
                terminal_confirmed=False,
            ))
            raise
        finally:
            self._pending.pop(request_id, None)
        if isinstance(response, CodexAdapterError):
            raise response
        if 'error' in response:
            raise CodexRPCError(method, request_id, response['error'])
        self._require_connection()
        return response['result']

    async def _send(self, message: dict[str, Any]) -> None:
        """Write one complete JSON line before yielding to other operations."""
        self._require_connection()
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write((json.dumps(message, allow_nan=False) + '\n').encode())
            await self._process.stdin.drain()
        except (OSError, ValueError, TypeError) as error:
            failure = CodexAdapterError('RUNTIME_CONNECTION_FAILED', f'Writing Codex stdio failed: {error}',
                                        terminal_confirmed=False)
            self._fail(failure)
            raise failure from error

    async def _read(self) -> None:
        """Consume responses and native completion notifications asynchronously."""
        assert self._process is not None and self._process.stdout is not None
        try:
            async for line in self._process.stdout:
                message = json.loads(line)
                self._receive(message)
        except Exception as error:
            self._protocol_failure(f'Reading Codex stdio failed: {error}')
        else:
            self._fail(CodexAdapterError(
                'RUNTIME_CONNECTION_CLOSED', 'Codex stdio closed before explicit close.',
                terminal_confirmed=False,
            ))

    def _receive(self, message: Any) -> None:
        """Validate native envelopes before routing either request namespace."""
        if not isinstance(message, dict):
            raise ValueError('Expected a JSON object')
        if 'id' in message and type(message['id']) not in (int, str):
            raise ValueError('Invalid native request ID')
        if 'method' in message:
            if not isinstance(message['method'], str) or not isinstance(message.get('params'), dict):
                raise ValueError('Invalid native method/params')
            if 'id' in message:
                request = CodexServerRequest(message['id'], message['method'], message['params'])
                if request.request_id in self._handlers:
                    raise ValueError('Duplicate pending native server request ID')
                task = asyncio.create_task(self._handle_request(request))
                self._handlers[request.request_id] = task
                task.add_done_callback(
                    lambda completed, key=request.request_id: self._handlers.pop(key, None)
                    if self._handlers.get(key) is completed else None
                )
                return
            params = message.get('params', {})
            if message['method'] == 'serverRequest/resolved':
                task = self._handlers.pop(params['requestId'], None)
                if task is not None:
                    task.cancel()
            elif message['method'] == 'item/completed':
                key = (_native_id(params['threadId']), _native_id(params['turnId']))
                state = self._turns.setdefault(key, _ExecutionState())
                item = params['item']
                if item['type'] == 'agentMessage':
                    if not isinstance(item['text'], str):
                        raise ValueError('Invalid native Agent message text')
                    state.last_message = item['text']
            elif message['method'] == 'turn/completed':
                self._complete(_native_id(params['threadId']), _native_turn(params['turn']))
            self._notifications.put_nowait(message)
        else:
            if ('result' in message) == ('error' in message):
                raise ValueError('Response must contain exactly one result or error')
            payload = message.get('result', message.get('error'))
            if not isinstance(payload, dict):
                raise ValueError('Invalid native response object')
            if 'error' in message and (
                type(payload.get('code')) is not int or not isinstance(payload.get('message'), str)
            ):
                raise ValueError('Invalid native error object')
            self._pending[message['id']].set_result(message)

    def _complete(self, thread_id: str, turn: dict[str, Any]) -> None:
        """Finish the native turn without clearing a newer execution's ownership."""
        if turn['status'] == 'inProgress':
            raise ValueError('Nonterminal turn/completed notification')
        key = (thread_id, turn['id'])
        state = self._turns.setdefault(key, _ExecutionState())
        if self._active.get(thread_id) == turn['id']:
            self._active.pop(thread_id)
        state.terminal = True
        if state.result.done():
            return
        if turn['status'] == 'failed':
            state.result.set_result(CodexAdapterError(
                'RUNTIME_EXECUTION_FAILED', f'Codex execution {key}: {turn.get("error")}',
            ))
        else:
            # Some responses include the final items without separate notices.
            for item in turn['items']:
                if item.get('type') == 'agentMessage':
                    state.last_message = item['text']
            state.result.set_result({
                'outcome': turn['status'], 'session_id': thread_id,
                'execution_id': turn['id'], 'last_agent_message': state.last_message,
            })

    async def _handle_request(self, request: CodexServerRequest) -> None:
        """Route server-initiated work without blocking the connection reader."""
        key = (request.params.get('threadId'), request.params.get('turnId'))
        failure = None
        result = None
        try:
            if self._on_request is not None:
                result = await asyncio.wait_for(self._on_request(request), self._handler_timeout)
            if result is None:
                failure = CodexAdapterError(
                    'RUNTIME_REQUEST_UNHANDLED',
                    f'No caller handles {request.method} request {request.request_id}.',
                    terminal_confirmed=False,
                )
            elif not isinstance(result, Mapping):
                raise ValueError('The native response must be a mapping or None')
            else:
                result = dict(result)
                json.dumps(result, allow_nan=False)
        except (Exception, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.CancelledError) and (
                self._closed or self._failure is not None
                or self._handlers.get(request.request_id) is not asyncio.current_task()
            ):
                return
            failure = CodexAdapterError(
                'RUNTIME_REQUEST_FAILED',
                f'{request.method} request {request.request_id}: {type(error).__name__}: {error}',
                terminal_confirmed=False,
            )
        try:
            if failure is None:
                state = self._turns.get(key)
                if (
                    self._handlers.get(request.request_id) is not asyncio.current_task()
                    or (state and state.terminal)
                ):
                    return  # Withdrawal or completion won the race with the reply.
                await self._send({'id': request.request_id, 'result': result})
            else:
                scoped = all(isinstance(value, str) and value for value in key)
                if scoped:
                    state = self._turns.setdefault(key, _ExecutionState())
                    if not state.result.done():
                        state.result.set_result(failure)
                await self._send({'id': request.request_id, 'error': {
                    'code': -32601 if failure.code == 'RUNTIME_REQUEST_UNHANDLED' else -32603,
                    'message': failure.message,
                }})
                if not scoped:
                    self._fail(failure)
        except CodexAdapterError as error:
            self._fail(error)


class CodexMainRecovery:
    """Return one enforced stop through the Runner call Main is awaiting.

    The binding owns the neutral caller-notice channel of one Runner
    operation. A sampled stochastic stop that arrives on that channel is
    retained as a delivery - stop identity, the stop's own absolute instant,
    the elapsed work duration and the explicit ``retro`` Skill reference - so
    the document this call returns carries it to the active Main. Ordinary
    estimate and allowance notices stay inert. Nothing is queued into Main's
    native input, and no second Main or Driver is created.
    """

    def __init__(self, retro_skill_path: Path) -> None:
        """Bind one caller channel to an existing absolute ``retro`` Skill path."""
        if (
            not isinstance(retro_skill_path, Path)
            or not retro_skill_path.is_absolute()
            or retro_skill_path.name != "SKILL.md"
            or not retro_skill_path.is_file()
        ):
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "Codex Main recovery requires an existing absolute SKILL.md path.",
            )
        self._retro_skill_path = retro_skill_path.resolve()
        self._read_fd: int | None = None
        self._notice_fd: int | None = None
        self._reader: threading.Thread | None = None
        self._closing = threading.Event()
        self._idle_pass = threading.Event()
        self._lock = threading.Lock()
        self._pending = b""
        self._stops: set[str] = set()
        self._deliveries: list[dict[str, Any]] = []
        self._error: CodexAdapterError | None = None
        self._opened = False
        self._closed = False

    @classmethod
    def from_environment(cls, cwd: Path) -> "CodexMainRecovery | None":
        """Return the installed caller binding when this process owns a Codex Main."""
        if not os.environ.get("CODEX_THREAD_ID") or os.environ.get("GRAPHTRAJ_ROLE"):
            return None
        return cls(cwd / ".agents/skills/retro/SKILL.md")

    @classmethod
    def from_request(
        cls, cwd: Path, metadata: object
    ) -> "CodexMainRecovery | None":
        """Return the caller binding for one request's own Codex metadata.

        The caller sends the identity of the Codex thread that made the request,
        so a host-serving process selects the right Main without guessing from
        its own environment. A request without that metadata, or a Harness
        Project Root without the installed ``retro`` Skill, keeps the generic
        behaviour of no notice channel instead of failing its operation.
        """
        thread_id = (
            metadata.get("threadId") if isinstance(metadata, Mapping) else None
        )
        skill_path = cwd / ".agents/skills/retro/SKILL.md"
        if not isinstance(thread_id, str) or not thread_id or not skill_path.is_file():
            return None
        return cls(skill_path)

    def __enter__(self) -> "CodexMainRecovery":
        """Start the narrow notice reader before the wrapped Runner operation."""
        with self._lock:
            if self._opened or self._closed:
                raise CodexAdapterError(
                    "RUNTIME_LIFECYCLE_INVALID",
                    "The Codex Main recovery binding cannot be opened twice.",
                )
            self._read_fd, self._notice_fd = os.pipe()
            self._opened = True
            self._reader = threading.Thread(
                target=self._read_notices,
                name="graphtraj-codex-main-recovery",
            )
            self._reader.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop reading notices and preserve any wrapped-operation exception chain."""
        self.close()

    @property
    def notice_fd(self) -> int:
        """Return the existing neutral caller-notice channel while it is open."""
        with self._lock:
            if self._notice_fd is None:
                raise CodexAdapterError(
                    "RUNTIME_LIFECYCLE_INVALID",
                    "Open the Codex Main recovery binding before selecting its notice channel.",
                )
            return self._notice_fd

    def close(self) -> None:
        """Release the caller channel and surface any retained reader failure."""
        with self._lock:
            first_close = not self._closed
            self._closing.set()
            if self._notice_fd is not None:
                os.close(self._notice_fd)
                self._notice_fd = None
            reader = self._reader
        if first_close and reader is not None and reader is not threading.current_thread():
            reader.join()
        with self._lock:
            self._closed = True
            error = self._error
        if error is not None:
            raise error

    def take_stop_deliveries(self) -> tuple[dict[str, Any], ...]:
        """Return the stops this call now delivers, each stamped once at the return.

        The delivery instant is the actual moment this document returns to
        Main, so a stop withheld until a long operation finished keeps showing
        its own trigger instant instead of appearing to have just happened.
        """
        # Let the reader retain input already waiting in the caller channel, so
        # a stop written by this operation is not left behind by the return.
        self._idle_pass.clear()
        self._idle_pass.wait(0.5)
        with self._lock:
            deliveries, self._deliveries = self._deliveries, []
        if not deliveries:
            return ()
        delivered_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return tuple(
            {**delivery, "delivered_at": delivered_at} for delivery in deliveries
        )

    def attach_stop_deliveries(
        self, document: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return one Runner document carrying the stops this call delivered.

        Ordinary results keep their existing shape: the field appears only when
        this call actually returns a stop to the Main that made it.
        """
        deliveries = self.take_stop_deliveries()
        if not deliveries:
            return dict(document)
        return {**document, "stop_deliveries": list(deliveries)}

    def _deliver_notice(self, line: bytes) -> None:
        """Retain one stochastic stop while keeping ordinary caller notices inert."""
        try:
            notice = json.loads(line)
            if not isinstance(notice, dict):
                raise ValueError("Budget notice is not an object")
            stop = self._stop_key(notice)
            if stop is None:
                return
            with self._lock:
                if stop in self._stops:
                    return
                ticket_id, ticket_name, limit = json.loads(stop)
                delivery = self._stop_delivery(
                    ticket_id,
                    ticket_name,
                    limit,
                    notice["occurred_at"],
                    notice["actual"]["elapsed_minutes"],
                )
                self._stops.add(stop)
                self._deliveries.append(delivery)
        except CodexAdapterError as error:
            self._record_error(error)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._record_error(CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The Codex Main budget notice is invalid: {0}".format(error),
            ))

    def _stop_delivery(
        self,
        ticket_id: str,
        ticket_name: str,
        limit: float,
        triggered_at: str,
        elapsed_minutes: float,
    ) -> dict[str, Any]:
        """Describe one enforced stop for the Runner call that returns it.

        The instruction is the user's standing explicit ``retro`` input: Main
        executes that named Skill from this evidence without another approval,
        while ordinary reminders never carry it.
        """
        elapsed = _duration(elapsed_minutes)
        stop_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "graphtraj:budget-stop:{0}:{1}:{2}".format(ticket_id, ticket_name, limit),
        ))
        return {
            "stop_id": stop_id,
            "stop": "stochastic_stop:{0}".format(limit),
            "ticket": {"ticket_id": ticket_id, "ticket_name": ticket_name},
            "triggered_at": triggered_at,
            "elapsed": elapsed,
            "instruction": (
                "$retro Analyze the enforced stochastic stop stochastic_stop:{0} "
                "for Ticket {1} using the retained wrap-up and evidence. Stop time: "
                "{2}. Elapsed work: {3}. Execute the retro Skill now for this stop, "
                "identify scheduling corrections before deciding continuation, "
                "reuse existing findings and do not restart work."
            ).format(limit, ticket_id, triggered_at, elapsed),
            "skill": {"name": "retro", "path": str(self._retro_skill_path)},
        }

    def _record_error(self, error: CodexAdapterError) -> None:
        """Keep the first concrete delivery failure for every close caller."""
        with self._lock:
            if self._error is None:
                self._error = error

    def _read_notices(self) -> None:
        """Read JSONL until this caller closes the channel."""
        pending = self._pending
        try:
            while self._read_fd is not None:
                ready, _, _ = select.select([self._read_fd], [], [], 0.05)
                if not ready:
                    if self._closing.is_set():
                        return
                    self._idle_pass.set()
                    continue
                chunk = os.read(self._read_fd, 8192)
                if not chunk:
                    return
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self._deliver_notice(line)
        except (OSError, ValueError) as error:
            self._record_error(
                CodexAdapterError(
                    "RUNTIME_CONNECTION_FAILED",
                    "The Codex Main notice channel failed: {0}".format(error),
                    terminal_confirmed=False,
                )
            )
        finally:
            with self._lock:
                self._pending = pending

    @staticmethod
    def _stop_key(notice: Mapping[str, Any]) -> str | None:
        """Return a stable stop identity without adding Codex fields to budget state."""
        if not isinstance(notice, Mapping) or notice.get("type") != "execution-budget-exceeded":
            return None
        threshold = notice.get("threshold")
        if not isinstance(threshold, Mapping) or not isinstance(threshold.get("kind"), str):
            raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The budget notice threshold is invalid.")
        if threshold["kind"] != "stochastic_stop":
            return None
        ticket = notice.get("ticket")
        limit = threshold.get("limit")
        actual = notice.get("actual")
        if (
            not isinstance(ticket, Mapping)
            or not isinstance(ticket.get("ticket_id"), str)
            or not ticket["ticket_id"]
            or not isinstance(ticket.get("ticket_name"), str)
            or not ticket["ticket_name"]
            or isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(limit)
            or not _instant(notice.get("occurred_at"))
            or not isinstance(actual, Mapping)
            or not _elapsed_minutes(actual.get("elapsed_minutes"))
        ):
            raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The stochastic-stop notice is invalid.")
        return json.dumps(
            (ticket["ticket_id"], ticket["ticket_name"], limit),
            allow_nan=False,
            separators=(",", ":"),
        )
