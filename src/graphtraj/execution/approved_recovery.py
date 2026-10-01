"""Concrete native-approved repairs followed by original-Session continuation."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

from graphtraj.execution.runner_control import _require_project_events, _send_session_locked
from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    caller_alias, read_alias_mapping, require_direct_authority, require_stopped_subtree,
    require_execution_allowed,
)
from graphtraj.graph.delivery_state import read_team
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline, _read_shards
from graphtraj.graph.ticket_graph import _load_states, _lock, _unlock
from graphtraj.runtimes import runtime_adapter
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.workspace.runner_project import discover_project


def approved_recovery(arguments: dict, cwd: Path) -> dict:
    """Prepare a reviewable repair, or retry continuation of an applied repair.

    Native approval executes the exact prepared command; this entry has no
    approved flag and never interprets supplied authority references as approval.
    Retry references the applied Worldline event and cannot extend time again.
    """
    project = discover_project(cwd, require_clean_integration=False)
    alias = arguments['alias']
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    require_direct_authority(project.runner_directory, alias, mapping)
    retry = arguments.get('retry_event_id')
    if retry:
        if set(arguments) != {'alias', 'retry_event_id'}:
            raise RunnerError('invalid-input', 'Retry accepts only alias and retry_event_id.')
        events = read_worldline(project.state_directory, project.harness_root)
        applied = next((event for event in events if event['event_id'] == retry
                        and event['event'] == 'recovery-applied' and event.get('alias') == alias), None)
        if applied is None:
            raise RunnerError('invalid-input', 'Retry must identify this Session\'s applied recovery.')
        return _resume(project, applied)

    for field in ('reason', 'instruction', 'allowed_scope', 'forbidden_scope'):
        if not isinstance(arguments.get(field), str) or not arguments[field].strip():
            raise RunnerError('invalid-input', f'{field} must be explicit nonempty text.')
    causes = tuple(arguments.get('caused_by_event_ids', ()))
    if not causes or len(set(causes)) != len(causes):
        raise RunnerError('invalid-input', 'Recovery requires unique authority event references.')
    _require_project_events(cwd, causes)
    minutes = arguments.get('additional_minutes', 0)
    if (isinstance(minutes, bool) or not isinstance(minutes, (int, float))
            or not math.isfinite(minutes) or minutes < 0):
        raise RunnerError('invalid-input', 'additional_minutes must be a finite nonnegative increment.')
    request = {**arguments, 'additional_minutes': minutes,
               'restore_active': arguments.get('restore_active', False),
               'resume': arguments.get('resume', True)}
    events = read_worldline(project.state_directory, project.harness_root)
    previous = next((event for event in reversed(events) if event['event'] == 'recovery-applied'
                     and event.get('alias') == alias
                     and {**event['proposal']['request'],
                          'resume': event['proposal']['request'].get('resume', True)} == request), None)
    if previous is not None:
        return _resume(project, previous)
    before, _ = _snapshot(project, alias)
    after = _repair_snapshot(project, before, request)
    proposal = {
        'request': request, 'before': before, 'after': after,
        'authority': [event for event in events if event['event_id'] in causes],
    }
    # Native review executes the installed public command with the exact values.
    command = [str(Path(sys.executable).with_name('agent-runner')), 'recover-apply',
               '--proposal', json.dumps(proposal, ensure_ascii=False)]
    caller = caller_alias(project.runner_directory)
    runtime = read_alias_mapping(project.runner_directory, caller)[0]['runtime'] if caller else caller_runtime()
    if runtime is None:
        raise RunnerError('native-approval-unavailable', 'The calling Runtime is unknown; recovery was not applied.')
    try:
        adapter = runtime_adapter.select_runtime_adapter(runtime)
        result = adapter.native_recovery_approval(command, proposal)
    except (runtime_adapter.RuntimeAdapterError, AttributeError) as error:
        raise RunnerError('native-approval-unavailable', str(error)) from error
    if not isinstance(result, dict) or 'recovery_status' not in result:
        raise RunnerError('native-approval-failed', 'The native recovery returned no execution result.')
    return {**result, 'proposal': proposal}


def _repair_snapshot(project: Any, before: dict, request: dict) -> dict:
    """Derive the only permitted repair, preserving stops for administrative work."""
    after = copy.deepcopy(before)
    minutes = request.get('additional_minutes', 0)
    resume = request.get('resume', True)
    if request.get('restore_active', False):
        if before['ticket']['replaced_by']:
            raise RunnerError('invalid-input', 'A replaced Ticket requires task-graph revision.')
        after['ticket']['active'] = True
        if Path(before['mapping']['worktree_path']) == project.integration_worktree:
            after['ticket']['status'] = 'resolving-integration'
        elif after['ticket']['status'] not in {'implementing', 'reviewing', 'reworking'}:
            after['ticket']['status'] = 'implementing'
        after['team']['status'] = 'active'
        for field in ('retired_by', 'retirement_event_id', 'retired_at', 'final_session_ref', 'final_trace_ref'):
            after['team'].pop(field, None)
        after['round_mode'] |= 0o200
    if minutes and before['budget'] is None:
        raise RunnerError('invalid-input', 'Time extension requires existing execution accounting.')
    if minutes:
        after['budget']['approved_minutes'] = after['budget'].get('approved_minutes', 0) + minutes
        if resume:
            after['budget']['stopped'] = False
    budget_stopped = after['budget'] is not None and after['budget'].get('stopped', False)
    # Administrative reopening grants neither execution permission nor more time.
    if resume and not budget_stopped and after['stop'] is not None:
        after['stop']['resumed'] = True
    if not after['ticket']['active'] or after['team']['status'] != 'active':
        raise RunnerError('team-not-active', 'This recovery needs restore_active to repair administrative state.')
    return after


def _snapshot(project: Any, alias: str, *, worldline_locked: bool = False) -> tuple[dict, dict]:
    """Read the exact target state and derive all paths from registered ownership."""
    mapping, session = read_alias_mapping(project.runner_directory, alias)
    directory, ticket = _load_states(project.state_directory / 'tickets')[mapping['ticket_id']]
    if ticket['active_team_ordinal'] != mapping['team_generation']:
        raise RunnerError('seat-replaced', 'Recovery cannot change Session ownership.')
    team_path = directory / 'teams' / str(mapping['team_generation']) / 'team.yml'
    team = read_team(team_path)
    if alias not in {member['session_ref'] for member in team['members'].values()}:
        raise RunnerError('seat-replaced', 'Recovery requires the original current Team member.')
    paths = {'ticket': directory / 'ticket.yml', 'team': team_path,
             'budget': directory / 'execution-budget.yml', 'stop': session / 'stop.yml',
             'round': team_path.parent / 'rounds' / str(team['current_round'])}
    events = (_read_shards(project.state_directory)[1] if worldline_locked
              else read_worldline(project.state_directory, project.harness_root))
    latest = [event['event_id'] for event in events if event.get('ticket_id') == mapping['ticket_id']]
    snapshot = {
        'ticket': ticket, 'team': team,
        'budget': yaml.safe_load(paths['budget'].read_text()) if paths['budget'].exists() else None,
        'stop': yaml.safe_load(paths['stop'].read_text()) if paths['stop'].exists() else None,
        'round_mode': paths['round'].stat().st_mode & 0o777,
        'mapping': mapping,
        'definition_sha256': hashlib.sha256((directory / ticket['current_definition']).read_bytes()).hexdigest(),
        'latest_ticket_event': latest[-1] if latest else None,
    }
    return snapshot, paths


def _differences(expected: Any, actual: Any, prefix: str = '') -> list[dict]:
    """Return concrete stale values, including nested state changes."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [difference for key in sorted(expected.keys() | actual.keys())
                for difference in _differences(expected.get(key), actual.get(key), f'{prefix}.{key}'.strip('.'))]
    return [] if expected == actual else [{'field': prefix, 'expected': expected, 'actual': actual}]


