"""Codex native Session control over one explicitly owned stdio connection."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .context import CodexAdapterError, reject_legacy_sandbox_config
from .trace import CodexNativeTrace
from agent_swarm import __version__
from agent_swarm.runtime import RuntimeContext, RuntimeExecutionResult
from agent_swarm.codex.websocket import CodexWebSocket


_DEFAULT_TIMEOUT = object()
# Reported sandbox policy types and their thread/fork SandboxMode selections.
_SANDBOX_MODES = {
    'readOnly': 'read-only', 'workspaceWrite': 'workspace-write', 'dangerFullAccess': 'danger-full-access',
}


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
    configuration: dict[str, Any] = field(default_factory=dict)
    turn_settings: dict[str, Any] = field(default_factory=dict)
    inherited_history: dict[str, Any] | None = field(default=None, repr=False)
    inherited_history_excluded: bool = False


@dataclass(frozen=True)
class CodexExecution:
    """Native target for active input, interruption and result retrieval."""

    thread_id: str
    turn_id: str


@dataclass(frozen=True)
class CodexServerRequest:
    """A native approval, tool, input or connection request routed to the caller.

    The handler returns the native response object. Request parameters and IDs
    are preserved; handling a method does not imply it has been real-tested.
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
        environment: Mapping[str, str | None] | None = None,
        request_timeout: float = 30,
        on_request: Callable[[CodexServerRequest], Awaitable[Mapping[str, Any] | None]] | None = None,
        request_handler_timeout: float | None | object = _DEFAULT_TIMEOUT,
        experimental_api: bool = False,
        local_websocket: Mapping[str, Any] | None = None,
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
        from agent_swarm.codex.local_websocket import validate_connection
        self._local_websocket = validate_connection(local_websocket)
        self._remote_socket = None
        self._cwd = cwd
        self._command = tuple(command)
        self._environment = {key: value for key, value in {**os.environ, **(environment or {})}.items()
                             if value is not None}
        # A variable the caller removed on purpose is no connection mismatch.
        self._default_connection = {
            name: os.environ.get(name) for name in ('OPENAI_BASE_URL', 'OPENAI_API_KEY')
            if (environment or {}).get(name, '') is not None
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
        self._websocket: CodexWebSocket | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._stderr = b''
        self._pending: dict[int, asyncio.Future[dict[str, Any] | CodexAdapterError]] = {}
        self._sequence = 0
        self._sessions: dict[str, CodexSession] = {}
        self._thread_parents: dict[str, str | None] = {}
        self._token_usage: dict[str, dict[str, Any]] = {}
        self._resuming: set[str] = set()
        self._turns: dict[tuple[str, str], _ExecutionState] = {}
        self._active: dict[str, str | None] = {}
        self._traces: dict[str, CodexNativeTrace] = {}
        self._trace_tasks: dict[str, asyncio.Task[None]] = {}
        self._trace_changes: dict[str, asyncio.Event] = {}
        self._failure: CodexAdapterError | None = None
        self._closed = False
        self._opened = False
        self._close_task: asyncio.Task[None] | None = None
        # One observer drains control records. Fork archives receive their own
        # native notices before delivery; persistent Sessions use their rollout.
        self._notifications: asyncio.Queue[dict[str, Any] | CodexAdapterError] = asyncio.Queue()
        self._fork_archives: dict[str, Any] = {}
        self._ordered_archives: dict[str, Any] = {}
        self._ordered_tasks: dict[str, asyncio.Task] = {}
        # Native model/rerouted params by (thread, turn), recorded before the
        # turn's own completion is read, so a result can name its reroute.
        self.reroutes: dict[tuple[str, str], dict[str, Any]] = {}

    async def __aenter__(self) -> CodexAppServer:
        """Open stdio and perform initialize/initialized before Session operations."""
        if self._opened or self._closed:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'The connection cannot be opened twice.')
        if self._local_websocket is not None:
            return await self._open_local_websocket()
        # A proxy does not launch or configure a service. Its existing host owns
        # configuration and permissions; do not read or override them here.
        if self._command[1:3] != ('app-server', 'proxy'):
            reject_legacy_sandbox_config(
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
        self._stderr_reader = asyncio.create_task(self._read_stderr())
        try:
            if self._command[1:3] == ('app-server', 'proxy'):
                assert self._process.stdout is not None and self._process.stdin is not None
                self._websocket = CodexWebSocket(self._process.stdout, self._process.stdin)
                try:
                    await asyncio.wait_for(self._websocket.open(), self._timeout)
                except Exception as error:
                    raise CodexAdapterError(
                        'RUNTIME_CONNECTION_FAILED',
                        f'Codex WebSocket Upgrade failed: {error}{await self._stderr_detail()}',
                        terminal_confirmed=False,
                    ) from error
            self._reader = asyncio.create_task(self._read())
            await self._call('initialize', {
                'clientInfo': {'name': 'graphtraj', 'version': __version__},
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

    async def _open_local_websocket(self) -> CodexAppServer:
        """Authenticate to an existing service through the native HTTP proxy."""
        import logging
        from websockets.asyncio.client import connect
        assert self._local_websocket is not None
        settings = self._local_websocket
        self._opened = True
        phase = 'token-file'
        try:
            token = Path(settings['token_file']).read_text(encoding='utf-8').strip()
            if not token or any(char.isspace() for char in token):
                raise ValueError('Invalid local token file.')
            phase = 'native-proxy'
            proxy_url = self._environment.get('HTTP_PROXY') or self._environment.get('http_proxy')
            if not proxy_url:
                raise ValueError('A native HTTP proxy is required for the local connection.')
            phase = 'authenticated-upgrade'
            self._remote_socket = await connect(
                settings['url'], proxy=proxy_url,
                additional_headers={'Authorization': 'Bearer ' + token},
                open_timeout=self._timeout, close_timeout=self._timeout,
                max_size=128 * 1024 * 1024,
                logger=logging.Logger('graphtraj.codex.local', level=logging.WARNING),
            )
            phase = 'native-identity'
            self._reader = asyncio.create_task(self._read())
            result = await self._call('initialize', {
                'clientInfo': {'name': 'graphtraj', 'version': __version__},
                'capabilities': {'experimentalApi': self._experimental_api},
            })
            if result.get('codexHome') != settings['codex_home']:
                raise ValueError('Native service returned a different Codex home.')
            await self._send({'method': 'initialized', 'params': {}})
        except BaseException as error:
            await self.close()
            if isinstance(error, asyncio.CancelledError):
                raise
            # Handshake exceptions may contain request headers. Never retain them.
            raise CodexAdapterError(
                'RUNTIME_CONNECTION_FAILED',
                'Local Codex WebSocket failed during ' + phase + ' (' + type(error).__name__ + ').',
                terminal_confirmed=False,
            ) from None
        return self

    async def _close_connection(self) -> None:
        """Bound EOF shutdown, then terminate only this explicitly owned service group."""
        await asyncio.gather(*self._ordered_tasks.values(), return_exceptions=True)
        for archive in self._ordered_archives.values():
            await archive.collect()
        self._closed = True
        self._fail(CodexAdapterError('RUNTIME_CONNECTION_CLOSED', 'Codex connection explicitly closed.',
                                    terminal_confirmed=False))
        for task in self._handlers.values():
            task.cancel()
        await asyncio.gather(*self._handlers.values(), return_exceptions=True)
        if self._remote_socket is not None:
            await self._remote_socket.close()
            if self._reader is not None:
                await self._reader
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
        for archive in self._fork_archives.values():
            archive.close()

    @property
    def service_pid(self) -> int:
        """Identify the owned service for process cleanup, never execution status."""
        self._require_connection()
        if self._process is None:
            raise CodexAdapterError('authority-denied', 'An existing WebSocket service is not an owned process.')
        return self._process.pid

    def authenticate_caller(self, pid: int) -> None:
        """Require a kernel-observed caller below this still-live service."""
        from agent_swarm import AgentsError
        from agent_swarm.process import process_ancestors

        if (self._process is None or self._process.returncode is not None
                or self._process.pid not in process_ancestors(pid)):
            raise AgentsError('authority-denied', 'Caller is outside the live Codex service.')

    def native_connection(self, thread_id: str) -> dict:
        """Return the selected service locator without credentials or inferred parentage."""
        return {'runtime': 'codex', 'session': thread_id,
                'codex_home': os.path.abspath(self._environment.get('CODEX_HOME', Path.home() / '.codex'))}

    @property
    def stderr_tail(self) -> str:
        """Return the last 16 KiB of service diagnostics, including startup errors."""
        return self._stderr.decode('utf-8', errors='replace')

    async def _stderr_detail(self) -> str:
        """Return the proxy's own refusal as a short redacted suffix, if it wrote one.

        A process that already failed closes stderr promptly; the wait is
        bounded so a still-running proxy cannot delay the reported failure.
        """
        from .diagnostics import redact

        if self._stderr_reader is not None:
            await asyncio.wait({self._stderr_reader}, timeout=1)
        tail = redact(self.stderr_tail.strip())[-500:]
        return f' Proxy stderr: {tail}' if tail else ''

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
        response = await self._call(method, params, wait_for_session=True)
        try:
            thread = response['thread']
            returned_id = _native_id(thread['id'])
            if returned_id in self._sessions or (thread_id is not None and returned_id != thread_id):
                raise ValueError('Codex returned a different or already owned Session')
            path = thread.get('path')
            if path is not None and (not isinstance(path, str) or not Path(path).is_absolute()):
                raise ValueError('Invalid native rollout path')
            # Keep the native approval facts the Runtime reported at startup.
            # Keep the model the Runtime selected, to compare with the requested one.
            facts = {key: response[key] for key in ('approvalPolicy', 'approvalsReviewer', 'model')
                     if key in response}
            session = CodexSession(returned_id, Path(path) if path else None, facts)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise self._protocol_failure(f'{method}: {error}') from error
        self._sessions[session.thread_id] = session
        return session

    def retain_native_trace(
        self, session: CodexSession, trace_file: Path,
        *, archive: Any | None = None,
    ) -> None:
        """Read one owned Session's native records through the given Trace entry.

        The Trace entry becomes a symbolic link to the Runtime-owned native
        rollout as soon as that file exists, and keeps reading it while the
        Session runs. Calling this once per connection Session preserves C.1's
        Session and execution handles unchanged. An archive copies complete
        native records and commits their source cursor in project storage.
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
                archive=archive,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            raise CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            ) from error
        self._traces[session.thread_id] = trace
        try:
            trace.collect()
        except (OSError, ValueError, sqlite3.Error) as error:
            raise CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex Session Trace could not be retained.',
                terminal_confirmed=False,
            ) from error
        self._trace_changes[session.thread_id] = asyncio.Event()
        self._trace_tasks[session.thread_id] = asyncio.create_task(
            self._collect_native_trace(trace, self._trace_changes[session.thread_id])
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
                **session.turn_settings,
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

    async def send_host_event(self, thread_id: str, event: dict[str, str]) -> dict:
        """Start or steer an already-loaded host thread with genuine tool output.

        The host enforces direct-input and provider checks. No settings, native
        user input, Session creation or resume request accompanies this event.
        The reply acknowledges submission, not the parent's processing.
        """
        # Once written, the host may apply it: await its reply while this
        # connection lives, so a late reply never causes a resubmission.
        result = await self._call('turn/start', {
            'threadId': _native_id(thread_id), 'input': [],
            'toolOutput': {'name': 'graphtraj', 'output': json.dumps(event, ensure_ascii=False)},
        }, wait_for_session=True)
        try:
            _native_turn(result.get('turn'))
        except ValueError as error:
            failure = self._protocol_failure(f'turn/start: {error}')
            failure.request_written = True  # The host replied, so it received the event.
            raise failure from error
        return result

    async def send_input(self, execution: CodexExecution, prompt: str) -> None:
        """Steer exactly the expected active native execution."""
        self._require_active(execution, inactive_code='runtime-input-closed')
        result = await self._call('turn/steer', {
            'threadId': execution.thread_id, 'expectedTurnId': execution.turn_id,
            'input': _text_input(prompt),
        })
        if result.get('turnId') != execution.turn_id:
            raise self._protocol_failure('turn/steer did not acknowledge the expected native turn ID')

    async def approve_denied_action(self, thread_id: str, event: dict[str, Any]) -> None:
        """Record one approval for a single retry of an auto-review denial.

        Codex keeps the retry under auto review; this only adds the approval
        context the model sees. ``event`` is the serialized native assessment.
        """
        await self._call('thread/approveGuardianDeniedAction', {
            'threadId': _native_id(thread_id), 'event': event,
        })

    async def turn_states(self, thread_id: str) -> list[tuple[str, str]]:
        """Recent turn ids and statuses only, without conversation content."""
        response = await self._call('thread/turns/list', {
            'threadId': _native_id(thread_id), 'limit': 5, 'sortDirection': 'desc',
            'itemsView': 'notLoaded',
        })
        return [(turn.get('id'), turn.get('status')) for turn in response.get('data') or []]

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        """Request interruption of a turn this connection did not start."""
        await self._call('turn/interrupt', {'threadId': _native_id(thread_id), 'turnId': _native_id(turn_id)})

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

    def _require_active(
        self, execution: CodexExecution, *, inactive_code: str = 'RUNTIME_LIFECYCLE_INVALID',
    ) -> None:
        """Reject stale active control before sending a native request."""
        self._require_connection()
        self._execution_state(execution)
        if self._active.get(execution.thread_id) != execution.turn_id:
            raise CodexAdapterError(inactive_code, 'The target execution is not active.')

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
            ordered = self._ordered_archives.get(execution.thread_id)
            if ordered is not None:
                await ordered.collect()
        except CodexAdapterError as error:
            result = error
        if isinstance(result, CodexAdapterError):
            if state.terminal and not result.terminal_confirmed:
                raise CodexAdapterError(result.code, result.message) from result
            raise result
        return result.copy()

    async def _collect_native_trace(self, trace: CodexNativeTrace, changed: asyncio.Event) -> None:
        """Collect changed files after notices and retry delayed native writes.

        A notice is a wakeup only, never an ordering source. The bounded file
        check also covers silent writes and notices received before disk flush.
        """

        try:
            while not self._closed:
                trace.collect()
                try:
                    await asyncio.wait_for(changed.wait(), 0.1)
                except TimeoutError:
                    pass
                changed.clear()
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, sqlite3.Error):
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
        except (OSError, ValueError, sqlite3.Error) as error:
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

    async def list_models(self) -> list[dict]:
        """Read the public native catalog without creating a Session or model turn."""
        models = []
        cursor = None
        seen = set()
        while True:
            response = await self._call('model/list', {'cursor': cursor, 'limit': 100})
            models.extend(response['data'])
            cursor = response.get('nextCursor')
            if cursor is None:
                return models
            if cursor in seen:
                raise self._protocol_failure('Repeated model-list cursor.')
            seen.add(cursor)

    async def read_configuration(self, cwd: Path) -> dict[str, Any]:
        """Read effective native configuration without changing any user setting."""
        response = await self._call('config/read', {'cwd': str(cwd), 'includeLayers': False})
        configuration = response.get('config')
        if not isinstance(configuration, dict):
            raise self._protocol_failure('Native configuration response is invalid.')
        return configuration

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

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        """Read native identity and current settings without conversation content."""
        response = await self._call('thread/read', {
            'threadId': _native_id(thread_id), 'includeTurns': False,
        })
        thread = response.get('thread')
        if not isinstance(thread, dict) or thread.get('id') != thread_id:
            raise self._protocol_failure('thread/read returned a different native Session.')
        return thread


    async def inspect_thread_reference(self, reference: str) -> dict[str, Any]:
        """Report metadata returned for a declared storage reference, without asserting identity.

        This diagnostic never authenticates a Session or relaxes read_thread's
        exact-ID contract. It excludes preview text, turns and configuration.
        Callers must not read the returned path merely because it was returned.
        """
        response = await self._call('thread/read', {
            'threadId': _native_id(reference), 'includeTurns': False,
        })
        thread = response.get('thread')
        if not isinstance(thread, dict) or not isinstance(thread.get('id'), str):
            raise self._protocol_failure('Native reference metadata has no Session identity.')
        fields = ('id', 'path', 'cwd', 'sessionId', 'forkedFromId', 'parentThreadId',
                  'historyMode', 'ephemeral', 'source')
        return {key: thread[key] for key in fields
                if key in thread and (thread[key] is None or type(thread[key]) in (str, int, bool))}

    async def subscribe_host(self, thread_id: str) -> dict[str, Any]:
        """Rejoin an already-loaded host to receive its native lifecycle events.

        Codex's public resume operation rejoins a loaded thread. Supply no
        history, settings or input; refuse an unloaded host rather than asking
        to restore it. The server still owns admission and provider checks.
        """
        thread = await self.read_thread(thread_id)
        if thread.get('status', {}).get('type') not in {'active', 'idle'}:
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'The owning host is not loaded and available.')
        response = await self._call('thread/resume', {
            'threadId': _native_id(thread_id), 'excludeTurns': True,
        })
        joined = response.get('thread')
        if not isinstance(joined, dict) or joined.get('id') != thread_id:
            raise self._protocol_failure('Host subscription returned a different native Session.')
        return response

    async def read_hooks(self, cwd: str) -> dict[str, Any]:
        """Read public discovered hook definitions/trust, not private execution history."""
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise self._protocol_failure('Native host cwd is unavailable for hooks/list.')
        return await self._call('hooks/list', {'cwds': [cwd]})

    def drain_notifications(self) -> list[dict[str, Any]]:
        """Return already-received notifications without polling the native host."""
        notices = []
        while not self._notifications.empty():
            notices.append(self._notifications.get_nowait())
        return notices

    async def read_host_status(self, thread_id: str) -> dict[str, Any]:
        """Read host activity and latest turn metadata without conversation items.

        These are successive native observations, not an atomic snapshot.
        Rechecking activity after the turn read avoids treating an earlier idle
        observation as proof that a subsequently active host is still idle.
        """
        response = await self._call('thread/turns/list', {
            'threadId': _native_id(thread_id), 'limit': 1, 'itemsView': 'notLoaded',
        })
        turns = response.get('data')
        if not isinstance(turns, list):
            raise self._protocol_failure('Host turn metadata is unavailable.')
        turn = None
        if turns:
            latest = turns[0]
            if (not isinstance(latest, dict) or not isinstance(latest.get('id'), str)
                    or latest.get('status') not in {'inProgress', 'completed', 'interrupted', 'failed'}):
                raise self._protocol_failure('Invalid host turn metadata.')
            turn = {key: latest[key] for key in ('id', 'status')}
        thread = await self.read_thread(thread_id)
        status = thread.get('status')
        if not isinstance(status, dict) or status.get('type') not in {
            'active', 'idle', 'notLoaded', 'systemError',
        }:
            raise self._protocol_failure('Host activity is unavailable.')
        return {'session': thread_id, 'activity': status['type'], 'turn': turn}

    async def fork_session(
        self,
        parent: dict[str, Any],
        *,
        network_profile: str | None = None,
        unix_socket: str | None = None,
    ) -> CodexSession:
        """Fork native history with the source's current model/provider unchanged.

        The caller binds the returned handle to its actual Main before starting
        execution. Fork lineage is checked, never represented as native parent
        metadata. No private rollout or replacement instructions are supplied.

        Parameters
        ----------
        parent
            Main's thread metadata with its ``configuration`` and ``turn_settings``.
        network_profile, unix_socket
            Supplied together, and only when Main selected a named permission
            profile: the fork selects a profile of this name that extends Main's
            with Codex managed network enabled and ``unix_socket`` allowed. The
            reported ``networkAccess`` is then the only accepted difference
            from Main's sandbox.
        """
        if (network_profile is None) != (unix_socket is None):
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID',
                                    'network_profile and unix_socket are supplied together.')
        if any(not isinstance(parent.get(k), str) or not parent[k]
               for k in ('id', 'model', 'modelProvider')):
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'Main model metadata is unavailable.')
        parameters = {
            'threadId': parent['id'], 'model': parent['model'],
            'modelProvider': parent['modelProvider'],
            # Paginated ephemeral forks reject included history. Unknown modes
            # use the same safe request; only explicit legacy exposes turns.
            'excludeTurns': parent.get('historyMode') != 'legacy',
            'ephemeral': True,
        }
        settings = parent.get('turn_settings', {})
        configuration = parent.get('configuration', {})
        for key in ('serviceTier', 'cwd', 'runtimeWorkspaceRoots', 'approvalPolicy', 'approvalsReviewer'):
            if key in configuration:
                parameters[key] = configuration[key]
        # Native fork does not inherit Main's sandbox. Select Main's named
        # profile or its sandbox mode (never both); the response is checked
        # against Main's full policy below.
        profile = configuration.get('activePermissionProfile')
        if isinstance(profile, dict) and isinstance(profile.get('id'), str) and network_profile:
            # Main's own profile with Codex managed network enabled, so the
            # fork can reach the caller's socket. The socket entry is not a
            # limit: other Unix sockets and loopback TCP stay reachable under
            # managed network.
            parameters['permissions'] = network_profile
            # A root permissions override replaces Main's named profiles.
            # Override only the fork's entry so its parent remains resolvable.
            parameters['config'] = {'permissions.' + network_profile: {
                'extends': profile['id'],
                'network': {'enabled': True, 'unix_sockets': {unix_socket: 'allow'}},
            }}
        elif isinstance(profile, dict) and isinstance(profile.get('id'), str):
            parameters['permissions'] = profile['id']
        elif 'sandbox' in configuration:
            policy = configuration['sandbox']
            mode = _SANDBOX_MODES.get(policy.get('type')) if isinstance(policy, dict) else None
            if mode is None:
                raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'Main sandbox has no fork selection.')
            parameters['sandbox'] = mode
        # Native fork rebuilds model config. Preserve the checked turn's
        # observed effort instead of project defaults.
        if 'effort' in settings:
            parameters.setdefault('config', {})['model_reasoning_effort'] = settings['effort']
        response = await self._call('thread/fork', parameters)
        thread = response.get('thread')
        if (not isinstance(thread, dict) or not isinstance(thread.get('id'), str)
                or not thread['id'] or thread['id'] == parent['id']
                or thread['id'] in self._sessions
                or thread.get('ephemeral') is not True
                or thread.get('forkedFromId') != parent['id']
                or response.get('model') != parent['model']
                or response.get('modelProvider') != parent['modelProvider']):
            raise self._protocol_failure('thread/fork did not preserve the bound source and model.')
        if 'effort' in settings and response.get('reasoningEffort') != settings['effort']:
            raise self._protocol_failure('thread/fork changed the checked turn reasoning effort.')
        for key in ('serviceTier', 'cwd', 'runtimeWorkspaceRoots', 'approvalPolicy', 'approvalsReviewer'):
            if key in configuration and response.get(key) != configuration[key]:
                raise self._protocol_failure(f'thread/fork changed Main {key}.')
        # The effective policy decides; a profile name is checked only when
        # Main selected one, since an unnamed policy may be reported by name.
        # The only authorized difference is the managed network access.
        ignored = ({'networkAccess'} if network_profile and parameters.get('permissions') == network_profile
                   else set())
        if 'sandbox' in configuration and (
                not isinstance(response.get('sandbox'), dict)
                or {k: v for k, v in response['sandbox'].items() if k not in ignored}
                != {k: v for k, v in configuration['sandbox'].items() if k not in ignored}):
            raise self._protocol_failure('thread/fork changed Main sandbox.')
        if 'permissions' in parameters and (
                not isinstance(response.get('activePermissionProfile'), dict)
                or response['activePermissionProfile'].get('id') != parameters['permissions']):
            raise self._protocol_failure('thread/fork changed Main permission profile.')
        path = thread.get('path')
        rollout = Path(path) if isinstance(path, str) and Path(path).is_absolute() else None
        # Keep native configuration facts, not inherited conversation or previews.
        facts = {key: response[key] for key in (
            'model', 'modelProvider', 'serviceTier', 'cwd', 'runtimeWorkspaceRoots',
            'approvalPolicy', 'approvalsReviewer', 'sandbox', 'activePermissionProfile',
            'reasoningEffort', 'instructionSources', 'disabledPluginIds',
        ) if key in response}
        facts['thread'] = {key: thread[key] for key in (
            'id', 'sessionId', 'forkedFromId', 'ephemeral', 'historyMode', 'cliVersion',
        ) if key in thread}
        turn_settings = {}
        if settings.get('collaboration_mode') is not None:
            turn_settings['collaborationMode'] = settings['collaboration_mode']
        session = CodexSession(thread['id'], rollout, facts, turn_settings, thread,
                               inherited_history_excluded=parameters['excludeTurns'])
        self._sessions[session.thread_id] = session
        return session

    def retain_fork_archive(self, session: CodexSession, archive: Any) -> None:
        """Archive an owned ephemeral fork at its actual native inheritance cut."""
        self._require_session(session)
        if session.inherited_history is None or session.thread_id in self._fork_archives:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'A new native fork is required.')
        archive.seed_fork(session.inherited_history, history_excluded=session.inherited_history_excluded)
        self._fork_archives[session.thread_id] = archive

    async def retain_ordered_history(
        self, session: CodexSession, create_collector: Callable[[], Any],
    ) -> None:
        """Capture the owned child's inheritance cut before its first model call."""
        self._require_session(session)
        if session.thread_id in self._ordered_archives:
            raise CodexAdapterError('RUNTIME_LIFECYCLE_INVALID', 'History is already retained.')
        collector = create_collector()
        self._ordered_archives[session.thread_id] = collector
        await collector.collect()

    async def is_current_turn(self, session: str, turn: str) -> bool:
        """Check the exact live turn without loading dialogue or execution items."""
        thread = await self.read_thread(session)
        if thread.get('status', {}).get('type') != 'active':
            return False
        response = await self._call('thread/turns/list', {
            'threadId': session, 'limit': 1, 'itemsView': 'notLoaded',
        })
        turns = response.get('data')
        if not isinstance(turns, list) or not turns or not isinstance(turns[0], dict):
            raise self._protocol_failure('The active Main turn could not be verified.')
        return turns[0].get('id') == turn and turns[0].get('status') == 'inProgress'

    def token_usage(self, session: CodexSession) -> dict[str, Any] | None:
        """Return only usage actually delivered by the native host, if available."""
        self._require_session(session)
        usage = self._token_usage.get(session.thread_id)
        return json.loads(json.dumps(usage)) if usage is not None else None

    @property
    def notifications_pending(self) -> bool:
        """Whether received notifications still wait for their consumer."""
        return not self._notifications.empty()

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
        if self._process is None and self._remote_socket is None:
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

    async def call(
        self, method: str, params: dict[str, Any] | None, *, wait_for_session: bool = False,
    ) -> dict[str, Any]:
        """Send one native JSON-RPC request and return its result."""
        return await self._call(method, params, wait_for_session=wait_for_session)

    async def _call(
        self, method: str, params: dict[str, Any] | None, *, wait_for_session: bool = False,
    ) -> dict[str, Any]:
        """Correlate a client request while the reader consumes interleaved events."""
        self._require_connection()
        self._sequence += 1
        request_id = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        written = False
        try:
            async with asyncio.timeout(self._timeout) as deadline:
                await self._send({'id': request_id, 'method': method, 'params': params})
                written = True
                # Loading a Session is native work, not a transport deadline.
                # Keep writes bounded; caller cancellation/close still wakes
                # this owner, while ordinary control RPCs retain their limit.
                if wait_for_session:
                    deadline.reschedule(None)
                response = await asyncio.shield(future)
        except TimeoutError as error:
            failure = CodexAdapterError(
                'RUNTIME_TIMEOUT',
                f'Codex {method} request {request_id} timed out; close this connection.',
                terminal_confirmed=False,
            )
            # The host may already have applied a written request.
            failure.request_written = written
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
            # The connection failed after this request was written.
            response.request_written = written
            raise response
        if 'error' in response:
            raise CodexRPCError(method, request_id, response['error'])
        self._require_connection()
        return response['result']

    async def _send(self, message: dict[str, Any]) -> None:
        """Write JSONL for stdio services or a Text message for daemon proxies."""
        self._require_connection()
        from websockets.exceptions import ConnectionClosed
        try:
            encoded = json.dumps(message, allow_nan=False)
            if self._remote_socket is not None:
                await self._remote_socket.send(encoded)
            elif self._websocket is not None:
                await self._websocket.send(encoded)
            else:
                assert self._process is not None and self._process.stdin is not None
                self._process.stdin.write((encoded + '\n').encode())
                await self._process.stdin.drain()
        except (OSError, ValueError, TypeError, ConnectionClosed) as error:
            failure = CodexAdapterError('RUNTIME_CONNECTION_FAILED', f'Writing Codex stdio failed: {error}',
                                        terminal_confirmed=False)
            self._fail(failure)
            raise failure from error

    async def _read(self) -> None:
        """Consume responses and native completion notifications asynchronously."""
        try:
            messages = self._remote_socket if self._remote_socket is not None else (
                self._websocket.messages() if self._websocket is not None
                else self._process.stdout
            )
            async for line in messages:
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
            archive = self._fork_archives.get(message['params'].get('threadId'))
            thread_id = message['params'].get('threadId')
            ordered = self._ordered_archives.get(thread_id)
            if ordered is not None and ('id' in message or message['method'] in {
                'serverRequest/resolved', 'item/completed', 'turn/completed', 'thread/compacted',
            }):
                ordered.transport(message)
            if ordered is not None and message['method'] in {'turn/completed', 'thread/compacted'}:
                pending = self._ordered_tasks.get(thread_id)
                if pending is None or pending.done():
                    self._ordered_tasks[thread_id] = asyncio.create_task(ordered.collect())
            changed = self._trace_changes.get(message['params'].get('threadId'))
            if changed is not None:
                changed.set()
            if archive is not None:
                archive.notice(message)
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
            elif message['method'] == 'model/rerouted':
                self.reroutes[(_native_id(params['threadId']), _native_id(params['turnId']))] = dict(params)
            elif message['method'] == 'turn/completed':
                self._complete(_native_id(params['threadId']), _native_turn(params['turn']))
            elif message['method'] == 'thread/tokenUsage/updated':
                if isinstance(params.get('tokenUsage'), dict):
                    self._token_usage[_native_id(params['threadId'])] = params['tokenUsage']
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
                reply = {'id': request.request_id, 'result': result}
                archive = self._fork_archives.get(request.params.get('threadId'))
                if archive is not None:
                    archive.reply(reply)
                ordered = self._ordered_archives.get(request.params.get('threadId'))
                if ordered is not None:
                    ordered.transport(reply, outbound=True)
                await self._send(reply)
            else:
                scoped = all(isinstance(value, str) and value for value in key)
                if scoped:
                    state = self._turns.setdefault(key, _ExecutionState())
                    if not state.result.done():
                        state.result.set_result(failure)
                reply = {'id': request.request_id, 'error': {
                    'code': -32601 if failure.code == 'RUNTIME_REQUEST_UNHANDLED' else -32603,
                    'message': failure.message,
                }}
                archive = self._fork_archives.get(request.params.get('threadId'))
                if archive is not None:
                    archive.reply(reply)
                ordered = self._ordered_archives.get(request.params.get('threadId'))
                if ordered is not None:
                    ordered.transport(reply, outbound=True)
                await self._send(reply)
                if not scoped:
                    self._fail(failure)
        except CodexAdapterError as error:
            self._fail(error)
        except (OSError, ValueError, sqlite3.Error):
            self._fail(CodexAdapterError(
                'RUNTIME_TRACE_FAILED', 'The native Codex reply could not be retained.',
                terminal_confirmed=False,
            ))
