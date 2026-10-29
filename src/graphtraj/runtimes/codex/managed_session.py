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

from graphtraj.configuration.project_configuration import (
    configuration_exists,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import load_project_roles
from graphtraj.runtimes.codex.approval import approval_route, review_request

from graphtraj.execution.runner_batch import read_session_task
from graphtraj.execution.runner_control import notify_direct_parent
from graphtraj.execution.runner_io import write_yaml_durably
from agent_swarm.codex.app_server import CodexAppServer, CodexExecution, CodexServerRequest
from agent_swarm.codex.managed_session import CodexManagedExecution as NativeCodexExecution
from graphtraj.runtimes.codex.codex_adapter import restore_codex_context
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from agent_swarm.sessions.archive import SessionArchive


def _approval_history_text(value: object) -> object:
    """Keep textual review evidence, replacing inline binary bodies explicitly.

    Rollout tool results can contain MCP content, including JSON encoded inside
    an output string. Sending their base64 as text cannot provide image evidence
    to the reviewer and can exhaust its context before it sees the command.
    This selection is only for historical evidence, never the pending request.
    """
    omitted = '[inline binary omitted; not available as review evidence]'
    if isinstance(value, list):
        return [_approval_history_text(item) for item in value]
    if isinstance(value, dict):
        content_type = value.get('type')
        binary = isinstance(content_type, str) and content_type in {
            'image', 'audio', 'input_audio', 'input_file',
        }
        return {
            key: omitted if binary and key in {'data', 'file_data'}
            else _approval_history_text(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        # Preserve the string shape and all textual output, including safety
        # restrictions. JSON tool envelopes are not always native content blocks.
        if value.lstrip().startswith(('{', '[')):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                selected = _approval_history_text(parsed)
                if selected != parsed:
                    return json.dumps(selected, ensure_ascii=False)
        return re.sub(r'data:[\w.+/-]+(?:;[\w=.+-]+)*;base64,[A-Za-z0-9+/=]+',
                      lambda _: omitted, value)
    return value


def refresh_approval_route(request: dict, session_directory: Path) -> None:
    """Reload approval and scoped socket access, preserving captured work settings."""
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
    from graphtraj.runtimes.codex.codex_adapter import apply_unix_socket_access

    apply_unix_socket_access(request, (settings.codex or {}).get('unix_sockets'))
    defaults = (
        load_project_configuration(harness_root).codex
        if configuration_exists(harness_root) else None
    )
    from graphtraj.runtimes.codex.local_websocket import project_access
    project_access(request, (defaults or {}).get('local_websocket')
                   if (settings.codex or {}).get('local_websocket_access') is True else None)
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


class CodexManagedExecution(NativeCodexExecution):
    """Attach GraphTraj task policy to the independent native execution owner."""

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
        independent: bool = False,
        archive: SessionArchive | None = None,
        connection: dict[str, str] | None = None,
        agent_call: Callable | None = None,
        extra_fields: dict | None = None,
    ) -> None:
        """Refresh consumer policy before the shared owner captures native settings.

        The shared owner archives; GraphTraj only chooses the archive and its
        ``extra_fields.graphtraj``. A Runner execution with a creation callback
        uses the project archive and its mapped Task.
        """
        from graphtraj.interfaces.agents import configured_archive, graphtraj_fields

        request = restore_codex_context(request, context_evidence).launch_document()['adapter_request']
        if expected_session and not independent:
            refresh_approval_route(request, session_directory)
        if not independent:
            archive = None
            if session_created is not None:
                from graphtraj.workspace.runner_project import discover_project_root

                archive = configured_archive(discover_project_root(Path(request['worktree_path'])))
        if archive is not None:
            extra_fields = graphtraj_fields(str(archive.root), session_directory.name, (), extra_fields)
        super().__init__(request, prompt, session_directory, session_started, context_evidence,
                         trace_file, expected_session, session_created,
                         connection=connection, agent_call=agent_call,
                         archive=archive, extra_fields=extra_fields)
        self.independent = independent
        self.approval = request.get('approval')
        if not independent:
            self.parent_notice = lambda notice, identity: notify_direct_parent(self.directory, notice, identity)

    def _uses_review(self) -> bool:
        """Keep the configured GraphTraj external review route."""
        return self.approval is not None

    def _bind_connection(self, connections: ExitStack, request: dict, cwd: Path) -> tuple:
        """Bind task tools for formal Workers, agents alone for Task-free consumers."""
        if self.independent:
            return super()._bind_connection(connections, request, cwd)
        if self.created is None:
            return None, None, None
        from graphtraj.interfaces.hosted_cli import CONNECTION_ENV, cli_connection
        from graphtraj.runtimes.codex.access import member_project_reads
        from graphtraj.workspace.runner_project import discover_project_root
        from agent_swarm.connection import verify_native_context

        root = discover_project_root(cwd)
        native_context = lambda: {'runtime': 'codex', 'session': self.native_session, 'cwd': str(cwd)}

        # A retained request may predate read-only project records. Apply
        # the current member grants at the native owner on every resume.
        config = request['session_parameters']['config']
        profile = config['permissions'][config['default_permissions']]
        profile['filesystem'].update(member_project_reads(root))

        def authorize(native: dict, _request: dict) -> tuple[str | None, set[str]]:
            """Verify own-thread calls without an event-loop round trip."""
            if isinstance(native, dict) and native.get('session') == self.native_session:
                verify_native_context(native, native_context())
                return self.directory.name, native_operation_features()
            return asyncio.run_coroutine_threadsafe(authorize_mcp_caller(
                self.adapter, self.native_session, self.directory.name, root, cwd, native,
            ), self.loop).result(timeout=30)

        address = connections.enter_context(cli_connection(
            root, self.directory.name, native_operation_features(), self._review_recovery_sync,
            native_context=native_context, native_authorizer=authorize,
        ))
        return address, CONNECTION_ENV, 'graphtraj.interfaces.mcp'

    def _archive(self, session: object) -> object | None:
        """Name a Runner execution's Task once its mapping exists, at native Session start."""
        if not self.independent and self.extra_fields is not None:
            from graphtraj.interfaces.agents import mapped_task_ids

            self.extra_fields['graphtraj']['taskIds'] = mapped_task_ids(self.directory)
        return super()._archive(session)

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

    async def _review_approval(self, request: CodexServerRequest) -> dict:
        """Review this request and return its native response without a separate log."""
        if request.method not in {
            'item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
            'item/permissions/requestApproval',
            'mcpServer/elicitation/request',
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
        if request.method == 'mcpServer/elicitation/request':
            # Review the exact native tool call, without granting persistent
            # server trust or answering ordinary server input elicitations.
            return {'action': result['decision']}
        if request.method == 'item/permissions/requestApproval':
            # Return only the exact requested profile; omitted scope uses Codex's
            # native default (turn). A denial grants nothing, only after review.
            return {'permissions': (
                request.params['permissions'] if result['decision'] == 'accept' else {}
            )}
        return {'decision': decisions[result['decision']]}

    def _approval_context(self) -> dict:
        """Select textual native evidence without summarizing safety constraints.

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
                    if payload.get('type') == 'message' and payload.get('role') in {'user', 'developer'}:
                        context['authorization_messages'].append(payload)
                        # Keep provenance/order in history, but send this often
                        # large authorization body only once across both fields.
                        context['history'].append({
                            'type': 'authorization_reference',
                            'index': len(context['authorization_messages']) - 1,
                        })
                    else:
                        context['history'].append(payload)
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
        # A native replacement history may itself contain authorizations already
        # retained above. Reference those too, without losing their new position.
        for index, item in enumerate(context['history']):
            if item.get('type') == 'message' and item.get('role') in {'user', 'developer'}:
                if item not in context['authorization_messages']:
                    context['authorization_messages'].append(item)
                context['history'][index] = {
                    'type': 'authorization_reference',
                    'index': context['authorization_messages'].index(item),
                }
        return _approval_history_text(context)

async def authorize_mcp_caller(
    adapter: CodexAppServer,
    native_session: str | None,
    alias: str | None,
    root: Path,
    cwd: Path,
    native: dict,
) -> tuple[str | None, set[str]]:
    """Keep existing native helper/checker summary access on an owned MCP channel.

    Kernel process authentication precedes this check. A real parent chain or
    the retained finish-check binding is required; fork lineage alone grants
    nothing. Returned identities use the existing Runner caller scope.
    """
    from agent_swarm.connection import verify_native_context
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.runtimes.codex.session_entry import is_bound_checker, session_source
    from graphtraj.workspace.runner_project import discover_runner_directory

    thread = native.get('session') if isinstance(native, dict) else None
    verify_native_context(native, {'runtime': 'codex', 'session': thread, 'cwd': str(cwd)})
    if native_session is None:
        raise RunnerError('authority-denied', 'The native Session is not ready.')
    if thread == native_session:
        return alias, native_operation_features()
    current = thread
    seen = set()
    while current and current != native_session and current not in seen:
        seen.add(current)
        current = await adapter.read_thread_parent(current)
    if current != native_session:
        metadata = await adapter.read_thread(thread)
        if (session_source(metadata) != 'main'
                or metadata.get('forkedFromId') != native_session
                or not is_bound_checker(discover_runner_directory(root), adapter.native_connection(thread))):
            raise RunnerError('authority-denied', 'Caller is outside this native Session subtree.')
    return thread, {'task_graph', 'agents'}


def native_operation_features() -> set[str]:
    """Share the managed host's allowed operations across MCP and CLI."""
    from graphtraj.interfaces.tools import METHOD_FEATURE_NAMES

    return ({'swarm', 'session_reports', 'submit_report', 'submit_result',
                'decide_result', 'retain_evidence', 'task_graph', 'task_members', 'worldline_read'}
            | set(METHOD_FEATURE_NAMES)
            | {'parent_status', 'replace', 'cleanup', 'approved_recovery',
               'role_organization', 'runtime_connections', 'desktop_activity', 'session_read', 'agents'})