def apply_approved_recovery(proposal: dict, cwd: Path) -> dict:
    """Apply only the native-reviewed snapshot, atomically with its Worldline fact.

    The public recover-apply command is executed by the native reviewer. The
    execution, Ticket, budget and Worldline locks serialize existing writers.
    A repeated approved payload uses its retained applied event without adding time.
    """
    project = discover_project(cwd, require_clean_integration=False)
    alias = proposal['request']['alias']
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    require_direct_authority(project.runner_directory, alias, mapping)
    # Validate command inputs independently of the preparing process. A proposal
    # cannot widen the supported repair into arbitrary Ticket/Team/file changes.
    from graphtraj.interfaces.gateway import _validate
    from graphtraj.interfaces.tools import TOOLS

    _validate(proposal['request'], TOOLS['approved_recovery'].input_schema, 'proposal.request')
    request = proposal['request']
    if 'retry_event_id' in request:
        raise RunnerError('invalid-input', 'An execution proposal cannot contain a retry.')
    for field in ('reason', 'instruction', 'allowed_scope', 'forbidden_scope'):
        if not isinstance(request.get(field), str) or not request[field].strip():
            raise RunnerError('invalid-input', f'{field} must be explicit nonempty text.')
    minutes = request.get('additional_minutes', 0)
    if not math.isfinite(minutes) or minutes < 0:
        raise RunnerError('invalid-input', 'additional_minutes must be a finite nonnegative increment.')
    causes = tuple(request.get('caused_by_event_ids', ()))
    if not causes or len(set(causes)) != len(causes):
        raise RunnerError('invalid-input', 'Recovery requires unique authority event references.')
    _require_project_events(cwd, causes)
    events = read_worldline(project.state_directory, project.harness_root)
    authority = [event for event in events if event['event_id'] in causes]
    if (proposal['authority'] != authority
            or proposal['after'] != _repair_snapshot(project, proposal['before'], request)):
        raise RunnerError('invalid-input', 'The proposal differs from the supported recovery and retained authority.')
    digest = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()
    _, paths = _snapshot(project, alias)
    with execution_start_lock(project.runner_directory):
        lock = _lock(project.state_directory / 'tickets', exclusive=True)
        try:
            with (paths['budget'].parent / '.execution-budget.lock').open('a+b') as budget_lock:
                fcntl.flock(budget_lock, fcntl.LOCK_EX)
                events = read_worldline(project.state_directory, project.harness_root)
                applied = next((event for event in events if event['event'] == 'recovery-applied'
                                and event.get('proposal_sha256') == digest), None)
                if applied is None:
                    current, paths = _snapshot(project, alias)
                    differences = _differences(proposal['before'], current)
                    if differences:
                        return {'recovery_status': 'stale', 'applied': False, 'differences': differences}
                    require_stopped_subtree(project.runner_directory, alias)
                    original = {key: path.read_bytes() if path.exists() else None
                                for key, path in paths.items() if key != 'round'}
                    original_mode = paths['round'].stat().st_mode & 0o777

                    def restore() -> None:
                        """Roll back only the exact files this approved change touched."""
                        for key, contents in original.items():
                            if contents is None:
                                paths[key].unlink(missing_ok=True)
                            else:
                                paths[key].write_bytes(contents)
                        paths['round'].chmod(original_mode)

                    def mutate(recorded: dict) -> Any:
                        """Recheck under the Worldline lock before any state mutation."""
                        current, _ = _snapshot(project, alias, worldline_locked=True)
                        differences = _differences(proposal['before'], current)
                        if differences:
                            raise RunnerError('recovery-stale', json.dumps(differences))
                        try:
                            for key in original:
                                if proposal['before'][key] != proposal['after'][key]:
                                    write_yaml_durably(paths[key], proposal['after'][key])
                            if original_mode != proposal['after']['round_mode']:
                                paths['round'].chmod(proposal['after']['round_mode'])
                        except Exception:
                            restore()
                            raise
                        return restore

                    try:
                        applied = append_project_worldline_event(
                            project.state_directory, project.harness_root,
                            {'event': 'recovery-applied', 'alias': alias, 'session': mapping['session'],
                             'ticket_id': mapping['ticket_id'], 'proposal_sha256': digest,
                             'proposal': proposal,
                             'caused_by_event_ids': proposal['request']['caused_by_event_ids'],
                             'evidence_refs': []}, mutate,
                        )
                    except RunnerError as error:
                        if error.code != 'recovery-stale':
                            raise
                        return {'recovery_status': 'stale', 'applied': False,
                                'differences': json.loads(error.message)}
        finally:
            _unlock(lock)
    return _resume(project, applied)


