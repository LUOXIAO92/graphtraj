"""Register host-owned Agents in the existing Runner Session records."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import IO, Callable

from graphtraj.execution.runner_heartbeat import execution_start_lock, hold_ownership
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    read_alias_mapping, require_execution_allowed,
    owning_execution, session_occupied, require_host_adoption,
)
from graphtraj.workspace.runner_project import discover_runner_directory


def adopt_host_agent(
    root: Path,
    runtime: str,
    reviewer: Callable[[dict], dict],
    *,
    resume: str | None = None,
    replaces: str | None = None,
    parent: str | None = None,
) -> tuple[dict, IO[bytes]]:
    """Allocate or restore an Agent through an owning host's user authorization.

    This host API is not a model tool. The host supplies its actual reviewer;
    no request field, process ID or native conversation handle authorizes Main.
    For a checker the already-bound Main supplies its direct parent instead.
    Returns the recorded identity and its ownership lock, held until host close.
    """
    runner = discover_runner_directory(root)
    purpose = 'checker' if parent else 'main'
    if parent is None:
        require_host_adoption(runner)
    if not isinstance(runtime, str) or not runtime:
        raise RunnerError('invalid-input', 'The host must name its Runtime Adapter.')
    if resume and replaces:
        raise RunnerError('invalid-input', 'Choose restoration or replacement, not both.')
    proposal = {'operation': 'replace-agent' if replaces else 'restore-agent' if resume else 'adopt-main',
                'project': str(root), 'runtime': runtime, 'alias': resume,
                'purpose': purpose, 'parent': parent}
    if replaces:
        proposal['replaces'] = replaces
    decision = reviewer(proposal)
    if not isinstance(decision, dict) or decision.get('decision') != 'accept':
        raise RunnerError('authority-denied', 'The owning user did not authorize this Agent binding.')
    with execution_start_lock(runner):
        if parent:
            mapping, _ = read_alias_mapping(runner, parent)
            if mapping.get('purpose') != 'main':
                raise RunnerError('authority-denied', 'Only a registered Main may create a checker.')
            require_execution_allowed(runner, parent, mapping)
        if replaces:
            from graphtraj.execution.runner_retirement import retire_stopped_session
            from graphtraj.workspace.runner_project import discover_project

            old, _ = read_alias_mapping(runner, replaces)
            if not old.get('hosted') or old['purpose'] != purpose or old['parent'] != parent:
                raise RunnerError('authority-denied', 'Replacement must retain purpose and direct parent.')
            retire_stopped_session(discover_project(root, require_clean_integration=False), replaces)
        if resume:
            mapping, directory = read_alias_mapping(runner, resume)
            if (not mapping.get('hosted') or mapping['purpose'] != purpose
                    or mapping['runtime'] != runtime or mapping['parent'] != parent):
                raise RunnerError('authority-denied', 'Restoration cannot change an Agent binding.')
            require_execution_allowed(runner, resume, mapping)
            occupied = owning_execution(resume, directory, mapping)
            if occupied is not None:
                raise session_occupied(resume, occupied)
        else:
            alias = f'{purpose}_{uuid.uuid4().hex}@m1'
            directory = runner / 'sessions' / alias
            directory.mkdir(parents=True, exist_ok=False)
            mapping = {'alias': alias, 'purpose': purpose, 'parent': parent,
                       'runtime': runtime, 'hosted': True, 'role': purpose,
                       'ticket_id': None, 'team_generation': None,
                       'worktree_path': str(root), 'session': None}
            write_yaml_durably(directory / 'session.yml', {'alias': alias, 'purpose': purpose})
        owner = hold_ownership(directory, os.getpid())
        mapping = {**mapping, 'worker_pid': os.getpid(), 'runtime_pid': os.getpid()}
        try:
            write_yaml_durably(directory / 'mapping.yml', mapping)
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as trace:
                trace.write(json.dumps({**proposal, 'alias': mapping['alias']}) + '\n')
        except BaseException:
            owner.close()
            raise
        return mapping, owner
