"""Session-scoped CLI transport over the existing Worker's file connection."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping

from graphtraj.execution.runner_connection import connection_operation, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import process_caller_alias, runtime_caller
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.tools import ToolResult
from graphtraj.runtimes.runtime_adapter import recovery_review
from graphtraj.workspace.runner_project import discover_runner_directory


CONNECTION_ENV = 'GRAPHTRAJ_CLI_CONNECTION'


@contextmanager
def cli_connection(
    root: Path,
    alias: str,
    allowed_features: Collection[str],
    recovery_reviewer: Callable[[dict], dict] | None = None,
) -> Iterator[str]:
    """Serve one Session using its actual ownership and selected approval route.

    Only this ephemeral directory is granted to the Session. The surrounding
    private tree and other Sessions' channels remain denied. No control records
    or caller-selectable identities are published in the directory.
    """
    runner = discover_runner_directory(root)
    directory = runner.parent / 'cli'
    directory.mkdir(parents=True, exist_ok=True)

    def authenticate(pid: int) -> None:
        """Require this channel's live Session to own the kernel-observed writer."""
        if process_caller_alias(runner, pid) != alias:
            raise RunnerError('authority-denied', 'The CLI request is not owned by this live Session.')

    def operate(document: dict) -> dict:
        """Bind verified identity before entering the same gateway as native tools."""
        if (not isinstance(document, dict) or set(document) != {'cwd', 'request'}
                or document['cwd'] != str(root)):
            raise RunnerError('invalid-config', 'Agent Runner must be invoked from the Harness Project Root.')
        with runtime_caller(runner, alias), recovery_review(recovery_reviewer):
            result = handle_request(document['request'], cwd=root, allowed_features=allowed_features)
        return {'document': result.document, 'failed': result.failed}

    with worker_connection(directory, operate, authenticate=authenticate) as address:
        yield address


def forward_cli(feature: str, arguments: dict, cwd: Path) -> ToolResult | None:
    """Forward only when a host channel is present; a failed channel never falls back.

    The environment locates a channel but grants no identity. Removing it leaves
    ordinary CLI identity checks in place, including inaccessible-record denial.
    """
    return forward_request({'action': 'execute', 'feature': feature, 'arguments': arguments}, cwd)


def forward_request(request: Mapping[str, Any], cwd: Path) -> ToolResult | None:
    """Forward the public discovery/operation envelope over the same bound channel."""
    address = os.environ.get(CONNECTION_ENV)
    if address is None:
        return None
    if not address:
        raise RunnerError('operation-unavailable', 'The Session CLI host connection is unavailable.')
    response = connection_operation(address, {
        'cwd': str(cwd.resolve()),
        'request': request,
    }, authenticate=True)
    return ToolResult(response['document'], failed=response['failed'])
