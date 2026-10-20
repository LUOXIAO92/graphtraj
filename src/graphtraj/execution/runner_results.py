"""Session-owned, versioned results retained in the Project Worldline."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.configuration.project_roles import configured_role_name
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_io import _sync_directory
from graphtraj.execution.runner_status import caller_alias, read_alias_mapping, require_task_authority
from graphtraj.graph.delivery_state import current_result_rework_cause, read_team
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline
from graphtraj.graph.task_graph import _load_states
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
    role_name = configured_role_name(role)
    directory = Path('.state') / 'teams' / str(generation) / 'rounds' / str(ordinal)
    reports = reports or (directory / f'{role_name}.md',)
    entity = alias.partition('@')[2]
    if entity != role_name.replace('-', '_'):
        reports = tuple(path.with_stem(f'{path.stem}-{entity}') for path in reports)
    return reports


def task_report_paths(mapping: Mapping[str, Any], cwd: Path) -> tuple[Path, ...]:
    """Resolve retained assignments, advancing only their Team Round component."""
    configuration = load_project_configuration(discover_project_root(cwd))
    directory, _ = _load_states(configuration.state / 'tasks')[mapping['task_id']]
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
    """Read retained submissions and later retained evidence for this exact Session."""
    configuration = load_project_configuration(discover_project_root(cwd))
    return [event for event in read_worldline(configuration.state, configuration.harness_root)
            if event['event'] in {'result-submitted', 'evidence-retained'}
            and event.get('alias') == mapping.get('alias')
            and event.get('session') == mapping.get('session')]


# Task states in which a member's result or a new Round may be recorded.
RESULT_STATUSES = frozenset({'implementing', 'reviewing', 'reworking', 'resolving-integration'})

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
    require_task_authority(configuration.state, runner, mapping['task_id'], alias, 'submit')
    if _load_states(configuration.state / 'tasks')[mapping['task_id']][1]['status'] not in RESULT_STATUSES:
        raise ValueError('This task is not accepting result submissions.')
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
    directory, task = _load_states(configuration.state / 'tasks')[mapping['task_id']]
    if task['status'] == 'resolving-integration' and worktree != configuration.integration_worktree:
        raise RunnerError('authority-denied', 'Integration results must belong to the assigned Integration Worktree.')
    if run_git(worktree, 'rev-parse', 'HEAD') != commit:
        raise ValueError('The result commit must be the current Worktree version.')
    if run_git(worktree, 'diff', '--name-only') or run_git(worktree, 'diff', '--cached', '--name-only'):
        raise ValueError('Commit tracked changes before submitting a result.')

    def committed_file(reference: str) -> str:
        """Validate one repository file at the submitted version."""
        path = Path(reference)
        if path.is_absolute() or '..' in path.parts or reference.startswith('-'):
            raise ValueError('Result files must be Worktree-relative.')
        if path.parts and path.parts[0] == '.state':
            raise ValueError('Assigned reports belong in evidence_refs; result_refs must name committed files.')
        # HEAD was already resolved here, so a Git failure means the path is absent.
        try:
            kind = run_git(worktree, 'cat-file', '-t', f'{commit}:{reference}')
        except RunnerError:
            kind = None
        if kind != 'blob':
            raise ValueError(f'Result reference {reference} is not a committed file at {commit}.')
        return reference

    for reference in result_refs:
        committed_file(reference)
    assigned = set(_session_report_paths(alias, cwd))
    trace = Path(mapping['trace_file'])
    snapshots = []
    for reference in evidence_refs:
        supplied = Path(reference)
        path = supplied if supplied.is_absolute() else worktree / supplied
        if supplied.parts and supplied.parts[0] == '.state':
            directory, _ = _load_states(configuration.state / 'tasks')[mapping['task_id']]
            path = directory.joinpath(*supplied.parts[1:])
        resolved = path.resolve()
        if resolved in assigned or (trace.is_absolute() and resolved == trace.resolve()):
            content = resolved.read_bytes()
        else:
            relative = resolved.relative_to(worktree.resolve()).as_posix()
            if run_git(worktree, 'ls-tree', '--name-only', commit, '--', relative):
                committed_file(relative)
                # Git supplies the submitted bytes, independent of later Worktree writes.
                content = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=worktree)
            elif resolved.is_file() and Path(relative).parts[0] != '.git':
                # An untracked attachment is retained now by its current bytes,
                # so a later Worktree cleanup cannot lose named evidence.
                content = resolved.read_bytes()
            else:
                raise ValueError('Evidence references must name existing Worktree files.')
        snapshots.append((path.name, content))
    start_result_correction(mapping, cwd)
    directory, _ = _load_states(configuration.state / 'tasks')[mapping['task_id']]
    team = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
    ordinal = team['current_round']
    events = read_worldline(configuration.state, configuration.harness_root)
    predecessors = [event['event_id'] for event in events if event.get('task_id') == mapping['task_id']]
    # Repeating an unchanged submission in the same Round, as a caller does
    # after an unconfirmed reply, returns the recorded one without another.
    previous = next((event for event in reversed(events) if event['event'] == 'result-submitted'
                     and event.get('alias') == alias and event['round'] == ordinal), None)
    if (previous is not None
            and (previous['candidate'], previous['result_refs'], previous['completion'], previous['unresolved'])
            == (commit, list(result_refs), completion, list(unresolved))
            and [(configuration.harness_root / reference).read_bytes() for reference in previous['evidence_refs']]
            == [content for _, content in snapshots]):
        return previous
    event = {
        'event': 'result-submitted', 'task_id': mapping['task_id'],
        'alias': alias, 'session': mapping['session'], 'role': mapping['role'],
        'team_ordinal': mapping['team_generation'], 'round': ordinal,
        'candidate': commit, 'result_refs': list(result_refs),
        'completion': completion, 'unresolved': list(unresolved),
        'caused_by_event_ids': predecessors[-1:], 'evidence_refs': [],
    }

    def retain(recorded: dict[str, Any]) -> Callable[[], None]:
        """Recheck current ownership under the Worldline mutation lock."""
        require_task_authority(configuration.state, runner, mapping['task_id'], alias, 'submit')
        current = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
        if (_load_states(configuration.state / 'tasks')[mapping['task_id']][1]['status']
                not in {'implementing', 'reviewing', 'resolving-integration'} or current['current_round'] != ordinal):
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

    recorded = append_project_worldline_event(configuration.state, configuration.harness_root, event, retain)
    from graphtraj.execution.runner_control import deliver_parent_event

    deliver_parent_event(
        runner / 'sessions' / alias,
        'Result submitted for assessment:\n' + json.dumps(recorded, ensure_ascii=False),
        {'type': recorded['event'], 'session': mapping['session'],
         'execution_id': mapping.get('execution_id')},
    )
    return recorded


def start_result_correction(mapping: Mapping[str, Any], cwd: Path) -> None:
    """Open the next Round when an author starts correcting a rejected result.

    Both report and result submission use this transition, so closed Round
    reports stay unchanged and correction does not need another Agent.
    """
    configuration = load_project_configuration(discover_project_root(cwd))
    cwd = configuration.harness_root
    require_task_authority(configuration.state, discover_runner_directory(cwd),
                           mapping['task_id'], mapping['alias'], 'submit')
    directory, task = _load_states(configuration.state / 'tasks')[mapping['task_id']]
    if task['status'] not in RESULT_STATUSES:
        raise ValueError('This task is not accepting result submissions.')
    team = read_team(directory / 'teams' / str(mapping['team_generation']) / 'team.yml')
    rejection = current_result_rework_cause(read_worldline(configuration.state, cwd), task, team)
    if task['status'] == 'reworking' or (
        task['status'] == 'resolving-integration' and rejection is not None
    ):
        from graphtraj.graph.delivery_state import apply_delivery_state_request

        if rejection is None:
            raise ValueError('Rework requires a confirmed result rejection or explicit graph reopening')
        request = {
            'phase': 'rework', 'task_id': mapping['task_id'],
            'caused_by_event_ids': [rejection['event_id']],
            'evidence_refs': rejection['evidence_refs'],
        }
        apply_delivery_state_request(configuration.state, cwd, request, request)


def decide_session_result(
    submission_id: str,
    commit: str,
    decision: str,
    reason: str,
    evidence_refs: tuple[str, ...],
    cwd: Path,
) -> dict[str, Any]:
    """Record an authorized acceptance or rejection of an existing submission."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request

    configuration = load_project_configuration(discover_project_root(cwd))
    events = read_worldline(configuration.state, configuration.harness_root)
    submission = next((event for event in events
                       if event["event_id"] == submission_id
                       and event["event"] == "result-submitted"), None)
    if submission is None:
        raise ValueError("Unknown result submission")
    request = {
        "phase": "final", "task_id": submission["task_id"],
        "submission_id": submission_id, "candidate": commit,
        "decision": decision, "reason": reason,
        "caused_by_event_ids": [submission_id], "evidence_refs": list(evidence_refs),
    }
    return apply_delivery_state_request(configuration.state, configuration.harness_root, request, request)


