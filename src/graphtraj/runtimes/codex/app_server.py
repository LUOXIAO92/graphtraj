"""Codex native Session control over one explicitly owned stdio connection."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from graphtraj.runtimes.codex.codex_adapter import (
    CodexAdapterError,
    _reject_legacy_user_sandbox_config,
)
from graphtraj.runtimes.runtime_adapter import RuntimeContext, RuntimeExecutionResult


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
    ) -> None:
        """Configure an unopened service with immutable environment overrides."""
        if (
            not command or isinstance(command, (str, bytes))
            or any(not isinstance(part, str) for part in command)
            or not command[0]
            or isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(request_timeout) or request_timeout <= 0
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
        self._on_request = on_request
        self._handlers: dict[int | str, asyncio.Task[None]] = {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._stderr = b''
        self._pending: dict[int, asyncio.Future[dict[str, Any] | CodexAdapterError]] = {}
        self._sequence = 0
        self._sessions: dict[str, CodexSession] = {}
        self._resuming: set[str] = set()
        self._turns: dict[tuple[str, str], _ExecutionState] = {}
        self._active: dict[str, str | None] = {}
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
                'capabilities': {'experimentalApi': False},
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
        if self._process is None:
            return
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
        params['approvalsReviewer'] = 'user'
        if approval_policy is not None:
            params['approvalPolicy'] = approval_policy
        if thread_id is not None:
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

    async def start_execution(self, session: CodexSession, prompt: str) -> CodexExecution:
        """Start an idle Session's next native turn."""
        self._require_session(session)
        inputs = _text_input(prompt)
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
        if isinstance(result, CodexAdapterError):
            if state.terminal and not result.terminal_confirmed:
                raise CodexAdapterError(result.code, result.message) from result
            raise result
        return result.copy()

    def _execution_state(self, execution: CodexExecution) -> _ExecutionState:
        """Resolve only a handle returned by this connection, even if IDs collide."""
        if isinstance(execution, CodexExecution):
            state = self._turns.get((execution.thread_id, execution.turn_id))
            if state is not None and state.handle is execution:
                return state
        raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The execution belongs to another connection.')

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
                result = await asyncio.wait_for(self._on_request(request), self._timeout)
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
                self._closed or self._failure is not None or request.request_id not in self._handlers
            ):
                return
            failure = CodexAdapterError(
                'RUNTIME_REQUEST_FAILED',
                f'{request.method} request {request.request_id}: {type(error).__name__}: {error}',
                terminal_confirmed=False,
            )
        try:
            if failure is None:
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
