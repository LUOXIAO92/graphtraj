"""Integration Worktree assignments for ordinary registered task execution."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_directory as project_runner_directory

from pathlib import Path
from typing import Any

import yaml

from graphtraj.configuration.project_configuration import ProjectConfiguration
from graphtraj.execution.runner_batch import read_session_task
from graphtraj.execution.runner_models import RunnerError, Task
from graphtraj.execution.runner_status import (
    _terminal_unestablished_launch, read_alias_mapping, require_execution_allowed,
    require_stopped_subtree, retained_session_directories,
)
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.workspace.runner_project import run_git


SUPERSEDED_RESOLVER = 'A later resolver replaced this Session; it has no active conflict assignment.'


def _latest_conflict(events: list[dict], task_id: str) -> dict | None:
    """Return the Task's latest conflict assignment, if it has one."""
    return next((event for event in reversed(events)
                 if event.get('task_id') == task_id
                 and event['event'] == 'task-integration-conflict-started'), None)


def superseded_resolvers(events: list[dict], task_id: str) -> list[str]:
    """Return the established resolvers the latest re-dispatch replaced.

    One resolver works at a time; these keep their Session, seat and stop, and
    may still deliver reports, but no longer hold the conflict assignment.
    """
    conflict = _latest_conflict(events, task_id)
    return list(conflict.get('superseded_resolvers', ())) if conflict else []


def require_resolver_redispatch(
    configuration: ProjectConfiguration,
    record: dict,
    events: list[dict],
    task: Task,
    parent_alias: str | None,
) -> list[str]:
    """Admit another resolver for a retained conflict; return the Sessions it replaces.

    A terminated launch without native identity is retried with its same role
    and diagnosis; retained launch inputs also cover older failures whose
    integration event has no Session reference. An ended established Session
    admits a new entity whose role and diagnosis may differ: a stop or retirement
    stays bound to the old entity and is not bypassed by this one. A running or
    unconfirmed resolver, or a stopped caller, still refuses.
    """
    from graphtraj.execution.runner_retirement import _record_is_retired

    conflict = _latest_conflict(events, task.task_id)
    if conflict is None or conflict.get('parent') != parent_alias:
        raise ValueError('Retry must retain the original resolution actual parent')
    runner = project_runner_directory(configuration.harness_root)
    if parent_alias is not None:
        require_execution_allowed(runner, parent_alias, read_alias_mapping(runner, parent_alias)[0])
    failed, replaced = [], []
    for launch_file in [*(runner / 'sessions').glob('*/launch.yml'),
                        *(directory / 'launch.yml' for directory in retained_session_directories(runner))]:
        if not launch_file.is_file():
            continue
        launch = yaml.safe_load(launch_file.read_text(encoding='utf-8'))
        mapping = launch['mapping']
        if (mapping.get('task_id') != task.task_id
                or mapping.get('team_generation') != record['active_team_ordinal']
                or mapping.get('worktree_path') != str(configuration.integration_worktree)):
            continue
        if mapping.get('parent') != parent_alias:
            raise ValueError('Retry requires earlier resolver launches of the same actual parent')
        if _terminal_unestablished_launch(launch_file.parent):
            retained = read_session_task(mapping, configuration.harness_root)
            require_execution_allowed(runner, mapping['alias'], mapping)
            if ((retained.role_reference or retained.role) == conflict['role_reference']
                    and retained.instruction == conflict['instruction']):
                failed.append(launch_file)
        elif _record_is_retired(launch_file.parent):
            replaced.append(mapping['alias'])
        elif (launch_file.parent / 'mapping.yml').is_file():
            require_stopped_subtree(runner, mapping['alias'], operation='dispatching another resolver')
            replaced.append(mapping['alias'])
        else:
            raise ValueError('Retry requires earlier resolver launches to have confirmably ended')
    if not failed and not replaced:
        raise ValueError('Retry requires a retained terminal resolver launch or an ended resolver Session')
    return sorted(replaced)


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
    )) if event.get('task_id') == task.task_id
        and event['event'] == 'task-integration-conflict-started'), None)
    if (conflict is None or conflict['event'] != 'task-integration-conflict-started'
            or conflict.get('parent') != parent_alias
            or conflict.get('role_reference') != (task.role_reference or task.role)
            or conflict.get('instruction') != task.instruction
            or run_git(project.integration_worktree, 'rev-parse', 'HEAD') != conflict['dev_commit']):
        raise RunnerError('authority-denied', 'Dispatch does not match the authorized integration assignment.')
    prompt = (
        task.task_content
        + f"\nFixed incoming candidate: {conflict['candidate']}\nExisting dev state: {conflict['dev_before']}"
        + f"\nCurrent dev commit: {conflict['dev_commit']}\nDiagnosis: {conflict['diagnosis']}\n"
        + 'Resolve only this conflict, commit the reconciliation and submit its result through Runner. '
          'The actual parent must decide the submitted version before integration can complete.\n'
        + '\n'.join((project.harness_root / ref).read_text() for ref in conflict['evidence_refs'])
    )
    return project.integration_worktree, prompt
