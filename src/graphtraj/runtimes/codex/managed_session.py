"""Connect the background Runner owner to the production native Session Adapter."""

from __future__ import annotations

import asyncio
import os
import json
import re
import uuid
from concurrent.futures import CancelledError
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

import yaml

from graphtraj.configuration.project_configuration import (
    configuration_exists,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.runtimes.codex.approval import approval_route, review_request

from graphtraj.execution.runner_batch import read_session_task
from graphtraj.execution.runner_control import notify_direct_parent
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexExecution, CodexServerRequest
from graphtraj.runtimes.codex.codex_adapter import restore_codex_context
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def refresh_approval_route(request: dict, session_directory: Path) -> None:
    """Reload only approval routing for the mapped role, preserving work settings."""
    config = request.get('session_parameters', {}).get('config', {})
    root = os.environ.get('GRAPHTRAJ_HARNESS_ROOT')
    if not root:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Harness root is required to refresh codex.approval.')

    harness_root = Path(root)
    mapping = yaml.safe_load((session_directory / 'mapping.yml').read_text(encoding='utf-8'))
    task = read_session_task(mapping, harness_root)
    # Inline roles live in their retained Batch, not in the reusable presets.
    settings = task.inline_preset
    if settings is None:
        roles = load_project_roles(harness_root)
        # Approval can change without resolving a new work connection. Removing
        # a catalog entry must not invalidate a captured Session.
        settings = roles.presets[roles.resolve(mapping.get('role_reference') or mapping['role'])]
    defaults = (
        load_project_configuration(harness_root).codex
        if configuration_exists(harness_root) else None
    )
    route = approval_route(
        settings.codex,
        custom=config.get('model_provider', 'openai') != 'openai',
        defaults=defaults,
    )
    if route is None:
        request.pop('approval', None)
        return
    request['approval'] = route
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
        session_created: Callable[[str, int], None] | None = None,
    ) -> None:
        """Capture immutable task configuration for one Worker execution."""
        self.context = restore_codex_context(request, context_evidence)
        request = self.context.launch_document()['adapter_request']
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
        self.created = session_created
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
        # Only a formal Worker has a creation callback that binds its native
        # Session to Runner ownership before the first Agent turn.
        if self.created is not None:
            from graphtraj.interfaces.hosted_cli import CONNECTION_ENV, cli_connection
            from graphtraj.workspace.runner_project import discover_project_root

            request = self.context.launch_document()['adapter_request']
            root = discover_project_root(Path(request['worktree_path']))
            address = connections.enter_context(cli_connection(
                root, self.directory.name, native_operation_features(), self._review_recovery_sync,
            ))
            config = request['session_parameters']['config']
            profile = config['permissions'][config['default_permissions']]
            profile['filesystem'][address] = 'write'
            config.setdefault('shell_environment_policy', {}).setdefault('set', {})[CONNECTION_ENV] = address
            self.context = restore_codex_context(request, self.context.evidence_document())
        adapter = CodexAppServer(cwd=Path(self.context.session_document()['adapter_request']['cwd']),
                                 command=self.command, request_timeout=5,
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
                write_yaml_durably(self.directory / 'session.yml', {
                    'session': session.thread_id,
                    'rollout_path': str(session.rollout_path) if session.rollout_path else None,
                })
                adapter.retain_native_trace(session, self.trace_file)
                if self.created is not None:
                    self.created(session.thread_id, adapter.service_pid)
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
        from graphtraj.runtimes.codex.codex_adapter import NATIVE_RUNNER_TOOLS

        if (
            request.method == 'item/tool/call'
            and request.params.get('tool') in {'graphtraj', *NATIVE_RUNNER_TOOLS}
        ):
            return await self._native_runner_request(request)
        if self.approval is not None and request.method.endswith("/requestApproval"):
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

    async def _native_runner_request(self, request: CodexServerRequest) -> dict:
        """Use the managed Session's bound identity for native Runner operations."""
        from graphtraj.workspace.runner_project import discover_project_root

        cwd = Path(self.context.session_document()['adapter_request']['cwd'])
        return await run_native_operation(
            self.adapter, self.native_session, self.directory.name,
            discover_project_root(cwd), request, recovery_reviewer=self._review_recovery_sync,
        )

    def _review_recovery_sync(self, proposal: dict) -> dict:
        """Bridge the tool worker to this existing execution's selected reviewer."""
        return asyncio.run_coroutine_threadsafe(self._review_recovery(proposal), self.loop).result()

    async def _review_recovery(self, proposal: dict) -> dict:
        """Review a host action; never present it as a native Codex request."""
        assert self.execution is not None and self.result is not None
        token = uuid.uuid4().hex
        context = {
            **self._approval_context(), 'request_id': token,
            'method': 'graphtraj/recoveryApproval', 'request': proposal,
            'allowed_decisions': ['accept', 'decline'], 'authorization': self.prompt,
            'developer_instructions': self.context.session_document()['adapter_request'].get('developerInstructions'),
        }
        if self.approval is not None:
            return await review_request(self.approval, context)
        params = self.context.session_document()['adapter_request']
        reviewer = params.get('approvalsReviewer', params.get('config', {}).get('approvals_reviewer', 'user'))
        if reviewer != 'user':
            raise RuntimeAdapterError('native-approval-unavailable',
                                      'The selected native automatic reviewer has no recovery callback.')
        response = asyncio.get_running_loop().create_future()
        from graphtraj.execution.approved_recovery import _differences

        # Keep the exact snapshot in this pending call; disclose only the action
        # and concrete changed values needed for the user's decision.
        summary = {'request': proposal['request'],
                   'changes': _differences(proposal['before'], proposal['after'])}
        identity = {'session': self.execution.thread_id, 'execution_id': self.execution.turn_id,
                    'request_id': token, 'request_token': token,
                    'method': 'graphtraj/recoveryApproval'}
        details = {**identity, 'params': summary}
        self.recovery_requests[token] = (details, response)
        try:
            receipt = await asyncio.to_thread(
                notify_direct_parent, self.directory,
                'Recovery needs an explicit user decision through the pending-request reply:\n'
                + json.dumps(details, ensure_ascii=False), identity,
            )
            if receipt['delivery'] != 'received':
                raise RuntimeAdapterError('native-approval-unavailable', 'The selected user review channel is unavailable.')
            done, _ = await asyncio.wait((response, self.result), return_when=asyncio.FIRST_COMPLETED)
            if self.result in done:
                raise RuntimeAdapterError('operation-failed', 'Execution ended before recovery review completed.')
            return response.result()
        finally:
            self.recovery_requests.pop(token, None)
            if not response.done():
                response.cancel()

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
                notify_direct_parent, self.directory, notice, identity,
            )
            if receipt["delivery"] in {"received", "no-direct-parent"}:
                return
            # Retry only while the original native request is still pending.
            await asyncio.sleep(1)

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


