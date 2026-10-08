"""Observe a root Agent's recorded owning host without sending it input."""

from __future__ import annotations

import math
from pathlib import Path

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter
from graphtraj.workspace.runner_project import discover_runner_directory


def parent_status(cwd: Path, timeout_seconds: float = 0, *, include_hooks: bool = False) -> dict:
    """Read the actual host parent, optionally waiting a finite interval for idle.

    Only the root child can wait: Main cannot synchronously wait for its own
    turn to end. No recipient, connection or identity comes from arguments.
    """
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds < 0):
        raise RunnerError('invalid-input', 'timeout_seconds must be finite and nonnegative.')
    runner = discover_runner_directory(cwd)
    alias = caller_alias(runner)
    if alias is None:
        raise RunnerError('authority-denied', 'Only a root Agent may observe its owning host parent.')
    mapping, _ = read_alias_mapping(runner, alias)
    connection = mapping.get('parent_connection')
    if mapping.get('parent') is not None or not isinstance(connection, dict):
        raise RunnerError('operation-unavailable', 'This Agent has no recorded Runtime host parent.')
    adapter = select_runtime_adapter(connection['runtime'])
    observe = getattr(adapter, 'parent_host_status', None)
    if observe is None:
        raise RunnerError('operation-unavailable', 'This Runtime cannot observe its owning host.')
    if include_hooks and connection['runtime'] != 'codex':
        raise RunnerError('unsupported-runtime', 'Native hook diagnostics currently require Codex.')
    options = {'include_hooks': True} if include_hooks else {}
    return {'alias': alias, **observe(connection, timeout_seconds, **options)}
