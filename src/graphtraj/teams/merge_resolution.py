"""Integration Worktree assignments for ordinary registered task execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from graphtraj.configuration.project_configuration import ProjectConfiguration
from graphtraj.execution.runner_batch import read_session_task
from graphtraj.execution.runner_models import RunnerError, Task
from graphtraj.execution.runner_status import _terminal_unestablished_launch, require_execution_allowed
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.workspace.runner_project import run_git


def require_unestablished_resolution(
    configuration: ProjectConfiguration,
    record: dict,
    events: list[dict],
    task: Task,
    parent_alias: str | None,
) -> None:
    """Permit retry only for terminated resolver launches without native identity.

    Retained launch inputs also cover older failures whose integration event
    has no Session reference. Established Sessions still need ordinary recovery
    or replacement; neither their identity nor a stop may be bypassed here.
    """
    conflict = next((event for event in reversed(events)
                     if event.get('ticket_id') == task.ticket_id
                     and event['event'] == 'ticket-integration-conflict-started'), None)
    if conflict is None or conflict.get('parent') != parent_alias:
        raise ValueError('Retry must retain the original resolution actual parent')
    runner = configuration.harness_root / '.graphtraj/runner'
    failed = []
    for launch_file in (runner / 'sessions').glob('*/launch.yml'):
        launch = yaml.safe_load(launch_file.read_text(encoding='utf-8'))
        mapping = launch['mapping']
        if (mapping.get('ticket_id') != task.ticket_id
                or mapping.get('team_generation') != record['active_team_ordinal']
                or mapping.get('worktree_path') != str(configuration.integration_worktree)):
            continue
        if (not _terminal_unestablished_launch(launch_file.parent)
                or mapping.get('parent') != parent_alias):
            raise ValueError('Retry requires confirmed terminal resolver launches without a Session')
        retained = read_session_task(mapping, configuration.harness_root)
        require_execution_allowed(runner, mapping['alias'], mapping)
        if ((retained.role_reference or retained.role) == conflict['role_reference']
                and retained.instruction == conflict['instruction']):
            failed.append(launch_file)
    if not failed:
        raise ValueError('Retry requires a retained terminal resolver launch without a Session')


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
        and event['event'] == 'ticket-integration-conflict-started'), None)
    if (conflict is None or conflict['event'] != 'ticket-integration-conflict-started'
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