async def run_native_operation(
    adapter: CodexAppServer | None,
    native_session: str | None,
    root_alias: str | None,
    root: Path,
    request: CodexServerRequest,
    *,
    recovery_reviewer: Callable[[dict], dict] | None = None,
) -> dict:
    """Route an owned native callback, preserving the Runtime's issuing identity."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request
    from graphtraj.interfaces.tools import METHOD_FEATURE_NAMES, TOOLS, ToolResult
    from graphtraj.runtimes.codex.codex_adapter import NATIVE_RUNNER_TOOLS
    from graphtraj.workspace.runner_project import discover_runner_directory

    try:
        thread = request.params.get('threadId')
        arguments = request.params.get('arguments')
        name = request.params.get('tool')
        if (
            not isinstance(thread, str) or not thread
            or native_session is None or adapter is None
            or not isinstance(arguments, dict)
            or name not in {'graphtraj', *NATIVE_RUNNER_TOOLS}
        ):
            raise RunnerError('invalid-input', 'Supply only supported tool arguments.')
        current: str | None = thread
        seen: set[str] = set()
        while current != native_session:
            if current in seen:
                raise RunnerError('authority-denied', 'Native parent chain is cyclic.')
            seen.add(current)
            current = await adapter.read_thread_parent(current)
            if current is None:
                raise RunnerError('authority-denied', 'Native caller is outside this Session subtree.')
        # Method-only features have no handler, so disclosing them adds
        # readable guidance without adding executable capability.
        allowed_features = native_operation_features()
        if name == 'graphtraj':
            feature = arguments.get('feature')
            action = arguments.get('action')
        else:
            feature, action = NATIVE_RUNNER_TOOLS[name], 'execute'
            tool = TOOLS[feature]
            if not set(arguments) <= set(tool.input_schema['properties']):
                raise RunnerError('invalid-input', 'Supply only supported tool arguments.')
        if thread != native_session:
            allowed_features = {'alias_status', 'ticket_graph', *METHOD_FEATURE_NAMES}
            if action == 'execute' and feature not in ('alias_status', 'ticket_graph'):
                raise RunnerError('authority-denied', 'Temporary native helpers have read-only Runner access.')
        identity = root_alias if thread == native_session else thread

        def operate() -> ToolResult:
            """Reuse public validation/control without process-based authorization."""
            from graphtraj.runtimes.runtime_adapter import recovery_review

            with runtime_caller(discover_runner_directory(root), identity), recovery_review(recovery_reviewer):
                if name == 'graphtraj':
                    return handle_request(arguments, cwd=root, allowed_features=allowed_features)
                return tool.handler(arguments, cwd=root)

        response = await asyncio.to_thread(operate)
        document, success = response.document, not response.failed
    except (RunnerError, RuntimeAdapterError) as error:
        document, success = {'error': {'code': error.code, 'message': error.message}}, False
    except ValueError as error:
        document, success = {'error': {'code': 'invalid-input', 'message': str(error)}}, False
    except OSError as error:
        document, success = {'error': {'code': 'operation-failed', 'message': str(error)}}, False
    return {
        'contentItems': [{'type': 'inputText', 'text': json.dumps(document)}],
        'success': success,
    }


def native_operation_features() -> set[str]:
    """Share the managed host's allowed operations across native tools and CLI."""
    from graphtraj.interfaces.tools import METHOD_FEATURE_NAMES
    from graphtraj.runtimes.codex.codex_adapter import NATIVE_RUNNER_TOOLS

    return (set(NATIVE_RUNNER_TOOLS.values()) | set(METHOD_FEATURE_NAMES)
            | {'parent_status', 'retire', 'replace', 'cleanup', 'approved_recovery',
               'role_organization', 'runtime_connections', 'desktop_activity'})
