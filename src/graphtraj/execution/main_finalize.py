"""Check the current task through a GraphTraj-owned Main and its Runtime Adapter."""

from __future__ import annotations

import json
from contextvars import ContextVar
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.graph.ticket_graph import read_graph
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter
from graphtraj.workspace.runner_project import discover_runner_directory


if TYPE_CHECKING:
    from graphtraj.interfaces.local_tool import HostTool


finish_host: ContextVar[HostTool | None] = ContextVar('finish_host', default=None)


def bind_main_finalize(summary_issue: str | None, cwd: Path) -> dict[str, Any]:
    """Prepare a native hook on the caller's existing authenticated CLI channel."""
    host = finish_host.get()
    if host is None:
        raise RunnerError('unsupported-operation',
                          'finish-check requires an adopted owning HostTool CLI channel.')
    return host.prepare_finish_check(summary_issue)


def parse_check_result(text: str) -> dict[str, Any]:
    """Validate the checker result without interpreting or persisting task truth."""
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {'status', 'reason', 'nodes'}:
        raise ValueError('The completion checker must return status, reason and nodes.')
    if result['status'] not in ('completed', 'waiting', 'actionable', 'error'):
        raise ValueError('The completion checker returned an unknown status.')
    if not isinstance(result['reason'], str) or not result['reason'].strip():
        raise ValueError('The completion checker returned no reason.')
    nodes = result['nodes']
    if not isinstance(nodes, list) or any(not isinstance(n, str) or not n.strip() for n in nodes):
        raise ValueError('Completion nodes must be nonempty Ticket identifiers or URLs.')
    if result['status'] == 'actionable' and not nodes:
        raise ValueError('Actionable work must identify concrete unfinished nodes.')
    return result


PREFIX = '[GraphTraj hook: finish-check]'


def finish_check_exclusion(purpose: str) -> str | None:
    """Explain exclusion only for a registered member/checker purpose."""
    if purpose in ('member', 'checker'):
        return f'GraphTraj {purpose} does not run Main completion checks.'
    return None


