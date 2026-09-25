"""Session-owned, versioned results retained in the Project Worldline."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import logical_role
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_io import _sync_directory
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping, require_task_authority
from graphtraj.graph.delivery_state import read_team
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.graph.ticket_graph import _load_states
from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory, run_git


def assign_session_reports(
    role: str,
    alias: str,
    generation: int,
    ordinal: int,
    reports: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    """Name an actual member's reports, retaining any task-selected attachments.

    Alias allocation already distinguishes repeated roles. Use that same entity
    component rather than reserving report names or introducing another identity.
    """
    role_name = logical_role(role)
    directory = Path('.state') / 'teams' / str(generation) / 'rounds' / str(ordinal)
    reports = reports or (directory / f'{role_name}.md',)
    entity = alias.partition('@')[2]
    if entity != role_name.replace('-', '_'):
        reports = tuple(path.with_stem(f'{path.stem}-{entity}') for path in reports)
    return reports


def task_report_paths(mapping: Mapping[str, Any], cwd: Path) -> tuple[Path, ...]:
    """Resolve retained assignments, advancing only their Team Round component."""
    configuration = load_project_configuration(discover_project_root(cwd))
    directory, _ = _load_states(configuration.state / 'tickets')[mapping['ticket_id']]
    team_file = directory / 'teams' / str(mapping['team_generation']) / 'team.yml'
    team = read_team(team_file) if team_file.exists() else None
    paths = []
    for value in mapping['report_files']:
        report = Path(value)
        if report.is_absolute() or len(report.parts) < 2 or '..' in report.parts or report.parts[0] != '.state':
            raise RunnerError('authority-denied', 'Invalid assigned report path.')
        parts = list(report.parts[1:])
        if team is not None and len(parts) >= 5 and parts[:3] == ['teams', str(mapping['team_generation']), 'rounds']:
            parts[3] = str(team['current_round'])
        path = directory.joinpath(*parts)
        if path.resolve() != path or path.suffix != '.md':
            raise RunnerError('authority-denied', 'A report path changed its declared target.')
        paths.append(path)
    return tuple(paths)


def session_submissions(mapping: Mapping[str, Any], cwd: Path) -> list[dict[str, Any]]:
    """Read retained submissions for this exact Session, including prior Rounds."""
    configuration = load_project_configuration(discover_project_root(cwd))
    return [event for event in read_worldline(configuration.state, configuration.harness_root)
            if event['kind'] == 'result-submitted'
            and event.get('alias') == mapping.get('alias')
            and event.get('session') == mapping.get('session')]


def submit_session_result(
    commit: str,
    result_refs: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    completion: str,
    unresolved: tuple[str, ...],
    cwd: Path,
) -> dict[str, Any]:
    """Bind a committed result and immutable evidence to the authentic member.

    Result references name files at ``commit`` relative to the Worktree.
    Evidence names committed files or the Session's assigned reports/Trace.
    Evidence copies and the event are committed together under the existing
    Worldline lock; a failed write or append removes the new copies.
    """
    from graphtraj.execution.runner_control import _session_report_paths

    configuration = load_project_configuration(discover_project_root(cwd))
    cwd = configuration.harness_root
    runner = discover_runner_directory(cwd)
    alias = caller_alias(runner)
    if alias is None:
        raise RunnerError('authority-denied', 'A task result requires its own Session.')
    mapping, _ = read_alias_mapping(runner, alias)
    require_task_authority(configuration.state, runner, mapping['ticket_id'], alias, 'submit')
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('A result requires a full Git commit.')
    if not isinstance(completion, str) or not completion.strip():
        raise ValueError('A result requires a completion description.')
    for refs in (result_refs, evidence_refs, unresolved):
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValueError('Result references and unresolved items must be nonempty strings.')
    if not result_refs or len(set(result_refs)) != len(result_refs):
        raise ValueError('A result requires distinct committed file references.')
    if len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError('Evidence references must be distinct.')
    worktree = Path(mapping['worktree_path'])
    if run_git(worktree, 'rev-parse', 'HEAD') != commit:
        raise ValueError('The result commit must be the current Worktree version.')
    if run_git(worktree, 'diff', '--name-only') or run_git(worktree, 'diff', '--cached', '--name-only'):
        raise ValueError('Commit tracked changes before submitting a result.')

    def committed_file(reference: str) -> str:
        """Validate one repository file at the submitted version."""
        path = Path(reference)
        if path.is_absolute() or '..' in path.parts or reference.startswith('-'):
            raise ValueError('Result files must be Worktree-relative.')
        if run_git(worktree, 'cat-file', '-t', f'{commit}:{reference}') != 'blob':
            raise ValueError('Result references must name committed files.')
        return reference

    for reference in result_refs:
        committed_file(reference)
    assigned = set(_session_report_paths(alias, cwd))
    trace = Path(mapping['trace_file'])
    snapshots = []
    for reference in evidence_refs:
        supplied = Path(reference)
        path = supplied if supplied.is_absolute() else worktree / supplied
        resolved = path.resolve()
        if resolved in assigned or (trace.is_absolute() and resolved == trace.resolve()):
            content = resolved.read_bytes()
        else:
            relative = resolved.relative_to(worktree.resolve()).as_posix()
            committed_file(relative)
            # Git supplies the submitted bytes, independent of later Worktree writes.
            content = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=worktree)
        snapshots.append((path.name, content))
    directory, _ = _load_states(configuration.state / 'tickets')[mapping['ticket_id']]
    team = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
    ordinal = team['current_round']
    predecessors = [event['event_id'] for event in read_worldline(configuration.state, configuration.harness_root)
                    if event.get('ticket_id') == mapping['ticket_id']]
    event = {
        'kind': 'result-submitted', 'ticket_id': mapping['ticket_id'],
        'alias': alias, 'session': mapping['session'], 'role': mapping['role'],
        'team_ordinal': mapping['team_generation'], 'round': ordinal,
        'candidate': commit, 'result_refs': list(result_refs),
        'completion': completion, 'unresolved': list(unresolved),
        'caused_by_event_ids': predecessors[-1:], 'evidence_refs': [],
    }

    def retain(recorded: dict[str, Any]) -> Callable[[], None]:
        """Recheck current ownership under the Worldline mutation lock."""
        require_task_authority(configuration.state, runner, mapping['ticket_id'], alias, 'submit')
        current = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
        if current['current_round'] != ordinal:
            raise RunnerError('authority-denied', 'The submission Round has changed.')
        if not snapshots:
            return lambda: None
        retained = directory / 'teams' / str(mapping['team_generation']) / 'traces' / alias / recorded['event_id']
        retained.mkdir(parents=True)
        try:
            for index, (name, content) in enumerate(snapshots):
                path = retained / f'{index}-{name}'
                with path.open('xb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                recorded['evidence_refs'].append(path.relative_to(configuration.harness_root).as_posix())
            _sync_directory(retained)
            _sync_directory(retained.parent)
        except Exception:
            shutil.rmtree(retained)
            raise
        return lambda: shutil.rmtree(retained)

    return append_project_worldline_event(configuration.state, configuration.harness_root, event, retain)
