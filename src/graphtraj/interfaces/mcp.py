"""Host-callable GraphTraj operations over MCP stdio JSON-RPC.

The installed ``graphtraj-mcp`` entry point answers the MCP methods a host
needs to discover and run tools: ``initialize``, ``notifications/initialized``,
``tools/list``, ``tools/call`` and ``ping``. Only ``agents`` and ``tasks`` are
published, with individual feature schemas disclosed on demand.

The server speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and uses
only the standard library, so no MCP SDK dependency is required. It reads the
Harness Project Root from its own working directory, exactly like the CLI.
"""

from __future__ import annotations

import os
import sys
import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, TextIO

import yaml

from agent_swarm.mcp import error_response as _error_response, result_response as _result_response

from graphtraj.configuration.project_configuration import ProjectConfigurationError
from graphtraj.configuration import project_configuration
from graphtraj.execution.execution_budget import budget_notice_output, caller_notice_fd
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import gateway
from graphtraj.runtimes.codex.app_server import CodexMainRecovery
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError


SERVER_INFO      = {"name": "graphtraj", "version": "0.1.0"}
_SERVICE = {'executable': sys.executable, 'module': __file__,
            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'configuration_sha256': hashlib.sha256(Path(project_configuration.__file__).read_bytes()).hexdigest()}

INVALID_PARAMS   = -32602


def _tool_documents() -> list[dict[str, Any]]:
    """Publish the two lightweight entries on every supported host."""
    return [
        {'name': name, 'description': f'Discover, describe, or execute {name} features.',
         'inputSchema': gateway.INPUT_SCHEMA}
        for name in ('agents', 'tasks')
    ]


@contextmanager
def _caller_notices(
    params: Mapping[str, Any],
) -> Iterator[CodexMainRecovery | None]:
    """Route live budget notices to the Codex Main that made this request.

    A worker's inherited channel wins. Otherwise the request's own Codex
    thread identity selects its Main through the existing recovery binding, so
    a stop produced by this operation reaches the conversation that called it.
    A request carrying no Codex caller context keeps the generic behaviour of
    no notice channel.
    """

    if 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        # The authenticated owner already routes its native notices/approvals.
        yield None
        return
    descriptor, owned = caller_notice_fd()
    if descriptor is None:
        recovery = CodexMainRecovery.from_request(
            params.get("_meta")
        )
        if recovery is not None:
            with recovery:
                with budget_notice_output(recovery.notice_fd):
                    yield recovery
            return
        yield None
        return
    try:
        with budget_notice_output(descriptor):
            yield None
    finally:
        if owned:
            os.close(descriptor)


def _tool_call_response(
    request_id: Any, params: Mapping[str, Any]
) -> dict[str, Any]:
    """Forward a registered function request and return its MCP tool result.

    The request's outer arguments are the gateway's discover/describe/execute
    envelope. The server's own working directory is the trusted project
    location; model arguments cannot supply it. Business failures keep the
    shared document and the CLI's message instead of stopping the server.
    """

    name = params.get("name")
    if name not in ('agents', 'tasks'):
        return _error_response(
            request_id, INVALID_PARAMS, "Unknown tool: {0}".format(name)
        )
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_response(
            request_id, INVALID_PARAMS, "Tool arguments must be an object."
        )
    try:
        # Keep the selected entry's scope before forwarding into the already
        # authenticated host. The host still owns feature authorization.
        if name == 'tasks' and arguments.get('action') != 'discover':
            if arguments.get('feature') == 'agents':
                raise ValueError('Feature does not belong to this MCP entry.')
        from graphtraj.runtimes.codex.host_events import calling_session

        metadata = params.get('_meta', {})
        session = metadata.get('threadId') if isinstance(metadata, dict) else None
        if session is not None and (not isinstance(session, str) or not session):
            raise ValueError('Invalid native MCP Session metadata.')
        with calling_session(session), _caller_notices(params) as recovery:
            from graphtraj.interfaces.hosted_cli import forward_request

            def dispatch(request: dict) -> Any:
                """Keep the existing host binding and shared business gateway."""
                from agent_swarm.connection import client_native_context

                result = forward_request(request, Path.cwd(), native_context=client_native_context(metadata))
                return result if result is not None else gateway.handle_request(request, cwd=Path.cwd())

            if name == 'agents':
                from agent_swarm.discovery import handle_request

                from agent_swarm.connection import client_native_context
                from graphtraj.interfaces.hosted_cli import agents_dispatch

                result = handle_request(arguments, lambda request: agents_dispatch(
                    request, Path.cwd(), native_context=client_native_context(metadata)))
            else:
                result = dispatch(arguments)
                if arguments.get('action') == 'discover' and not result.failed:
                    result.document['features'] = [item for item in result.document.get('features', [])
                                                   if item['feature'] != 'agents']
                    # Capture in the serving process, not from a caller's CLI
                    # installation. A forwarded host supplies its own stamp.
                    result.document.setdefault('service', {})['mcp'] = _SERVICE
            document = (
                recovery.attach_stop_deliveries(result.document)
                if recovery is not None
                else result.document
            )
    except (
        OSError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
        ProjectConfigurationError,
        RunnerError,
        CodexAdapterError,
    ) as error:
        # A rejected operation is a tool failure, not a protocol failure, so the
        # host receives the same message the CLI reports for the same input and
        # this server keeps answering later calls. RunnerError carries the
        # shared operations' own rejections, such as a status query outside a
        # Harness Project Root or incomplete Git diagnostics arguments.
        return _result_response(
            request_id,
            {"content": [{"type": "text", "text": str(error)}], "isError": True},
        )
    return _result_response(
        request_id,
        {
            # The text is the CLI's YAML rendering of the same document.
            "content":           [
                {"type": "text", "text": yaml.safe_dump(document, sort_keys=False, allow_unicode=True)}
            ],
            "structuredContent": document,
            "isError":           result.failed,
        },
    )


