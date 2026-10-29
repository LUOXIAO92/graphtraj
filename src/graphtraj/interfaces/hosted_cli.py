"""Session-scoped CLI transport over the existing Worker's file connection."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import cli_directory
from graphtraj.configuration import project_configuration

import os
import sys
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping

from graphtraj.execution.runner_connection import connection_operation, worker_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import process_caller_alias, read_alias_mapping, runtime_caller
from graphtraj.interfaces.gateway import handle_request
from graphtraj.interfaces.tools import ToolResult
from graphtraj.runtimes.runtime_adapter import recovery_review
from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory


CONNECTION_ENV = 'GRAPHTRAJ_CLI_CONNECTION'
_SERVICE = {'executable': sys.executable, 'module': __file__,
            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'configuration_sha256': hashlib.sha256(Path(project_configuration.__file__).read_bytes()).hexdigest()}


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


def agents_dispatch(
    request: Mapping[str, Any], cwd: Path, *, native_context: dict | None = None,
) -> ToolResult:
    """Run one ``agents`` action over this process's bound channel, else in this project.

    Both MCP entries and the ``agents`` CLI use this one route, so a Task
    member's control stays in the host that verifies its caller.
    """
    envelope = {'action': 'execute', 'feature': 'agents', 'arguments': dict(request)}
    answer = forward_request(envelope, cwd, native_context=native_context)
    return answer if answer is not None else handle_request(envelope, cwd=cwd)


def agents_host(cwd: Path) -> Callable[[dict], Any] | None:
    """Claim the independent ``agents`` CLI only inside GraphTraj (``agent_swarm.hosts`` entry).

    A process bound to a Task channel, or a caller inside a Harness project,
    uses ``agents_dispatch``; anywhere else the CLI keeps its own owner. The
    environment only locates the channel; the host still verifies the caller.
    """
    if CONNECTION_ENV not in os.environ:
        try:
            discover_project_root(cwd)
        except RunnerError:
            return None

    def dispatch(request: dict) -> Any:
        """Report a host rejection in the CLI's own error shape."""
        from agent_swarm import AgentsError, AgentsResult
        from graphtraj.configuration.project_configuration import ProjectConfigurationError
        from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

        try:
            result = agents_dispatch(request, cwd)
        except (RunnerError, RuntimeAdapterError, ProjectConfigurationError) as error:
            raise AgentsError(getattr(error, 'code', 'operation-failed'), str(error)) from error
        document = result.document
        if result.failed and isinstance(document.get('diagnostic'), dict):
            # Name the entry so a checker can attribute a CLI status failure.
            document = {**document, 'diagnostic': {**document['diagnostic'], 'entry': 'cli'}}
        return AgentsResult(document, failed=result.failed)

    return dispatch


def forward_cli(feature: str, arguments: dict, cwd: Path) -> ToolResult | None:
    """Forward only when a host channel is present; a failed channel never falls back.

    The environment locates a channel but grants no identity. Removing it leaves
    ordinary CLI identity checks in place, including inaccessible-record denial.
    """
    return forward_request({'action': 'execute', 'feature': feature, 'arguments': arguments}, cwd)


def forward_request(
    request: Mapping[str, Any], cwd: Path, *, native_context: dict | None = None,
) -> ToolResult | None:
    """Forward the public discovery/operation envelope over the same bound channel.

    A process that also carries an independent agents connection is refused:
    which owner it belongs to is ambiguous.
    """
    address = os.environ.get(CONNECTION_ENV)
    if address is None:
        return None
    if 'AGENT_SWARM_CONNECTION' in os.environ:
        raise RunnerError('authority-denied', 'Both independent and GraphTraj connections are present.')
    if not address:
        raise RunnerError('operation-unavailable', 'The Session CLI host connection is unavailable.')
    # The host removes a request when it accepts it. Reads, status, interrupt,
    # recovery and writes have no fixed duration once accepted, so the owner's
    # own reply is awaited until it arrives or the host closes the channel.
    # Only a request the host never accepts ends at the ordinary deadline.
    from agent_swarm.connection import client_native_context

    native = native_context if native_context is not None else client_native_context()
    response = connection_operation(address, {
        'cwd': str(cwd.resolve()),
        'request': request,
        **({'native': native} if native is not None else {}),
    }, authenticate=True, await_accepted=True)
    return ToolResult(response['document'], failed=response['failed'])
