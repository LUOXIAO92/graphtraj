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

import copy
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


# Native dialog text for each reviewed operation, by language. Claude Code
# shows only the first three message lines before folding the rest, so each
# operation has (action, change summary, what Accept applies) kept short.
REVIEW_TEXT = {
    'en': {
        'approved_recovery':   ('add execution time to', 'add {minutes} min of execution time{resume}{restore}',
                                'apply the added time and repair'),
        'role_organization':   ('change child roles in', 'remove {removed}, add {added}, change {changed}: {fields}',
                                'save this change'),
        'runtime_connections': ('save Runtime connections in',
                                'models: remove {removed}, add {added}, change {changed}; other settings: {other}',
                                'save this file'),
        'retire':              ('retire', 'stopped Agent becomes history; Session, Trace and Worktree are kept',
                                'retire it now'),
        'replace':             ('replace', '{replacement} takes over; Session, Trace and Worktree are kept',
                                'retire and replace it now'),
        'heading':             'GraphTraj review: {action} {target} (requested by {requester})',
        'choices':             'Accept: {accept}. Decline: nothing is written.',
        'requester':           'Requested by: ',
        'target':              'Target: ',
        'full':                'Full request (authoritative):',
        'main':                'Main',
        'parent':              ' (parent {0})',
        'resume':              ', resume its Session',
        'restore':             ', reactivate its Task',
        'roles':               'roles.yml',
        'replacement':         'the {role} seat {member} of Task {task_id} Team {team_ordinal}',
    },
    'zh': {
        'approved_recovery':   ('追加执行时间', '追加 {minutes} 分钟{resume}{restore}',
                                '应用追加时间与修复'),
        'role_organization':   ('修改子角色配置', '删除 {removed} 项、新增 {added} 项、修改 {changed} 项：{fields}',
                                '保存此变更'),
        'runtime_connections': ('保存 Runtime 连接',
                                '模型删除 {removed} 个、新增 {added} 个、修改 {changed} 个；其他设置 {other} 项',
                                '保存此文件'),
        'retire':              ('清退 Agent', '已停止的 Agent 变为历史记录；Session、Trace、Worktree 保留',
                                '立即清退'),
        'replace':             ('替换 Agent', '由 Task {task_id} 第 {team_ordinal} 组 {role} 席位 {member} 接替；'
                                'Session、Trace、Worktree 保留', '立即清退并替换'),
        'heading':             'GraphTraj 审查：{action} {target}（{requester} 请求）',
        'choices':             'Accept：{accept}；Decline：不写入任何变更',
        'requester':           '请求者：',
        'target':              '对象：',
        'full':                '完整请求（以此为准）：',
        'main':                'Main',
        'parent':              '（父级 {0}）',
        'resume':              '，并恢复其 Session',
        'restore':             '，并重新激活其 Task',
        'roles':               'roles.yml',
        'replacement':         'Task {task_id} 第 {team_ordinal} 组 {role} 席位 {member}',
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


def _short(alias: str) -> str:
    """Shorten a long alias to its Task prefix and final seat for the first line.

    ``364-readable_review-handover0-engineer@engineer`` becomes
    ``364-…-engineer@engineer``; the full alias follows on a later line.
    """
    if len(alias) <= 32 or '-' not in alias:
        return alias
    return alias.split('-', 1)[0] + '-…-' + alias.rsplit('-', 1)[1]


def _models(catalog: Any) -> dict[tuple, Any]:
    """Return a connection catalog's models keyed by (entry, provider, model)."""
    found = {}
    for entry, runtime in ((catalog or {}).get('runtimes') or {}).items():
        for provider, settings in ((runtime or {}).get('providers') or {}).items():
            for model, value in ((settings or {}).get('models') or {}).items():
                found[(entry, provider, model)] = value
    return found


def _without_models(catalog: Any) -> Any:
    """Return a connection catalog copy whose providers list no models."""
    copied = copy.deepcopy(catalog or {})
    for runtime in (copied.get('runtimes') or {}).values():
        for settings in ((runtime or {}).get('providers') or {}).values():
            if isinstance(settings, dict):
                settings.pop('models', None)
    return copied


def review_message(proposal: dict, operation: str, summary: dict) -> tuple[str, str]:
    """Return the dialog heading and the message a host shows for one review.

    Lines 1-3 name the operation, target and requester, summarize the change
    with what it removes, and state what Accept and Decline do; a host that
    folds the rest still shows them. The full requester, the full target and
    the authoritative reviewed request follow.
    """
    from graphtraj.execution.approved_recovery import _differences

    text = REVIEW_TEXT[review_language()]
    action, change, accept = text[operation]
    request   = summary['request']
    requester = proposal.get('caller') or text['main']

    # Each operation names its own target; long aliases are shortened on line 1.
    if operation in ('retire', 'replace', 'approved_recovery'):
        target = request.get('alias', '')
        short  = _short(target)
        if proposal.get('parent'):
            target += text['parent'].format(proposal['parent'])
    elif operation == 'role_organization':
        target = short = text['roles']
    else:
        target = request.get('path') or ''
        short  = Path(target).name

    # Count what the change removes, adds and modifies.
    if operation == 'runtime_connections':
        before, after = _models(proposal['before']), _models(proposal['after'])
        counts = {'removed': len(before.keys() - after.keys()), 'added': len(after.keys() - before.keys()),
                  'changed': sum(before[key] != after[key] for key in before.keys() & after.keys()),
                  'other':   len(_differences(_without_models(proposal['before']),
                                              _without_models(proposal['after'])))}
    else:
        changes = summary['changes']
        fields  = [item['field'] for item in changes]
        counts  = {'removed': sum(item['actual'] is None for item in changes),
                   'added':   sum(item['expected'] is None for item in changes),
                   'changed': sum(item['expected'] is not None and item['actual'] is not None for item in changes),
                   'other':   0,
                   'fields':  ', '.join(fields[:2]) + (', …' if len(fields) > 2 else '')}
    registration = request.get('registration') or {}
    change = change.format(
        minutes     = request.get('additional_minutes', 0),
        resume      = text['resume'] if request.get('resume') else '',
        restore     = text['restore'] if request.get('restore_active') else '',
        replacement = text['replacement'].format_map({key: registration.get(key)
                      for key in ('task_id', 'team_ordinal', 'role', 'member')}),
        **{key: registration.get(key) for key in ('task_id', 'team_ordinal', 'role', 'member')},
        **{'fields': '', **counts},
    )

    heading = text['heading'].format(action=action, target=short, requester=_short(requester))
    lines   = [
        heading,
        change,
        text['choices'].format(accept=accept),
        text['requester'] + requester,
        text['target'] + target,
        text['full'],
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
