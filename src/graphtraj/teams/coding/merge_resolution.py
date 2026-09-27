"""Integration Worktree assignments for ordinary registered task execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from graphtraj.execution.runner_models import RunnerError, Task
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.workspace.runner_project import run_git


def integration_assignment(
    project: Any,
    task: Task,
    parent_alias: str | None,
) -> tuple[Path, str]:
    """Resolve the explicitly authorized conflict assignment from its retained event.

    Ordinary dispatch still checks role_tree and binds the actual parent. This
    assignment grants the configured Integration Worktree only to that selected
    task input, never to a role spelling or arbitrary swarm invocation.
    """
    conflict = next((event for event in reversed(read_worldline(
        project.state_directory, project.harness_root,
    )) if event.get('ticket_id') == task.ticket_id
        and event['kind'] == 'ticket-integration-conflict-started'), None)
    if (conflict is None or conflict['kind'] != 'ticket-integration-conflict-started'
            or conflict.get('parent') != parent_alias
            or conflict.get('role_reference') != (task.role_reference or task.role)
            or conflict.get('instruction') != task.instruction
            or run_git(project.integration_worktree, 'rev-parse', 'HEAD') != conflict['dev_commit']):
        raise RunnerError('authority-denied', 'Dispatch does not match the authorized integration assignment.')
    prompt = (
        task.ticket_content
        + f"\nFixed incoming candidate: {conflict['candidate']}\nExisting dev state: {conflict['dev_before']}"
        + f"\nCurrent dev commit: {conflict['dev_commit']}\nDiagnosis: {conflict['diagnosis']}\n"
        + 'Resolve only this conflict, commit the reconciliation and submit its result through Runner. '
          'The actual parent must decide the submitted version before integration can complete.\n'
        + '\n'.join((project.harness_root / ref).read_text() for ref in conflict['evidence_refs'])
    )
    return project.integration_worktree, prompt
