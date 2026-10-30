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
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

import yaml

from agent_swarm.approval import review_failed
from agent_swarm.review import build_request, record_decision, review_call
from agent_swarm.runtime import RuntimeAdapterError
from .app_server import CodexAppServer, CodexExecution, CodexServerRequest
from .context import restore_codex_context, recovery_environment


def model_change_message(summary: str, requested: object, observed: object, reason: str | None) -> str:
    """State both models and the Runtime's reason so a stopped child is diagnosable (369)."""
    return (f'{summary}: requested model {requested}, observed model {observed}; Runtime reason: '
            + (reason or 'not provided in the native stream') + '.')


# Auto-review outcomes Codex reports only as notifications (Codex 0.164
# app-server: item/autoApprovalReview/completed, GuardianApprovalReviewStatus).
REVIEW_COMPLETED = 'item/autoApprovalReview/completed'
RELAYED_REVIEWS = {'denied', 'timedOut', 'aborted'}


def _accepted(request: CodexServerRequest) -> dict | None:
    """Return the native answer accepting exactly this request, if Codex offers one."""
    if request.method == 'mcpServer/elicitation/request':
        # The exact native tool call, without persistent server trust.
        return {'action': 'accept'}
    if request.method == 'item/permissions/requestApproval':
        # The exact requested profile; omitted scope is Codex's default, the turn.
        permissions = request.params.get('permissions')
        return {'permissions': permissions} if permissions else None
    if request.method in {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval'}:
        available = request.params.get('availableDecisions')
        return {'decision': 'accept'} if available is None or 'accept' in available else None
    return None


def _snake(value: object) -> object:
    """Rename camelCase mapping keys to snake_case, recursively."""
    if isinstance(value, dict):
        return {re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower(): _snake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snake(item) for item in value]
    return value


def _assessment_event(params: dict) -> dict:
    """Serialize a review notification as Codex's native assessment event.

    ponytail: the app-server publishes only the camelCase notification while
    ``thread/approveGuardianDeniedAction`` takes the core GuardianAssessmentEvent.
    The snake_case names follow the 0.164 binary's field strings; a real host
    has not yet accepted this shape, and a refusal reaches the parent's reply.
    """
    review = params['review']
    return {
        'id': params['reviewId'], 'target_item_id': params.get('targetItemId'),
        'turn_id': params['turnId'], 'started_at_ms': params.get('startedAtMs'),
        'completed_at_ms': params.get('completedAtMs'), 'status': 'denied',
        'risk_level': review.get('riskLevel'), 'user_authorization': review.get('userAuthorization'),
        'rationale': review.get('rationale'), 'decision_source': params.get('decisionSource'),
        'action': _snake(params.get('action')),
    }


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
        archive: object | None = None,
        extra_fields: dict | None = None,
        review: Mapping | None = None,
    ) -> None:
        """Capture immutable task configuration for one Worker execution.

        ``archive`` is the bound :class:`SessionArchive`, or ``None`` to archive
        nothing; ``extra_fields`` goes to the header of a Session first archived here.
        ``review`` is the reviewer judging this execution's native approvals, or
        ``None`` to keep Codex's own.
        """
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
        self.archive = archive
        self.extra_fields = extra_fields
        self.review = review
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
        # Auto-review outcomes relayed to the direct parent, and the answers
        # that still need a native turn after the reviewed turn has ended.
        self.relays: dict[str, tuple[CodexServerRequest, asyncio.Future[dict]]] = {}
        self.followups: list[str] = []
        self.relay_notices: set[asyncio.Task] = set()

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
        # The reviewer's key stays with this host, away from the child it judges,
        # unless the connection itself gives the child that variable.
        review_key = (self.review or {}).get('api_key_env')
        withheld = {review_key: None} if review_key and review_key not in self.connection_environment else {}
        adapter = CodexAppServer(cwd=Path(self.context.session_document()['adapter_request']['cwd']),
                                 command=self.command, request_timeout=5,
                                 environment={**self.context.runtime_environment(), **self.connection_environment,
                                              'AGENT_SWARM_CONNECTION': None, 'GRAPHTRAJ_CLI_CONNECTION': None,
                                              **withheld},
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
                if self.review is not None and permissions['approval_policy'] == 'never':
                    # A setting outside what agents supplied, such as the native home's.
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', "Codex runs this Session with approval_policy "
                                                                        "'never', so the review plugin would never run.")
                requested = request['session_parameters'].get('model')
                observed = session.configuration.get('model', requested)
                if requested is not None and observed != requested:
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', model_change_message(
                        f'Codex {phase} selected a different model', requested, observed, None))
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
                    result = await self._settle_relays(session, result)
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
                reroute = adapter.reroutes.get((session.thread_id, self.execution.turn_id))
                if reroute is not None:
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', model_change_message(
                        'Codex rerouted the turn to a different model', requested or reroute.get('fromModel'),
                        reroute.get('toModel'), reroute.get('reason')))
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
                if (notification['method'] == 'model/rerouted' and self.execution is not None
                        and notification['params'].get('turnId') == self.execution.turn_id):
                    # Stop work on a model nobody requested; the result names both.
                    self.terminate()
                if notification['method'] == 'item/autoApprovalReview/completed':
                    self._relay_review(notification.get('params', {}))
                if notification['method'] == 'error':
                    with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(notification, ensure_ascii=False) + '\n')
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
        if request.get('operation') == 'send' and self.outcome is not None:
            raise RuntimeAdapterError('runtime-input-closed', 'The execution has stopped accepting input.')
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
            pending = self._pending_requests()
            return {'requests': pending if not self.result.done() else [
                details for details in pending if details['request_token'] in self.relays]}
        if request['operation'] == 'reply':
            if request['request_token'] in self.relays:
                return await self._answer_relay(request['request_token'], request['response'])
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
        return await self._hold(request)

    async def _hold(self, request: CodexServerRequest) -> dict:
        """Keep one native request pending for the direct parent's reply."""
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
        if request.method == REVIEW_COMPLETED:
            notice += (" Codex automatic approval review did not allow this action;"
                       " reply accept to let the child retry it once under auto review"
                       " again, or decline to keep it refused.")
        notice += "\n" + json.dumps({**identity, "params": request.params}, ensure_ascii=False)
        while self._waiting(token):
            receipt = await asyncio.to_thread(
                self.parent_notice, notice, identity,
            ) if self.parent_notice is not None else {"delivery": "no-direct-parent"}
            if receipt["delivery"] in {"received", "retained", "no-direct-parent"}:
                return
            # Retry only while the original native request is still pending.
            await asyncio.sleep(1)


    def _waiting(self, token: str) -> bool:
        """Whether a held native request or relayed review still awaits its reply."""
        entry = self.requests.get(token) or self.relays.get(token)
        return entry is not None and not entry[1].done()

    def _relay_review(self, params: dict) -> None:
        """Hold a refused or failed auto review for the direct parent's answer.

        Codex resolves approvals itself under ``approvals_reviewer = auto_review``
        and only reports the outcome as a notification. A denial (``denied``)
        or a reviewer failure (``timedOut``, ``aborted``) becomes a
        parent-visible request; approvals and reviews in progress do not.
        """
        review = params.get('review') if isinstance(params.get('review'), dict) else {}
        if review.get('status') not in RELAYED_REVIEWS or not isinstance(params.get('reviewId'), str):
            return
        token = uuid.uuid4().hex
        relay = CodexServerRequest('auto-review:' + params['reviewId'], REVIEW_COMPLETED, params)
        self.relays[token] = (relay, asyncio.get_running_loop().create_future())
        notice = asyncio.create_task(self._notify_direct_parent(relay, token))
        self.relay_notices.add(notice)
        notice.add_done_callback(self.relay_notices.discard)

    async def _answer_relay(self, token: str, response: dict) -> dict:
        """Apply the parent's one answer to a relayed auto-review outcome.

        ``accept`` after a denial records Codex's own one-retry approval
        (``thread/approveGuardianDeniedAction``); after a reviewer failure no
        native record exists, so the child is only told it may retry. Either
        way the retry goes through auto review again, so the parent cannot
        approve the action itself. ``decline`` keeps the refusal. The answer
        reaches the child as input to its active turn, or an accepted answer
        starts one follow-up turn once the reviewed turn has ended.
        """
        relay, answered = self.relays[token]
        if answered.done():
            raise RuntimeAdapterError('operation-failed', 'The relayed review is no longer pending.')
        if response not in ({'decision': 'accept'}, {'decision': 'decline'}):
            raise RuntimeAdapterError('invalid-input', 'Return an explicit accept or decline decision.')
        assert self.adapter is not None and self.execution is not None
        params = relay.params
        denied = params['review']['status'] == 'denied'
        accepted = response['decision'] == 'accept'
        if accepted and denied:
            await self.adapter.approve_denied_action(params['threadId'], _assessment_event(params))
        outcome = 'denied' if denied else 'could not complete'
        message = (
            f"Your direct parent answered the automatic approval review that {outcome} "
            f"(review {params['reviewId']}): "
            + ("you may retry that action once; the retry still goes through automatic approval review."
               if accepted else "do not retry that action; continue with other work or report it as blocked.")
        )
        answered.set_result(response)
        if not self.result.done():
            try:
                await self.adapter.send_input(self.execution, message)
                message = None
            except RuntimeAdapterError:
                pass  # The turn ended meanwhile; an accepted answer gets a follow-up turn.
        if message is not None and accepted:
            self.followups.append(message)
        return {'request_id': relay.request_id, 'reply_status': 'submitted'}

    async def _settle_relays(self, session: object, result: dict) -> dict:
        """Keep the execution open until every relayed review is answered.

        Returns the last native turn's result: an accepted answer that arrives
        after the reviewed turn has ended starts one follow-up turn.
        """
        assert self.adapter is not None
        while True:
            # A review reported just before turn/completed may still be queued
            # for the observer; let it register before deciding nothing waits.
            for _ in range(100):
                if not self.adapter.notifications_pending:
                    break
                await asyncio.sleep(0.01)
            waiting = [answered for _, answered in self.relays.values() if not answered.done()]
            if waiting:
                await asyncio.wait(waiting)
                continue
            if not self.followups or self.termination_requested:
                return result
            prompt = '\n'.join(self.followups)
            self.followups.clear()
            self.execution = await self.adapter.start_execution(session, prompt)
            self.result = asyncio.create_task(self.adapter.wait(self.execution))
            result = await self.result

    def permission_evidence(self, observed: dict) -> dict:
        """Distinguish the requested reviewer and its source from Codex's startup report."""
        params = self.context.session_document()['adapter_request']
        requested = params.get('approvalsReviewer', params.get('config', {}).get('approvals_reviewer'))
        selection = self.context.evidence_document().get('approvals_reviewer') or {}
        actual = observed.get('approvalsReviewer')
        return {
            'requested': requested,
            'source': ('review-plugin' if self.review is not None else
                       'role' if self._uses_review() else selection.get('source', 'unknown')),
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
            for token, (native, response) in [*self.requests.items(), *self.relays.items()]
            if not response.done()
        ] + [details for details, response in self.recovery_requests.values() if not response.done()]

    def terminate(self) -> bool:
        """Schedule native interruption for a Worker termination/budget signal."""
        self.termination_requested = True
        if self.loop is None or self.loop.is_closed():
            return False
        def drop_relays() -> None:
            """Stop holding relayed reviews; termination ends the execution."""
            for _, answered in self.relays.values():
                answered.cancel()
        self.loop.call_soon_threadsafe(drop_relays)
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
        """Native approval is handled by Codex unless a reviewer is selected or a consumer provides one."""
        return self.review is not None

    async def _review_approval(self, request: CodexServerRequest) -> dict:
        """Judge one native approval with the review plugin before the call runs.

        ``allow`` accepts exactly this request. Anything else, including a
        failed review, holds the same native request for the direct parent with
        ``params.review`` added, so ``requests``, the notice and ``reply`` work as
        for any held request. There is no retry and no second review.
        """
        parameters = self.context.session_document()['adapter_request']
        item = self.approval_items.get(request.params.get('itemId'))
        accepted = _accepted(request)
        if accepted is None:
            decision = review_failed('Codex offers no answer accepting this request')
        elif request.method == 'item/fileChange/requestApproval' and not item:
            decision = review_failed('the file changes are not available for review')
        else:
            decision = await asyncio.to_thread(review_call, self.review, build_request(
                'codex', request.method, request.params, cwd=parameters['cwd'], instruction=self.prompt,
                native={'item': item, 'permissions': parameters['config'].get('permissions'),
                        'default_permissions': parameters['config'].get('default_permissions')},
            ))
        try:
            await asyncio.to_thread(record_decision, self.directory, 'codex', request.method,
                                    str(request.request_id), decision)
        except OSError as error:
            decision = review_failed(f'the decision could not be recorded ({type(error).__name__})')
        if decision['decision'] == 'allow':
            return accepted
        return await self._hold(replace(request, params={**request.params, 'review': decision}))

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
        """Collect the native rollout into the bound archive, if any."""
        if self.archive is None:
            return None
        from agent_swarm.sessions.codex import CodexJsonlArchive

        return CodexJsonlArchive(self.archive, session.thread_id, session.rollout_path,
                                 new_session=self.expected_session is None,
                                 extra_fields=self.extra_fields)

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