def _resume(project: Any, applied: dict) -> dict:
    """Continue the original Session; report applied changes even when resume fails."""
    result = {'recovery_status': 'resume-failed', 'applied': True,
              'recovery_event_id': applied['event_id'],
              'changes': _differences(applied['proposal']['before'], applied['proposal']['after'])}
    if not applied['proposal']['request'].get('resume', True):
        return {**result, 'recovery_status': 'applied'}
    try:
        _, directory = read_alias_mapping(project.runner_directory, applied['alias'])
        with (directory / 'launch.yml').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _resume_locked(project, applied, directory)
    except (RunnerError, runtime_adapter.RuntimeAdapterError, OSError, ValueError) as error:
        return {**result, 'error': {'code': getattr(error, 'code', 'operation-failed'), 'message': str(error)}}


def _resume_locked(project: Any, applied: dict, directory: Path) -> dict:
    """Serialize retry and send with ordinary input to this same Session."""
    proposal = applied['proposal']
    alias = applied['alias']
    result = {'recovery_status': 'applied', 'applied': True,
              'recovery_event_id': applied['event_id'],
              'changes': _differences(proposal['before'], proposal['after'])}
    events = read_worldline(project.state_directory, project.harness_root)
    prior = next((event for event in events if event['event'] == 'recovery-resumed'
                  and applied['event_id'] in event['caused_by_event_ids']), None)
    if prior:
        return {**result, 'recovery_status': 'resumed', 'resumption': prior['resumption']}
    current, _ = _snapshot(project, alias)
    expected = {**proposal['after'], 'latest_ticket_event': applied['event_id']}
    differences = _differences(expected, current)
    # Native startup replaces transport and clears the terminal summary before
    # turn admission. These changes do not alter Session ownership or authority.
    for key in ('execution_id', 'worker_pid', 'runtime_pid', 'control_directory', 'last_outcome'):
        differences = [item for item in differences if item['field'] != 'mapping.' + key]
    if differences:
        return {**result, 'recovery_status': 'resume-stale', 'differences': differences}
    request = proposal['request']
    instruction = json.dumps({
        'instruction': request['instruction'], 'allowed_scope': request['allowed_scope'],
        'forbidden_scope': request['forbidden_scope'],
        'caused_by_event_ids': [*request['caused_by_event_ids'], applied['event_id']],
    }, ensure_ascii=False)
    try:
        from graphtraj.teams.team_replacement import require_active_session

        mapping, _ = read_alias_mapping(project.runner_directory, alias)
        with execution_start_lock(project.runner_directory):
            require_execution_allowed(project.runner_directory, alias, mapping)
        require_active_session(project, alias)
        resumption = _send_session_locked(
            alias, instruction, directory, mapping, (applied['event_id'],), project.harness_root,
            require_budget_permission=True,
        )
    except (RunnerError, runtime_adapter.RuntimeAdapterError, OSError, ValueError) as error:
        return {**result, 'recovery_status': 'resume-failed',
                'error': {'code': getattr(error, 'code', 'operation-failed'), 'message': str(error)}}
    try:
        append_project_worldline_event(
            project.state_directory, project.harness_root,
            {'event': 'recovery-resumed', 'alias': alias, 'session': applied['session'],
             'ticket_id': applied['ticket_id'], 'resumption': resumption,
             'caused_by_event_ids': [applied['event_id']], 'evidence_refs': []},
        )
    except (OSError, ValueError) as error:
        return {**result, 'recovery_status': 'resumed', 'resumption': resumption,
                'evidence_error': str(error)}
    return {**result, 'recovery_status': 'resumed', 'resumption': resumption}
