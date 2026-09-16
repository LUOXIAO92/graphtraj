"""Connect the background Runner owner to the production native Session Adapter."""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable

from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexExecution, CodexServerRequest
from graphtraj.runtimes.codex.codex_adapter import restore_codex_context
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


class CodexManagedExecution:
    """Hold a connection until its execution and final Trace drain finish."""

    def __init__(
        self,
        request: dict,
        prompt: str,
        session_directory: Path,
        session_started: Callable[[str, int], None],
        context_evidence: dict,
        trace_file: Path,
        expected_session: str | None = None,
    ) -> None:
        """Capture immutable task configuration for one Worker execution."""
        self.context = restore_codex_context(request, context_evidence)
        self.command = (request['arguments'][0], 'app-server', '--listen', 'stdio://')
        self.prompt = prompt
        self.directory = session_directory
        self.trace_file = trace_file
        self.started = session_started
        self.expected_session = expected_session
        self.execution: CodexExecution | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.adapter: CodexAppServer | None = None
        self.result: asyncio.Task | None = None
        self.operations: set[asyncio.Task] = set()
        self.outcome: dict | None = None
        self.requests: dict[str, tuple[CodexServerRequest, asyncio.Future[dict]]] = {}

    def run(self) -> dict:
        """Run native control on one loop while the Worker accepts local calls."""
        return asyncio.run(self._run())

    async def _run(self) -> dict:
        """Retain identity from the Session handle and outcomes from native turns."""
        self.loop = asyncio.get_running_loop()
        adapter = CodexAppServer(cwd=Path(self.context.session_document()['adapter_request']['cwd']),
                                 command=self.command, request_timeout=5,
                                 on_request=self._request, request_handler_timeout=None)
        self.adapter = adapter
        observer = None
        try:
            async with adapter:
                observer = asyncio.create_task(self._observe())
                session = (
                    await adapter.resume_session(self.context, self.expected_session)
                    if self.expected_session else await adapter.create_session(self.context)
                )
                write_yaml_durably(self.directory / 'session.yml', {
                    'session': session.thread_id,
                    'rollout_path': str(session.rollout_path) if session.rollout_path else None,
                })
                adapter.retain_native_trace(session, self.trace_file)
                self.execution = await adapter.start_execution(session, self.prompt)
                self.result = asyncio.create_task(adapter.wait(self.execution))
                self.started(session.thread_id, adapter.service_pid)
                try:
                    result = await self.result
                    self.outcome = result
                except RuntimeAdapterError as error:
                    with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                        stream.write(error.code + ': ' + error.message + '\n')
                    result = {
                        'outcome': 'runtime-error', 'session_id': session.thread_id,
                        'execution_id': self.execution.turn_id,
                        'error': {'code': error.code, 'message': error.message},
                    }
                    if error.terminal_confirmed:
                        self.outcome = result
                finally:
                    while self.operations:
                        await asyncio.sleep(0.01)
            self.outcome = result
            return result
        except RuntimeAdapterError as error:
            # The context manager has reaped this Worker's service even when a
            # startup RPC failed. Keep a shutdown failure explicitly unconfirmed.
            if error.code == 'RUNTIME_SHUTDOWN_FAILED':
                raise
            raise RuntimeAdapterError(error.code, error.message) from error
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
            with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                stream.write(adapter.stderr_tail)

    async def _observe(self) -> None:
        """Drain control notifications for diagnostics separately from native records."""
        assert self.adapter is not None
        try:
            while True:
                notification = await self.adapter.next_notification()
                if notification['method'] == 'error':
                    with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(notification) + '\n')
        except RuntimeAdapterError:
            return

    def operate(self, request: dict) -> dict:
        """Schedule a targeted control request from the Worker's local server."""
        execution = self.execution
        if execution is None or (
            request.get('session'), request.get('execution_id')
        ) != (execution.thread_id, execution.turn_id):
            raise RuntimeAdapterError('operation-failed', 'The requested native execution is not owned.')
        if request.get('operation') == 'status' and self.outcome is not None:
            return {'activity': 'idle', 'last_outcome': self.outcome['outcome']}
        if request.get('operation') == 'requests' and self.outcome is not None:
            return {'requests': []}
        if self.outcome is not None or self.loop is None or self.loop.is_closed():
            raise RuntimeAdapterError('operation-failed', 'The execution is no longer active.')
        try:
            return asyncio.run_coroutine_threadsafe(self._control(request), self.loop).result(timeout=10)
        except (CancelledError, RuntimeError) as error:
            raise RuntimeAdapterError('operation-failed', 'The execution owner has closed.') from error

    async def _control(self, request: dict) -> dict:
        """Keep acknowledged operations owned through a native completion race."""
        task = asyncio.current_task()
        self.operations.add(task)
        try:
            return await self._operate(request)
        finally:
            self.operations.remove(task)

    async def _operate(self, request: dict) -> dict:
        """Use the retained execution handle; never steer or cancel by service PID."""
        execution = self.execution
        if execution is None or (
            request.get('session'), request.get('execution_id')
        ) != (execution.thread_id, execution.turn_id):
            raise RuntimeAdapterError('operation-failed', 'The requested native execution is not owned.')
        assert self.adapter is not None and self.result is not None
        if request['operation'] == 'status':
            if self.outcome is not None:
                return {'activity': 'idle', 'last_outcome': self.outcome['outcome']}
            return {'activity': 'running', **(
                {'waiting_for': 'runtime-request'} if self._pending_requests() else {}
            )}
        if request['operation'] == 'requests':
            return {'requests': self._pending_requests() if not self.result.done() else []}
        if request['operation'] == 'reply':
            pending = self.requests.get(request['request_token'])
            if pending is None or pending[1].done() or self.result.done():
                raise RuntimeAdapterError('operation-failed', 'The native request is no longer pending.')
            native, response = pending
            response.set_result(request['response'])
            return {'request_id': native.request_id, 'reply_status': 'submitted'}
        if request['operation'] == 'send':
            await self.adapter.send_input(execution, request['instruction'])
        elif request['operation'] == 'interrupt':
            await self.adapter.interrupt(execution)
            result = await self.adapter.wait(execution)
            if result['outcome'] != 'interrupted':
                raise RuntimeAdapterError('operation-failed', 'Interruption was not confirmed.')
        else:
            raise RuntimeAdapterError('invalid-input', 'Unknown Session operation.')
        return {}

    async def _request(self, request: CodexServerRequest) -> dict:
        """Hold one native callback until an explicit reply or native cancellation."""
        token = uuid.uuid4().hex
        response = asyncio.get_running_loop().create_future()
        self.requests[token] = (request, response)
        try:
            return await response
        finally:
            self.requests.pop(token, None)

    def _pending_requests(self) -> list[dict]:
        """Snapshot native contents with the identity of this execution's owner."""
        assert self.execution is not None
        return [
            {
                'session': self.execution.thread_id, 'execution_id': self.execution.turn_id,
                'request_token': token, 'request_id': native.request_id,
                'method': native.method, 'params': native.params,
            }
            for token, (native, response) in self.requests.items() if not response.done()
        ]

    def terminate(self) -> bool:
        """Schedule native interruption for a Worker termination/budget signal."""
        if self.loop is None or self.execution is None or self.loop.is_closed():
            return False
        async def interrupt() -> None:
            """Observe signal-driven cancellation errors without inferring an outcome."""
            try:
                assert self.adapter is not None and self.execution is not None
                await self.adapter.interrupt(self.execution)
            except RuntimeAdapterError:
                pass
        self.loop.call_soon_threadsafe(lambda: asyncio.create_task(interrupt()))
        return True
