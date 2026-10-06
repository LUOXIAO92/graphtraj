"""Session-scoped CLI transport over the existing Worker's file connection."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping

from graphtraj.execution.runner_connection import connection_operation, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    process_caller_alias, read_alias_mapping, runtime_caller, require_execution_allowed,
)
from graphtraj.execution.runner_heartbeat import ownership_is_held
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.tools import ToolResult
from graphtraj.runtimes.runtime_adapter import recovery_review
from graphtraj.workspace.runner_project import discover_runner_directory


CONNECTION_ENV = 'GRAPHTRAJ_CLI_CONNECTION'


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
    authenticate: Callable[[int], None] | None = None,
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
        directory = runner.parent / 'cli'
    directory.mkdir(parents=True, exist_ok=True)

    def verify_writer(pid: int) -> None:
        """Require this channel's live Session to own the kernel-observed writer."""
        if authenticate is not None:
            mapping, session_directory = read_alias_mapping(runner, alias)
            require_execution_allowed(runner, alias, mapping)
            if not ownership_is_held(session_directory, mapping['worker_pid']):
                raise RunnerError('authority-denied', 'The bound host no longer owns this Agent.')
            authenticate(pid)
            return
        if process_caller_alias(runner, pid) != alias:
            raise RunnerError('authority-denied', 'The CLI request is not owned by this live Session.')

    def operate(document: dict) -> dict:
        """Bind verified identity before entering the same gateway as native tools."""
        if (not isinstance(document, dict) or set(document) != {'cwd', 'request'}
                or not _caller_in_scope(document['cwd'], root, runner, alias)):
            raise RunnerError(
                'invalid-config',
                "Agent Runner must be invoked from the Harness Project Root or this Session's Worktree.",
            )
        with runtime_caller(runner, alias), recovery_review(recovery_reviewer):
            result = handle_request(document['request'], cwd=root, allowed_features=allowed_features)
        return {'document': result.document, 'failed': result.failed}

    with worker_connection(directory, operate, authenticate=verify_writer) as address:
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