def retain_submission_evidence(
    submission_id: str,
    evidence_refs: tuple[str, ...],
    cwd: Path,
) -> dict[str, Any]:
    """Retain untracked Worktree files for an existing result submission.

    The submitting Session's direct owner names files that are still only in
    that Session's Worktree. Their current bytes are copied beside the
    submission's Trace under the Worldline lock and recorded as one
    ``evidence-retained`` event caused by the submission, so later Worktree
    cleanup cannot lose them. The submission, its decision and the Task state
    are unchanged; repeating the same files with the same bytes returns the
    recorded event.
    """
    from graphtraj.execution.runner_status import require_direct_authority

    configuration = load_project_configuration(discover_project_root(cwd))
    events        = read_worldline(configuration.state, configuration.harness_root)
    submission    = next((event for event in events if event['event_id'] == submission_id
                          and event['event'] == 'result-submitted'), None)
    if submission is None:
        raise ValueError('Unknown result submission')
    if not evidence_refs or len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError('Retained evidence requires distinct Worktree files.')

    runner = discover_runner_directory(configuration.harness_root)
    alias  = submission['alias']
    mapping, _ = read_alias_mapping(runner, alias)
    require_direct_authority(runner, alias, mapping)
    if mapping.get('session') != submission['session']:
        raise RunnerError('authority-denied', 'The submission belongs to another Session.')

    worktree  = Path(mapping['worktree_path']).resolve()
    snapshots = []
    for reference in evidence_refs:
        path = Path(reference)
        if (not isinstance(reference, str) or path.is_absolute() or '..' in path.parts
                or not path.parts or path.parts[0] == '.git'):
            raise ValueError('Retained evidence must name Worktree-relative files.')
        resolved = (worktree / path).resolve()
        if not resolved.is_relative_to(worktree) or not resolved.is_file():
            raise ValueError(f'Retained evidence does not exist in the Worktree: {reference}')
        snapshots.append((reference, path.name, resolved.read_bytes()))

    # The same files with the same bytes were already retained.
    for event in events:
        if (event['event'] == 'evidence-retained' and event['caused_by_event_ids'] == [submission_id]
                and event.get('sources') == list(evidence_refs)
                and [(configuration.harness_root / item).read_bytes() for item in event['evidence_refs']]
                == [content for _, _, content in snapshots]):
            return event

    directory, _ = _load_states(configuration.state / 'tasks')[submission['task_id']]
    event = {
        'event': 'evidence-retained', 'task_id': submission['task_id'],
        'alias': alias, 'session': submission['session'], 'submission_id': submission_id,
        'sources': list(evidence_refs),
        'caused_by_event_ids': [submission_id], 'evidence_refs': [],
    }

    def retain(recorded: dict[str, Any]) -> Callable[[], None]:
        """Write the copies under the Worldline lock, removed if the append fails."""
        retained = (directory / 'teams' / str(submission['team_ordinal']) / 'traces'
                    / alias / recorded['event_id'])
        retained.mkdir(parents=True)
        try:
            for index, (_, name, content) in enumerate(snapshots):
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