def _respond(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Use the shared MCP dispatcher with this host's existing caller binding."""
    from agent_swarm.mcp import respond

    return respond(message, _tool_documents, _tool_call_response, SERVER_INFO)


# Native dialog text for each reviewed operation, by language. Each entry is
# (action, what the change does, what Accept applies). Hosts may hide the
# dialog title, so the message itself repeats these.
REVIEW_TEXT = {
    'en': {
        'approved_recovery':   ('add Task execution time',
                                'add {minutes} minutes of execution time{resume}{restore}',
                                'the added time and the shown repair apply to the original Task and Session'),
        'role_organization':   ('change child-role configuration',
                                'change {fields}',
                                'only the reviewed child-role configuration change is saved'),
        'runtime_connections': ('save Runtime connections',
                                'change {fields}',
                                'only the reviewed user Runtime connection change is saved'),
        'retire':              ('retire an Agent',
                                'retire the shown stopped Agent; its Session, Trace, parent relationships '
                                'and Worktree are kept',
                                'the Agent is retired and remains only as history'),
        'replace':             ('replace an Agent',
                                'retire the shown stopped Agent for {replacement}; its Session, Trace, '
                                'parent relationships and Worktree are kept',
                                'the Agent is retired and its replacement continues its seat'),
        'labels':              {'heading': 'GraphTraj review: ', 'requester': 'Requested by: ',
                                'target': 'Target: ', 'change': 'Change: ', 'accept': 'Accept: ',
                                'decline': 'Decline: ', 'full': 'Full request (authoritative):'},
        'main':                'the current Main session',
        'parent':              ' (parent {0})',
        'resume':              ', then resume its Session',
        'restore':             ', and reactivate its Task',
        'roles':               'this project\'s child-role configuration (roles.yml)',
        'connections':         'the user Runtime connection file {0}',
        'replacement':         'Task {task_id} Team {team_ordinal} {role} seat {member}',
        'more':                ' and {0} more',
        'declined':            'nothing is written and the call returns a refusal',
    },
    'zh': {
        'approved_recovery':   ('追加 Task 执行时间',
                                '追加 {minutes} 分钟执行时间{resume}{restore}',
                                '对原 Task 和 Session 应用所示的追加时间与修复'),
        'role_organization':   ('修改子角色配置',
                                '修改 {fields}',
                                '只保存所示的子角色配置变更'),
        'runtime_connections': ('保存 Runtime 连接',
                                '修改 {fields}',
                                '只保存所示的用户 Runtime 连接变更'),
        'retire':              ('清退 Agent',
                                '清退所示已停止的 Agent；其 Session、Trace、父子关系和 Worktree 保留',
                                '该 Agent 被清退，只作为历史记录保留'),
        'replace':             ('替换 Agent',
                                '清退所示已停止的 Agent，由{replacement}接替；其 Session、Trace、父子关系和 Worktree 保留',
                                '该 Agent 被清退，由替换者继续其席位'),
        'labels':              {'heading': 'GraphTraj 审查：', 'requester': '请求者：',
                                'target': '对象：', 'change': '内容：', 'accept': '接受（Accept）：',
                                'decline': '拒绝（Decline）：', 'full': '完整请求（以此为准）：'},
        'main':                '当前 Main 会话',
        'parent':              '（父级 {0}）',
        'resume':              '，并恢复其 Session',
        'restore':             '，并重新激活其 Task',
        'roles':               '本项目的子角色配置（roles.yml）',
        'connections':         '用户 Runtime 连接文件 {0}',
        'replacement':         ' Task {task_id} 第 {team_ordinal} 组 {role} 席位 {member} ',
        'more':                ' 等 {0} 项',
        'declined':            '不写入任何变更，本次调用返回拒绝',
    },
}


def review_language() -> str:
    """Return the review dialog language from the user's message locale.

    The first nonempty of ``LANGUAGE`` (its first entry), ``LC_ALL``,
    ``LC_MESSAGES`` and ``LANG`` decides, as in gettext. Chinese locales
    (``zh``, ``zh_CN`` ...) select ``'zh'``; every other value, or none,
    selects the default ``'en'``.
    """
    for name in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(name, '').split(':')[0]
        if value:
            return 'zh' if value.lower().startswith('zh') else 'en'
    return 'en'


def review_message(proposal: dict, operation: str, summary: dict) -> tuple[str, str]:
    """Return the dialog heading and the message a host shows for one review.

    The message names the requester, the operation, its target and what
    Accept and Decline each do, in the user's language, before the full
    reviewed request on its last line. A host that truncates the message
    still shows the readable lines first.
    """
    text = REVIEW_TEXT[review_language()]
    action, change, accept = text[operation]
    labels  = text['labels']
    request = summary['request']
    fields  = [item['field'] for item in summary['changes']]
    listed  = ', '.join(fields[:5]) + (text['more'].format(len(fields) - 5) if len(fields) > 5 else '')

    # Each operation names its own target and change detail.
    if operation in ('retire', 'replace'):
        target = request['alias'] + (text['parent'].format(proposal['parent']) if proposal.get('parent') else '')
    elif operation == 'approved_recovery':
        target = request.get('alias', '')
    elif operation == 'role_organization':
        target = text['roles']
    else:
        target = text['connections'].format(request.get('path'))
    change = change.format(
        minutes     = request.get('additional_minutes', 0),
        resume      = text['resume'] if request.get('resume') else '',
        restore     = text['restore'] if request.get('restore_active') else '',
        fields      = listed,
        replacement = (text['replacement'].format_map({key: request['registration'].get(key)
                       for key in ('task_id', 'team_ordinal', 'role', 'member')})
                       if 'registration' in request else ''),
    )

    heading = labels['heading'] + action
    lines   = [
        heading,
        labels['requester'] + (proposal.get('caller') or text['main']),
        labels['target'] + target,
        labels['change'] + change,
        labels['accept'] + accept,
        labels['decline'] + text['declined'],
        labels['full'],
        json.dumps(summary, ensure_ascii=False),
    ]
    return heading, '\n'.join(lines)


def elicit_review(
    input_stream: TextIO, output_stream: TextIO, proposal: dict, call_id: Any, feature: str,
    accepted: Callable[[dict], bool],
) -> dict:
    """Keep the change pending until the client's strict native review response arrives.

    The client's own elicitation handling decides; ``accepted`` checks the
    accept result for what that client's native decision requires.
    Decline and cancel refuse; any other answer or a disconnect raises.
    The dialog names the reviewed operation: a retirement or replacement
    proposal names itself, otherwise ``feature`` does.
    """
    from graphtraj.execution.approved_recovery import _differences

    request_id = 'recovery-' + uuid.uuid4().hex
    # A connection save reviews the user catalog file, not a request document.
    reviewed  = proposal.get('request', {'scope': proposal.get('scope'), 'path': proposal.get('path')})
    summary   = {'request': reviewed,
                 'changes': _differences(proposal['before'], proposal['after']),
                 **({'authority': proposal['authority']} if 'authority' in proposal else {})}
    operation = reviewed.get('operation')
    title, message = review_message(
        proposal,
        operation if operation in ('retire', 'replace')
        else feature if feature in ('role_organization', 'runtime_connections') else 'approved_recovery',
        summary,
    )
    request = {'jsonrpc': '2.0', 'id': request_id, 'method': 'elicitation/create',
               'params': {
                   'mode': 'form',
                   'message': message,
                   'requestedSchema': {'type': 'object', 'properties': {}},
                   '_meta': {
                       'codex_request_type': 'approval_request',
                       'codex_approval_kind': 'mcp_tool_call',
                       'codex_strict_auto_review': True,
                       'codex_sensitive_action': True,
                       'tool_name': 'tasks',
                       'tool_title': title,
                       'tool_description': message,
                       'tool_params': {'action': 'execute', 'feature': feature,
                                       'arguments': reviewed},
                   },
               }}
    output_stream.write(json.dumps(request, ensure_ascii=False) + '\n')
    output_stream.flush()
    while line := input_stream.readline():
        response = json.loads(line)
        if not isinstance(response, dict):
            raise RunnerError('native-approval-unavailable', 'Invalid native recovery response.')
        if response.get('method') == 'notifications/cancelled':
            if response.get('params', {}).get('requestId') in (call_id, request_id):
                raise RunnerError('recovery-denied', 'Native recovery review was cancelled.')
            continue
        if 'method' in response:
            # Do not run another mutation while the reviewed snapshot waits.
            if 'id' in response:
                reply = (_result_response(response['id'], {}) if response['method'] == 'ping'
                         else _error_response(response['id'], -32000, 'Recovery review is pending.'))
                output_stream.write(json.dumps(reply, ensure_ascii=False) + '\n')
                output_stream.flush()
            continue
        if response.get('id') != request_id or 'error' in response:
            raise RunnerError('native-approval-unavailable', 'Native recovery review did not return a decision.')
        result = response.get('result', {})
        if not isinstance(result, dict):
            raise RunnerError('native-approval-unavailable', 'Invalid native recovery decision.')
        metadata = result.get('_meta') or {}
        if not isinstance(metadata, dict):
            raise RunnerError('native-approval-unavailable', 'Invalid native recovery metadata.')
        if result.get('action') in ('decline', 'cancel'):
            return {'decision': 'decline', 'rationale': metadata.get('message', 'Native review refused this change.')}
        if result.get('action') == 'accept' and accepted(result):
            return {'decision': 'accept'}
        raise RunnerError('native-approval-unavailable', 'Recovery requires an actual native approval decision.')
    raise RunnerError('native-approval-unavailable', 'Native recovery review disconnected before deciding.')


def serve(input_stream: TextIO, output_stream: TextIO) -> None:
    """Serve tools and bind native review for recovery and child-role changes."""
    from agent_swarm.mcp import serve as serve_stdio
    from graphtraj.runtimes.runtime_adapter import recovery_review

    capabilities = {}

    def review(proposal: dict, call_id: Any, feature: str) -> dict:
        """Accept only Codex's actual auto_review decision."""
        return elicit_review(input_stream, output_stream, proposal, call_id, feature,
                             lambda result: result.get('content') == {}
                             and (result.get('_meta') or {}).get('approvals_reviewer') == 'auto_review')

    def respond(message: Mapping[str, Any]) -> dict | None:
        """Bind these direct Codex mutations to their existing client review channel."""
        nonlocal capabilities
        params = message.get('params', {})
        if message.get('method') == 'initialize':
            capabilities = params.get('capabilities', {}) if isinstance(params, dict) else {}
        if not isinstance(params, dict):
            return _respond(message)
        arguments = params.get('arguments', {})
        metadata = params.get('_meta', {})
        elicitation = capabilities.get('elicitation') if isinstance(capabilities, dict) else None
        if (message.get('method') == 'tools/call' and params.get('name') == 'tasks'
                and isinstance(arguments, dict) and arguments.get('action') == 'execute'
                and arguments.get('feature') in {'approved_recovery', 'role_organization'}
                and isinstance(metadata, dict) and isinstance(metadata.get('threadId'), str)
                and isinstance(elicitation, dict) and (not elicitation or 'form' in elicitation)
                and 'GRAPHTRAJ_CLI_CONNECTION' not in os.environ):
            with recovery_review(lambda proposal: review(proposal, message['id'], arguments['feature'])):
                return _respond(message)
        return _respond(message)

    serve_stdio(input_stream, output_stream, respond)


def main() -> None:
    """Run the MCP stdio server installed as the ``graphtraj-mcp`` command."""
    from agent_swarm.connection import client_native_context

    if 'GRAPHTRAJ_CLI_CONNECTION' in os.environ:
        # A DSH host names its native Session only through its own environment;
        # the hosted CLI binding checks that Session against this channel.
        native = client_native_context()
        if native is not None and native['runtime'] == 'dsh':
            os.environ['GRAPHTRAJ_NATIVE_RUNTIME'] = 'dsh'
    serve(sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
