"""Connect the background Runner owner to the production native Session Adapter."""

from __future__ import annotations

import asyncio
import os
import json
import re
import sys
import uuid
from concurrent.futures import CancelledError
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

import yaml

from agent_swarm.runtime import RuntimeAdapterError
from .app_server import CodexAppServer, CodexExecution, CodexServerRequest
from .context import restore_codex_context, recovery_environment


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
        session_created: Callable[[str, int], None] | None = None,
        *,
        connection: dict[str, str] | None = None,
        agent_call: Callable | None = None,
    ) -> None:
        """Capture immutable task configuration for one Worker execution."""
        self.context = restore_codex_context(request, context_evidence)
        self.connection_environment = recovery_environment(connection or {})
        request = self.context.launch_document()['adapter_request']
        request['session_parameters'].pop('dynamicTools', None)
        self.context = restore_codex_context(request, context_evidence)
        self.approval_items: dict[str, dict] = {}
        self.command = (request['arguments'][0], 'app-server', '--listen', 'stdio://')
        if request['session_parameters']['config'].get('features', {}).get('network_proxy'):
            # The owning service must enable the proxy before creating or
            # resuming the thread that selects its scoped socket permissions.
            self.command += ('-c', 'features.network_proxy=true')
        self.prompt = prompt
        self.directory = session_directory
        self.trace_file = trace_file
        self.started = session_started
        self.created = session_created
        self.agent_call = agent_call
        self.parent_notice: Callable[[str, dict], dict] | None = None
        self.expected_session = expected_session
        self.termination_requested = False
        self.execution: CodexExecution | None = None
        self.native_session: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.adapter: CodexAppServer | None = None
        self.result: asyncio.Task | None = None
        self.startup: asyncio.Task | None = None
        self.operations: set[asyncio.Task] = set()
        self.outcome: dict | None = None
        self.requests: dict[str, tuple[CodexServerRequest, asyncio.Future[dict]]] = {}
        self.recovery_requests: dict[str, tuple[dict, asyncio.Future[dict]]] = {}

    @property
    def session(self) -> str | None:
        """Expose the native Session through the shared RuntimeTurn interface."""
        return self.native_session

    @property
    def execution_id(self) -> str | None:
        """Expose native execution identity without leaking the Codex handle."""
        return self.execution.turn_id if self.execution is not None else None

    def run(self) -> dict:
        """Run native control on one loop while the Worker accepts local calls."""
        return asyncio.run(self._run())

    async def _run(self) -> dict:
        """Retain identity from the Session handle and outcomes from native turns."""
        self.loop = asyncio.get_running_loop()
        connections = ExitStack()
        request = self.context.launch_document()['adapter_request']
        cwd = Path(request['worktree_path'])
        config = request['session_parameters']['config']
        address, connection_env, entry = self._bind_connection(connections, request, cwd)
        if address is not None:
            profile = config['permissions'][config['default_permissions']]
            profile['filesystem'][address] = 'write'
            shell = config.setdefault('shell_environment_policy', {}).setdefault('set', {})
            shell[connection_env] = address
            shell['GRAPHTRAJ_NATIVE_RUNTIME'] = 'codex'
            # A Task host serves agents and tasks itself; an independent one only agents.
            config.setdefault('mcp_servers', {})['graphtraj'] = {
                'command': sys.executable, 'args': ['-m', entry], 'cwd': str(cwd),
                'env': {connection_env: address, 'GRAPHTRAJ_NATIVE_RUNTIME': 'codex'},
            }
            self.context = restore_codex_context(request, self.context.evidence_document())
        adapter = CodexAppServer(cwd=Path(self.context.session_document()['adapter_request']['cwd']),
                                 command=self.command, request_timeout=5,
                                 environment={**self.context.runtime_environment(), **self.connection_environment,
                                              'AGENT_SWARM_CONNECTION': None, 'GRAPHTRAJ_CLI_CONNECTION': None},
                                 on_request=self._request, request_handler_timeout=None,
                                 experimental_api=True)
        self.adapter = adapter
        observer = None
        phase = 'initialize'
        try:
            async with adapter:
                phase = 'thread/resume' if self.expected_session else 'thread/start'
                observer = asyncio.create_task(self._observe())
                if self.termination_requested:
                    raise RuntimeAdapterError(
                        'RUNTIME_EXECUTION_INTERRUPTED', 'Stopped before native Session creation.',
                    )
                # Resume itself can append settings. Capture the owned source
                # boundary before that operation, not after its response.
                resume_source = None
                retained = self.directory / 'session.yml'
                if self.expected_session and retained.is_file():
                    previous = yaml.safe_load(retained.read_text())
                    if previous.get('session') == self.expected_session and previous.get('rollout_path'):
                        path = Path(previous['rollout_path'])
                        try:
                            resume_source = (path, path.stat().st_size)
                        except FileNotFoundError:
                            pass
                self.startup = asyncio.create_task(
                    adapter.resume_session(self.context, self.expected_session)
                    if self.expected_session else adapter.create_session(self.context)
                )
                try:
                    session = await self.startup
                except asyncio.CancelledError:
                    if not self.termination_requested:
                        raise
                    raise RuntimeAdapterError(
                        'RUNTIME_EXECUTION_INTERRUPTED', 'Stopped during native Session creation.',
                        terminal_confirmed=False,
                    ) from None
                finally:
                    self.startup = None
                self.native_session = session.thread_id
                permissions = self.permission_evidence(session.configuration)
                self._write_session({
                    'session': session.thread_id,
                    'rollout_path': str(session.rollout_path) if session.rollout_path else None,
                    'permissions': permissions,
                })
                if self.created is not None:
                    self.created(session.thread_id, adapter.service_pid)
                if permissions['matches_request'] is False:
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                              'Codex did not confirm the requested approvals reviewer.')
                archive = self._archive(session)
                if archive is not None and resume_source is not None:
                    if session.rollout_path == resume_source[0]:
                        archive.activation = resume_source[1]
                adapter.retain_native_trace(session, self.trace_file, archive=archive)
                if self.termination_requested:
                    raise RuntimeAdapterError(
                        "RUNTIME_EXECUTION_INTERRUPTED", "Stopped before native execution started.",
                        terminal_confirmed=True,
                    )
                self.execution = await adapter.start_execution(session, self.prompt)
                if self.termination_requested:
                    self.terminate()
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
            message = error.message
            if self.native_session is None:
                # Match Pi's startup-only diagnostic boundary and redaction;
                # never publish task output or earlier executions' stderr.
                diagnostic = adapter.stderr_tail
                for name, value in os.environ.items():
                    if value and any(part in name.upper() for part in (
                        'KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL',
                    )):
                        diagnostic = diagnostic.replace(value, '[REDACTED]')
                diagnostic = re.sub(r'(?i)(bearer\s+)[^\s"\']+', r'\1[REDACTED]', diagnostic)
                diagnostic = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', diagnostic)
                diagnostic = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[REDACTED]', diagnostic)
                message = f'Codex {phase}: {message}'
                if diagnostic.strip():
                    message += '\nStartup stderr: ' + diagnostic.strip()[-4096:]
            raise RuntimeAdapterError(error.code, message) from error
        finally:
            await asyncio.to_thread(connections.close)
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
                if notification['method'] in {'item/started', 'item/completed'}:
                    item = notification.get('params', {}).get('item', {})
                    if isinstance(item.get('id'), str):
                        self.approval_items[item['id']] = item
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
            pending = self.recovery_requests.get(request['request_token'])
            if pending is not None:
                details, response = pending
                if response.done() or self.result.done():
                    raise RuntimeAdapterError('operation-failed', 'Recovery review is no longer pending.')
                decision = request['response']
                if decision not in ({'decision': 'accept'}, {'decision': 'decline'}):
                    raise RuntimeAdapterError('invalid-input', 'Return an explicit accept or decline decision.')
                response.set_result(decision)
                return {'request_id': details['request_id'], 'reply_status': 'submitted'}
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
        tool = request.params.get('tool')
        if request.method == 'item/tool/call' and (
            tool in {'graphtraj', 'agents', 'tasks'} or isinstance(tool, str) and tool.startswith('graphtraj_')
        ):
            # A retained Session may still advertise its old dynamic tool set.
            # Do not execute it or turn an obsolete tool call into a human prompt.
            return {'success': False, 'contentItems': [{'type': 'inputText',
                    'text': 'This project tool registration was removed. Use the agents/tasks MCP entry.'}]}
        mcp_approval = (
            request.method == 'mcpServer/elicitation/request'
            and request.params.get('mode') == 'form'
            and isinstance(request.params.get('_meta'), dict)
            and request.params['_meta'].get('codex_approval_kind') == 'mcp_tool_call'
        )
        if self._uses_review() and (request.method.endswith("/requestApproval") or mcp_approval):
            return await self._review_approval(request)
        token = uuid.uuid4().hex
        response = asyncio.get_running_loop().create_future()
        self.requests[token] = (request, response)
        try:
            notification = asyncio.create_task(self._notify_direct_parent(request, token))
            return await response
        finally:
            notification.cancel()
            await asyncio.gather(notification, return_exceptions=True)
            self.requests.pop(token, None)

    def _authenticate_mcp(self, pid: int) -> None:
        """Reject calls before the native service owns the process connection."""
        from agent_swarm import AgentsError

        if self.adapter is None:
            raise AgentsError('authority-denied', 'The Codex service has not started.')
        self.adapter.authenticate_caller(pid)


    async def _notify_direct_parent(self, request: CodexServerRequest, token: str) -> None:
        """Tell the recorded direct parent about this request before the turn waits.

        The notice reaches the parent's own execution through the parent's
        control channel; a parent that is busy or waiting receives it as input
        in the Session and execution it already holds. The notice announces the
        request for the parent's native approval reply and never answers it, so
        this execution keeps waiting for the response either way.
        """
        # The request names its own native execution: it can arrive before
        # start_execution returns this Worker the handle it retains.
        session = request.params.get("threadId")
        execution_id = request.params.get("turnId")
        notice = (
            "Direct child notice: Session {0} waits for your decision on native "
            "request {1} ({2}) in execution {3}. Reply through the existing "
            "reply entry for that request when you decide; receiving this "
            "notice neither approves nor declines it.".format(
                session, request.request_id, request.method, execution_id,
            )
        )
        identity = {
            "request_id": request.request_id, "method": request.method,
            "request_token": token, "session": session,
            "execution_id": execution_id,
        }
        notice += "\n" + json.dumps({**identity, "params": request.params}, ensure_ascii=False)
        while token in self.requests and not self.requests[token][1].done():
            receipt = await asyncio.to_thread(
                self.parent_notice, notice, identity,
            ) if self.parent_notice is not None else {"delivery": "no-direct-parent"}
            if receipt["delivery"] in {"received", "retained", "no-direct-parent"}:
                return
            # Retry only while the original native request is still pending.
            await asyncio.sleep(1)


    def permission_evidence(self, observed: dict) -> dict:
        """Distinguish the requested reviewer and its source from Codex's startup report."""
        params = self.context.session_document()['adapter_request']
        requested = params.get('approvalsReviewer', params.get('config', {}).get('approvals_reviewer'))
        selection = self.context.evidence_document().get('approvals_reviewer') or {}
        actual = observed.get('approvalsReviewer')
        return {
            'requested': requested,
            'source': 'role' if self._uses_review() else selection.get('source', 'unknown'),
            'observed': actual if isinstance(actual, str) else 'unknown',
            'observed_source': 'thread/start' if isinstance(actual, str) else 'unknown',
            'approval_policy': observed.get('approvalPolicy'),
            'matches_request': None if requested is None or not isinstance(actual, str) else requested == actual,
        }

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
        ] + [details for details, response in self.recovery_requests.values() if not response.done()]

    def terminate(self) -> bool:
        """Schedule native interruption for a Worker termination/budget signal."""
        self.termination_requested = True
        if self.loop is None or self.loop.is_closed():
            return False
        if self.execution is None:
            def cancel_startup() -> None:
                """Cancel only pending Session loading, leaving shutdown owned."""
                if self.startup is not None:
                    self.startup.cancel()
            self.loop.call_soon_threadsafe(cancel_startup)
            return True
        async def interrupt() -> None:
            """Observe signal-driven cancellation errors without inferring an outcome."""
            try:
                assert self.adapter is not None and self.execution is not None
                await self.adapter.interrupt(self.execution)
            except RuntimeAdapterError:
                pass
        self.loop.call_soon_threadsafe(lambda: asyncio.create_task(interrupt()))
        return True

    def _uses_review(self) -> bool:
        """Native approval is handled by Codex unless a consumer provides a reviewer."""
        return False

    def _write_session(self, document: dict) -> None:
        """Atomically retain native identity before reporting Session creation."""
        import tempfile

        path = self.directory / 'session.yml'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(yaml.safe_dump(document).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _archive(self, session: object) -> object | None:
        """No collector is required for native control; consumers bind their own."""
        return None

    def _bind_connection(self, connections: ExitStack, request: dict, cwd: Path) -> tuple:
        """Expose agents only to the owned native process and Session."""
        from agent_swarm.connection import CONNECTION_ENV, agents_connection

        if self.agent_call is None:
            return None, None, None
        native_context = lambda: {'runtime': 'codex', 'session': self.native_session, 'cwd': str(cwd)}
        address = connections.enter_context(agents_connection(
            self.directory / 'mcp', self.agent_call, self._authenticate_mcp,
            native_context=native_context,
        ))
        return address, CONNECTION_ENV, 'agent_swarm.mcp'
