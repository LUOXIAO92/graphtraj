"""Session-scoped CLI transport over the existing Worker's file connection."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import cli_directory

import os
import math
import sys
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping

from graphtraj.execution.runner_connection import connection_operation, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_process import OPERATION_TIMEOUT_SECONDS
from graphtraj.execution.runner_status import process_caller_alias, read_alias_mapping, runtime_caller
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.tools import ToolResult
from graphtraj.runtimes.runtime_adapter import recovery_review
from graphtraj.workspace.runner_project import discover_runner_directory


CONNECTION_ENV = 'GRAPHTRAJ_CLI_CONNECTION'
_SERVICE = {'executable': sys.executable, 'module': __file__,
            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _caller_in_scope(document_cwd: Any, root: Path, runner: Path, alias: str) -> bool:
    """Whether one caller directory is the bound project or this Session's Worktree.

    A restricted Runtime cannot read the Harness Project Root, so its public CLI
    runs from the Worktree the Runner recorded for that Session. That recorded
    directory and paths inside it are the Session's own project scope; every
    other directory, including another project's, stays refused.
    """
    if not isinstance(document_cwd, str):
        return False
    if document_cwd == str(root):
        return True
    try:
        mapping, _ = read_alias_mapping(runner, alias)
    except RunnerError:
        return False
    worktree = mapping.get('worktree_path')
    if not isinstance(worktree, str) or not worktree:
        return False
    try:
        return Path(document_cwd).resolve().is_relative_to(Path(worktree).resolve())
    except (OSError, ValueError):
        return False


@contextmanager
def cli_connection(
    root: Path,
    alias: str,
    allowed_features: Collection[str],
    recovery_reviewer: Callable[[dict], dict] | None = None,
    directory: Path | None = None,
    native_context: Callable[[], dict | None] | None = None,
    native_authorizer: Callable[[dict, dict], tuple[str | None, Collection[str]]] | None = None,
) -> Iterator[str]:
    """Serve one Session using its actual ownership and selected approval route.

    Only this ephemeral directory is granted to the Session. The surrounding
    private tree and other Sessions' channels remain denied. No control records
    or caller-selectable identities are published in the directory. A Runtime
    whose sandbox only permits writing inside its own Worktree passes that
    sandbox-visible directory; every other caller keeps the shared location
    beside the Runner records.
    """
    runner = discover_runner_directory(root)
    if directory is None:
        directory = cli_directory(root)
    directory.mkdir(parents=True, exist_ok=True)

    def authenticate(pid: int) -> None:
        """Require this channel's live Session to own the kernel-observed writer."""
        if process_caller_alias(runner, pid) != alias:
            raise RunnerError('authority-denied', 'The CLI request is not owned by this live Session.')

    def operate(document: dict) -> dict:
        """Bind verified identity before entering the same gateway as native tools."""
        fields = {'cwd', 'request'} | ({'native'} if native_context is not None else set())
        if (not isinstance(document, dict) or set(document) != fields
                or not _caller_in_scope(document['cwd'], root, runner, alias)):
            raise RunnerError(
                'invalid-config',
                "Agent Runner must be invoked from the Harness Project Root or this Session's Worktree.",
            )
        identity, features = alias, allowed_features
        if native_authorizer is not None:
            identity, features = native_authorizer(document.get('native'), document['request'])
        elif native_context is not None:
            from agent_swarm.connection import verify_native_context
            from agent_swarm import AgentsError

            try:
                verify_native_context(document['native'], native_context())
            except AgentsError as error:
                raise RunnerError(error.code, error.message) from error
        with runtime_caller(runner, identity), recovery_review(recovery_reviewer):
            result = handle_request(document['request'], cwd=root, allowed_features=features)
        if document['request'].get('action') == 'discover' and not result.failed:
            result.document['service'] = {'host': _SERVICE}
        return {'document': result.document, 'failed': result.failed}

    with worker_connection(directory, operate, authenticate=authenticate) as address:
        yield address


def forward_cli(feature: str, arguments: dict, cwd: Path) -> ToolResult | None:
    """Forward only when a host channel is present; a failed channel never falls back.

    The environment locates a channel but grants no identity. Removing it leaves
    ordinary CLI identity checks in place, including inaccessible-record denial.
    """
    return forward_request({'action': 'execute', 'feature': feature, 'arguments': arguments}, cwd)


def forward_request(
    request: Mapping[str, Any], cwd: Path, *, native_context: dict | None = None,
) -> ToolResult | None:
    """Forward the public discovery/operation envelope over the same bound channel."""
    address = os.environ.get(CONNECTION_ENV)
    if address is None:
        return None
    if not address:
        raise RunnerError('operation-unavailable', 'The Session CLI host connection is unavailable.')
    response_timeout = OPERATION_TIMEOUT_SECONDS
    if request.get('action') == 'execute' and request.get('feature') == 'parent_status':
        arguments = request.get('arguments', {})
        observation = arguments.get('timeout_seconds', 0) if isinstance(arguments, Mapping) else 0
        # Invalid arguments still reach the authenticated gateway for rejection;
        # they must never extend the client's transport deadline.
        if type(observation) in (int, float) and math.isfinite(observation) and observation >= 0:
            response_timeout += observation
    # Recovery and a continuation can include Session startup, and a result
    # or notified report reaches the direct parent; none has a fixed duration,
    # so once the host accepts one its own reply is awaited.
    long_operation = (request.get('action') == 'execute'
                      and (request.get('feature') in {'approved_recovery', 'submit_result', 'send_instruction'}
                           or request.get('feature') == 'submit_report'
                           and isinstance(request.get('arguments'), Mapping)
                           and request['arguments'].get('notify_parent') is True))
    from agent_swarm.connection import client_native_context

    native = native_context if native_context is not None else client_native_context()
    response = connection_operation(address, {
        'cwd': str(cwd.resolve()),
        'request': request,
        **({'native': native} if native is not None else {}),
    }, authenticate=True, response_timeout=response_timeout, await_accepted=long_operation)
    return ToolResult(response['document'], failed=response['failed'])