def check_main_finalize(
    host: HostTool,
    connection: dict[str, Any],
    event: dict[str, Any],
    *,
    summary_issue: str | None = None,
) -> dict[str, Any]:
    """Check an adopted host's current task and return its native end decision.

    The owning host invokes this callback only while its hook is enabled. Its
    receiver displays start/outcome messages and its lifecycle consumes the
    returned decision on the same conversation. Native handles stay inside the
    Adapter; the registered GraphTraj purpose decides who may run a checker.
    """
    from graphtraj.execution.runner_status import read_alias_mapping, require_execution_allowed

    adapter = None
    # Unverifiable lifecycle metadata must fail visibly without requesting a new turn.
    context = {'continued': True}
    child = None

    def announce(outcome: str, reason: str) -> None:
        """Deliver through the existing owning host, never only a private log."""
        host.receiver({'source': 'graphtraj', 'alias': host.alias or 'unregistered',
                       'event': 'finish-check', 'message': f'{PREFIX} {outcome}: {reason}'})

    def respond(result: dict | None, reason: str = '') -> dict:
        """Deliver the visible outcome before returning the native decision."""
        outcome = ('skip' if result is None else
                   {'completed': 'pass', 'waiting': 'pass',
                    'actionable': 'continue', 'error': 'failure'}[result['status']])
        reply = adapter.finalize_response(result, context['continued'])
        announce(outcome, reason if result is None else result['reason'])
        return reply

    try:
        announce('start', 'Checking completion eligibility.')
        if host.closed or not host.alias:
            raise RunnerError('authority-denied', 'The owning host has no active GraphTraj identity.')
        runner = discover_runner_directory(host.cwd)
        mapping, _ = read_alias_mapping(runner, host.alias)
        require_execution_allowed(runner, host.alias, mapping)
        purpose = mapping.get('purpose', 'member')
        excluded = finish_check_exclusion(purpose)
        if excluded is not None:
            announce('skip', excluded)
            return {'status': 'skip', 'reason': excluded}
        if purpose != 'main':
            raise RunnerError('authority-denied', 'Unknown GraphTraj Agent purpose.')
        adapter = select_runtime_adapter(mapping['runtime'])
        if connection.get('runtime') != mapping['runtime']:
            raise ValueError('The owning connection does not match the registered Runtime.')
        binding = {'runtime': mapping['runtime'], 'connection': dict(connection),
                   'cwd': str(host.cwd)}
        def execution_allowed() -> None:
            """Cancel checker execution when either Runner or its owning host stops."""
            if host.closed:
                raise RunnerError('host-closed', 'The owning host attachment closed.')
            require_execution_allowed(runner, host.alias, mapping)

        binding['execution_allowed'] = execution_allowed
        binding['session'] = adapter.verify_finalize_main(binding['connection'])
        context = adapter.finalize_event(binding, event)
        if context is None:
            context = {'continued': False}
            return respond(None, 'The host reports an unrelated event or a stopped or changed turn.')
        if not isinstance(context, dict) or type(context.get('continued')) is not bool:
            raise ValueError('The Adapter did not provide valid lifecycle state.')
        configuration = load_project_configuration(host.cwd)
        graph = read_graph(configuration.state)
        prompt = files('graphtraj').joinpath('prompts/main_finalize_check.md').read_text(encoding='utf-8')
        prompt += '\n\n' + json.dumps({
            'summary_issue_hint': summary_issue, 'task_graph_hint': graph,
        }, ensure_ascii=False)
        child = host.register_checker(host.receiver)
        # The child callback supplies GraphTraj identity, not its native handle.
        child.allowed_features = {'agent_identity', 'ticket_graph', 'alias_status'}
        binding['checker_tool'] = child
        _, directory = read_alias_mapping(runner, child.alias)
        native_handle = None

        def created(handle: str) -> None:
            """Retain the Adapter's fresh execution association on this checker."""
            nonlocal native_handle
            if native_handle is not None or not isinstance(handle, str) or not handle:
                raise ValueError('The Adapter must create exactly one checker execution.')
            native_handle = handle
            write_yaml_durably(directory / 'native.yml', {
                'runtime': mapping['runtime'], 'session': handle, 'parent': host.alias,
            })

        native = adapter.check_main_finalize(binding, context, prompt, created)
        # An actual stop remains effective, including while the checker runs.
        require_execution_allowed(runner, host.alias, mapping)
        if native is None:
            return respond(None, 'The owning host stopped or changed its turn during checking.')
        if native_handle is None or native.get('session') != native_handle:
            raise ValueError('The completion result does not belong to the registered checker.')
        write_yaml_durably(directory / 'execution.yml', native)
        result = parse_check_result(native['output'])
        return respond(result)
    except (KeyboardInterrupt, SystemExit):
        announce('skip', 'The owning execution was interrupted; no continuation is requested.')
        raise
    except Exception as error:
        if isinstance(error, RunnerError) and error.code in ('subtree-stopped', 'session-retired', 'host-closed'):
            announce('skip', str(error))
            raise
        reason = f'finish-check failed: {error}'
        # If delivery itself failed, the raised error must reach the owning
        # lifecycle's error surface; a successful end response would hide it.
        try:
            announce('failure', reason)
        except Exception as delivery_error:
            raise RunnerError('operation-failed',
                              f'{PREFIX} failure: {reason}; delivery failed: {delivery_error}') from error
        if adapter is None:
            raise RunnerError('operation-failed', f'{PREFIX} failure: {reason}') from error
        continued = not isinstance(context, dict) or context.get('continued') is not False
        try:
            return adapter.finalize_response({'status': 'error', 'reason': reason, 'nodes': []}, continued)
        except Exception as response_error:
            raise RunnerError('operation-failed',
                              f'{PREFIX} failure: {reason}; native response failed: {response_error}') from error
    finally:
        if child is not None:
            child.close()
