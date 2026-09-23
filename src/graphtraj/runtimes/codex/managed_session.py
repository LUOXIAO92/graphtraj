"""Connect the background Runner owner to the production native Session Adapter."""

from __future__ import annotations

import asyncio
import copy
import os
import json
import uuid
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable

import yaml

from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.runtimes.codex.approval import approval_route, review_request

from graphtraj.execution.runner_control import notify_direct_parent
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexExecution, CodexServerRequest
from graphtraj.runtimes.codex.codex_adapter import restore_codex_context
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def refresh_approval_route(request: dict, session_directory: Path) -> None:
    """Reload only approval routing for the mapped role, preserving work settings."""
    config = request.get('session_parameters', {}).get('config', {})
    if config.get('model_provider', 'openai') == 'openai':
        request.pop('approval', None)
        return
    root = os.environ.get('GRAPHTRAJ_HARNESS_ROOT')
    if not root:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Harness root is required to refresh codex.approval.')
    mapping = yaml.safe_load((session_directory / 'mapping.yml').read_text(encoding='utf-8'))
    roles = load_project_roles(Path(root))
    settings = roles.presets[roles.resolve(mapping.get('role_reference') or mapping['role'])]
    request['approval'] = approval_route(settings.codex, custom=True)
    config['approvals_reviewer'] = 'user'
    request['session_parameters']['approvalsReviewer'] = 'user'
    arguments = request['arguments']
    for index in range(len(arguments) - 2, -1, -1):
        if arguments[index] == '-c' and arguments[index + 1].startswith('approvals_reviewer='):
            del arguments[index:index + 2]
    arguments[2:2] = ['-c', 'approvals_reviewer="user"']


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
        request = copy.deepcopy(request)
        if expected_session:
            refresh_approval_route(request, session_directory)
        self.context = restore_codex_context(request, context_evidence)
        self.approval = request.get("approval")
        self.approval_items: dict[str, dict] = {}
        self.command = (request['arguments'][0], 'app-server', '--listen', 'stdio://')
        self.prompt = prompt
        self.directory = session_directory
        self.trace_file = trace_file
        self.started = session_started
        self.expected_session = expected_session
        self.execution: CodexExecution | None = None
        self.native_session: str | None = None
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
                                 on_request=self._request, request_handler_timeout=None,
                                 experimental_api=True)
        self.adapter = adapter
        observer = None
        try:
            async with adapter:
                observer = asyncio.create_task(self._observe())
                session = (
                    await adapter.resume_session(self.context, self.expected_session)
                    if self.expected_session else await adapter.create_session(self.context)
                )
                self.native_session = session.thread_id
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
        if request.method == 'item/tool/call' and request.params.get('tool') == 'graphtraj_status':
            return await self._native_status(request)
        if self.approval is not None and request.method.endswith("/requestApproval"):
            return await self._review_approval(request)
        token = uuid.uuid4().hex
        response = asyncio.get_running_loop().create_future()
        self.requests[token] = (request, response)
        try:
            await self._notify_direct_parent(request, token)
            return await response
        finally:
            self.requests.pop(token, None)

    async def _native_status(self, request: CodexServerRequest) -> dict:
        """Apply existing status visibility to the Runtime-authenticated issuer."""
        from graphtraj.execution.runner_models import RunnerError, StatusResponse
        from graphtraj.execution.runner_status import runtime_caller, status_aliases
        from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory

        try:
            thread = request.params.get('threadId')
            arguments = request.params.get('arguments')
            if (
                not isinstance(thread, str) or not thread
                or self.native_session is None or self.adapter is None
                or not isinstance(arguments, dict) or set(arguments) != {'aliases'}
                or not isinstance(arguments['aliases'], list) or not arguments['aliases']
                or any(not isinstance(alias, str) for alias in arguments['aliases'])
            ):
                raise RunnerError('invalid-input', 'Supply only the target aliases.')
            current: str | None = thread
            seen: set[str] = set()
            while current != self.native_session:
                if current in seen:
                    raise RunnerError('authority-denied', 'Native parent chain is cyclic.')
                seen.add(current)
                current = await self.adapter.read_thread_parent(current)
                if current is None:
                    raise RunnerError('authority-denied', 'Native caller is outside this Session subtree.')
            identity = self.directory.name if thread == self.native_session else thread
            cwd = Path(self.context.session_document()['adapter_request']['cwd'])
            root = discover_project_root(cwd)

            def observe() -> StatusResponse:
                """Reuse the public operation without authorizing from process ancestry."""
                with runtime_caller(discover_runner_directory(root), identity):
                    return status_aliases(arguments['aliases'], root)

            response = await asyncio.to_thread(observe)
            document, success = response.document, response.succeeded
        except (RunnerError, RuntimeAdapterError) as error:
            document, success = {'error': {'code': error.code, 'message': error.message}}, False
        return {
            'contentItems': [{'type': 'inputText', 'text': json.dumps(document)}],
            'success': success,
        }

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
        await asyncio.to_thread(
            notify_direct_parent, self.directory, notice, {
                "request_id": request.request_id, "method": request.method,
                "request_token": token, "session": session,
                "execution_id": execution_id,
            },
        )

    async def _review_approval(self, request: CodexServerRequest) -> dict:
        """Review this request and return its native response without a separate log."""
        if request.method not in {
            'item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
            'item/permissions/requestApproval',
        }:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unsupported automatic approval request.')
        available = request.params.get('availableDecisions')
        # Codex 0.154.0 normally offers Abort (wire: cancel), not Declined.
        # Preserve the offered denial's continue/interrupt semantics.
        deny = next((value for value in ('decline', 'cancel')
                     if available is None or value in available), None)
        if deny is None:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Approval request has no supported deny decision.')
        decisions = {'decline': deny}
        if available is None or 'accept' in available:
            decisions['accept'] = 'accept'
        allowed = [value for value in ('accept', 'decline') if value in decisions]
        params = self.context.session_document()['adapter_request']
        context = {
            'request_id': request.request_id, 'method': request.method,
            'request': request.params, 'allowed_decisions': allowed,
            'native_decisions': decisions,
            'authorization': self.prompt,
            'developer_instructions': params['developerInstructions'],
            'permissions': params['config'].get('permissions'),
            'default_permissions': params['config'].get('default_permissions'),
            'item': self.approval_items.get(request.params.get('itemId')),
        }
        context.update(self._approval_context())
        if request.method == 'item/fileChange/requestApproval' and not context['item']:
            raise RuntimeAdapterError(
                'RUNTIME_REQUEST_FAILED', 'File changes are not available for review.',
                terminal_confirmed=False,
            )
        result = await review_request(self.approval, context)
        if request.method == 'item/permissions/requestApproval':
            # Return only the exact requested profile; omitted scope uses Codex's
            # native default (turn). A denial grants nothing, only after review.
            return {'permissions': (
                request.params['permissions'] if result['decision'] == 'accept' else {}
            )}
        return {'decision': decisions[result['decision']]}

    def _approval_context(self) -> dict:
        """Map native rollout snapshots and subsequent items without new compaction.

        Codex 0.154.0 history/src/rollout_payload.rs defines compacted.message,
        replacement_history, retained_context, and separate turn_context and
        retained_context events. Preserve user/developer inputs across snapshots
        so compaction cannot remove explicit task restrictions from this review.
        """
        visible = {
            'message', 'function_call', 'function_call_output',
            'custom_tool_call', 'custom_tool_call_output',
        }
        context = {'history': [], 'authorization_messages': [],
                   'compaction': None, 'retained_context_events': [], 'turn_context': None}
        if not self.trace_file.exists():
            return context
        with self.trace_file.open(encoding='utf-8') as stream:
            for line in stream:
                record = json.loads(line)
                payload = record.get('payload', {})
                kind = record.get('type')
                if kind == 'response_item' and payload.get('type') in visible:
                    context['history'].append(payload)
                    if payload.get('type') == 'message' and payload.get('role') in {'user', 'developer'}:
                        context['authorization_messages'].append(payload)
                elif kind == 'compacted':
                    # Use the native replacement and summary rather than summarize
                    # or silently retain superseded tool evidence ourselves.
                    replacement = payload.get('replacement_history')
                    context['history'] = [
                        item for item in (replacement or []) if item.get('type') in visible
                    ]
                    context['compaction'] = {
                        'message': payload.get('message'),
                        'retained_context': payload.get('retained_context'),
                    }
                elif kind == 'retained_context':
                    context['retained_context_events'].append(payload)
                elif kind == 'turn_context':
                    context['turn_context'] = payload
        return context

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
