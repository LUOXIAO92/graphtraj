"""Concrete native-approved repairs followed by original-Session continuation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import yaml

from graphtraj import file_lock
from graphtraj.execution.runner_control import (
    _confirm_termination, _require_project_events, _send_session_locked,
)
from graphtraj.execution.runner_heartbeat import execution_start_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    caller_alias, read_alias_mapping, read_execution_result, require_direct_authority,
    require_stopped_subtree, require_execution_allowed, caller_runtime_name,
)
from graphtraj.graph.delivery_state import read_team
from graphtraj.graph.delivery_worldline import append_project_worldline_event, read_worldline, _read_shards
from graphtraj.graph.task_graph import _load_states, _lock, _unlock
from graphtraj.runtimes import runtime_adapter
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.workspace.runner_project import discover_project


def approved_recovery(arguments: dict, cwd: Path) -> dict:
    """Prepare a reviewable repair, or retry continuation of an applied repair.

    Only new spending requires review; interruption does not revoke authority.
    Explicit user directives still constrain the authorized task. The decision
    stays inside this call; supplied authority references are never approval.
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
    before, _ = _snapshot(project, alias, administrative=not request['resume'])
    after = _repair_snapshot(project, before, request)
    proposal = {
        'request': request, 'before': before, 'after': after,
        'authority': [event for event in events if event['event_id'] in causes],
    }
    _confirm_unconfirmed_target(project.runner_directory, alias)
    if _changes_execution(request) or before['mapping'] != after['mapping']:
        require_stopped_subtree(project.runner_directory, alias)
    if minutes:
        decision = review_proposal(proposal, cwd, project.runner_directory)
        if decision != {'decision': 'accept'}:
            rationale = decision.get('rationale')
            message = 'Recovery was not approved; no repair was applied.'
            if isinstance(rationale, str) and rationale.strip():
                message += ' Reviewer reason: ' + rationale
            raise RunnerError('recovery-denied', message)
    return _apply_recovery(proposal, cwd)


def _changes_execution(request: dict) -> bool:
    """Whether a recovery resumes the Session or reactivates its Task.

    Only these need the target subtree stopped. A budget increment without
    either keeps running work, its stop facts and its original clock.
    """
    return request['resume'] or request.get('restore_active', False)


def review_proposal(proposal: dict, cwd: Path, runner_directory: Path) -> dict:
    """Obtain the owning host's selected decision without exposing approval inputs."""
    try:
        reviewer = runtime_adapter.current_recovery_reviewer()
        if reviewer is not None:
            return reviewer(proposal)
        else:
            caller = caller_alias(runner_directory)
            runtime = caller_runtime_name(runner_directory, caller) or caller_runtime()
            if runtime is None:
                raise RunnerError('native-approval-unavailable', 'The calling Runtime is unknown.')
            adapter = runtime_adapter.select_runtime_adapter(runtime)
            return adapter.native_recovery_approval(proposal, cwd)
    except (runtime_adapter.RuntimeAdapterError, AttributeError) as error:
        raise RunnerError(getattr(error, 'code', 'native-approval-unavailable'), str(error)) from error


def _repair_snapshot(project: Any, before: dict, request: dict) -> dict:
    """Derive the only permitted repair, preserving stops for administrative work."""
    after = copy.deepcopy(before)
    minutes = request.get('additional_minutes', 0)
    resume = request.get('resume', True)
    if request['alias'] not in {member['session_ref'] for member in before['team']['members'].values()}:
        if resume or request.get('restore_active', False) or not minutes or before['budget'] is None:
            raise RunnerError(
                'invalid-input',
                'Retired-member recovery requires a positive budget increment without resume or restore_active.',
            )
        # The retained binding preserves ownership; this repair changes only its
        # Task budget, leaving the retired Session and Team untouched.
        after['budget']['approved_minutes'] = after['budget'].get('approved_minutes', 0) + minutes
        return after
    if request.get('restore_active', False):
        if not before['task']['active'] or before['task']['status'] == 'integrated':
            raise RunnerError('invalid-input', 'Task disposition and completed ancestors require task-graph revision.')
        if before['task']['replaced_by']:
            raise RunnerError('invalid-input', 'A replaced Task requires task-graph revision.')
        after['task']['active'] = True
        if Path(before['mapping']['worktree_path']) == project.integration_worktree:
            after['task']['status'] = 'resolving-integration'
        elif after['task']['status'] not in {'implementing', 'reviewing', 'reworking'}:
            after['task']['status'] = 'implementing'
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
    if not after['task']['active'] or after['team']['status'] != 'active':
        raise RunnerError('team-not-active', 'This recovery needs restore_active to repair administrative state.')
    if before['mapping'].get('parent') is None and caller_alias(project.runner_directory) is None:
        from graphtraj.execution.runner_connection import current_parent_connection

        # An authenticated Main's recovery retains the Agent and native Session,
        # but returns its notices to that Main's actual host. The event keeps
        # the former connection; no model argument can choose a recipient.
        host = current_parent_connection() or runtime_adapter.current_host_connection()
        if host is not None:
            after['mapping']['parent_connection'] = host
    return after


def _confirm_unconfirmed_target(runner: Path, alias: str) -> None:
    """Run the interrupt's own termination confirmation for an unconfirmed target.

    Only a retained outcome marked unconfirmed and still lacking its receipt is
    rechecked, under the same lock and Adapter evidence; failure still refuses.
    """
    mapping, directory = read_alias_mapping(runner, alias)
    execution = directory / 'execution.yml'
    if not execution.is_file() or execution.is_symlink():
        return
    if read_execution_result(execution).get('terminal_confirmed') is not False:
        return
    if os.path.lexists(directory / f"terminal-confirmation-{mapping['execution_id']}.yml"):
        return
    _confirm_termination(alias, directory, mapping)


def _snapshot(
    project: Any,
    alias: str,
    *,
    administrative: bool = False,
    worldline_locked: bool = False,
) -> tuple[dict, dict]:
    """Read the exact target state and derive all paths from registered ownership."""
    mapping, session = read_alias_mapping(project.runner_directory, alias)
    directory, task = _load_states(project.state_directory / 'tasks')[mapping['task_id']]
    if task['active_team_ordinal'] != mapping['team_generation']:
        raise RunnerError('seat-replaced', 'Recovery cannot change Session ownership.')
    team_path = directory / 'teams' / str(mapping['team_generation']) / 'team.yml'
    team = read_team(team_path)
    if not administrative and alias not in {member['session_ref'] for member in team['members'].values()}:
        raise RunnerError('seat-replaced', 'Recovery requires the original current Team member.')
    paths = {'task': directory / 'task.yml', 'team': team_path, 'mapping': session / 'mapping.yml',
             'budget': directory / 'execution-budget.yml', 'stop': session / 'stop.yml',
             'round': team_path.parent / 'rounds' / str(team['current_round'])}
    events = (_read_shards(project.state_directory)[1] if worldline_locked
              else read_worldline(project.state_directory, project.harness_root))
    latest = [event['event_id'] for event in events if event.get('task_id') == mapping['task_id']]
    snapshot = {
        'task': task, 'team': team,
        'budget': yaml.safe_load(paths['budget'].read_text()) if paths['budget'].exists() else None,
        'stop': yaml.safe_load(paths['stop'].read_text()) if paths['stop'].exists() else None,
        'round_mode': paths['round'].stat().st_mode & 0o777,
        'mapping': mapping,
        'definition_sha256': hashlib.sha256((directory / task['current_definition']).read_bytes()).hexdigest(),
        'latest_task_event': latest[-1] if latest else None,
    }
    return snapshot, paths


def _differences(expected: Any, actual: Any, prefix: str = '') -> list[dict]:
    """Return concrete stale values, including nested state changes."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [difference for key in sorted(expected.keys() | actual.keys())
                for difference in _differences(expected.get(key), actual.get(key), f'{prefix}.{key}'.strip('.'))]
    return [] if expected == actual else [{'field': prefix, 'expected': expected, 'actual': actual}]


def _apply_recovery(proposal: dict, cwd: Path) -> dict:
    """Apply the authorized snapshot atomically with its Worldline fact.

    Called only by recovery after required review. The execution, Task,
    budget and Worldline locks serialize existing writers.
    A repeated approved payload uses its retained applied event without adding time.
    """
    project = discover_project(cwd, require_clean_integration=False)
    alias = proposal['request']['alias']
    mapping, _ = read_alias_mapping(project.runner_directory, alias)
    require_direct_authority(project.runner_directory, alias, mapping)
    # Recheck authority and state after review; the repair must still describe
    # the exact supported changes when it reaches the mutation locks.
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
    _, paths = _snapshot(project, alias, administrative=not request['resume'])
    with execution_start_lock(project.runner_directory):
        lock = _lock(project.state_directory / 'tasks', exclusive=True)
        try:
            with (paths['budget'].parent / '.execution-budget.lock').open('a+b') as budget_lock:
                file_lock.flock(budget_lock, file_lock.LOCK_EX)
                events = read_worldline(project.state_directory, project.harness_root)
                applied = next((event for event in events if event['event'] == 'recovery-applied'
                                and event.get('proposal_sha256') == digest), None)
                if applied is None:
                    current, paths = _snapshot(project, alias, administrative=not request['resume'])
                    differences = _differences(proposal['before'], current)
                    if differences:
                        return {'recovery_status': 'stale', 'applied': False, 'differences': differences}
                    if _changes_execution(request) or proposal['before']['mapping'] != proposal['after']['mapping']:
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
                        current, _ = _snapshot(
                            project, alias, administrative=not request['resume'], worldline_locked=True,
                        )
                        differences = _differences(proposal['before'], current)
                        if differences:
                            raise RunnerError('recovery-stale', json.dumps(differences))
                        try:
                            for key in original:
                                if proposal['before'][key] != proposal['after'][key]:
                                    value = proposal['after'][key]
                                    if key == 'task':
                                        from graphtraj.graph.task_protocol import execution_record

                                        value = execution_record(value)
                                    elif key == 'budget':
                                        from graphtraj.execution.execution_budget import start_approved_window

                                        # The increment counts as execution time from now,
                                        # not from when the budget ran out.
                                        value = start_approved_window(proposal['before']['budget'], value, time.time())
                                        # The applied clock can differ from the reviewed
                                        # increment after waiting. Retry must compare the
                                        # clock we actually wrote, not the earlier proposal.
                                        recorded['applied_budget'] = value
                                    write_yaml_durably(paths[key], value)
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
                             'task_id': mapping['task_id'], 'proposal_sha256': digest,
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
        result['recovery_status'] = 'applied'
        before = applied['proposal']['before']['mapping']
        after = applied['proposal']['after']['mapping']
        if before.get('parent_connection') != after.get('parent_connection'):
            # Re-deliver an already written report after host recovery without
            # waking its author or granting more execution time. A successful
            # receipt prevents replay on a repeated recovery request.
            from graphtraj.execution.runner_control import _reported

            _, directory = read_alias_mapping(project.runner_directory, applied['alias'])
            notices = directory / 'parent-notices.jsonl'
            if notices.is_file():
                for line in reversed(notices.read_text(encoding='utf-8').splitlines()):
                    receipt = json.loads(line)
                    identity = receipt.get('identity', {})
                    if identity.get('type') != 'report-submitted':
                        continue
                    if (receipt.get('delivery') == 'not-delivered'
                            and receipt.get('error', {}).get('code') != 'delivery-unconfirmed'):
                        result['report_notification'] = _reported(
                            directory, applied['alias'], Path(identity['report']), True,
                        )
                    break
        return result
    try:
        _, directory = read_alias_mapping(project.runner_directory, applied['alias'])
        with (directory / 'launch.yml').open('rb') as lock:
            file_lock.flock(lock, file_lock.LOCK_EX)
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
    expected = {**proposal['after'], 'latest_task_event': applied['event_id']}
    if 'applied_budget' in applied:
        expected['budget'] = applied['applied_budget']
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
             'task_id': applied['task_id'], 'resumption': resumption,
             'caused_by_event_ids': [applied['event_id']], 'evidence_refs': []},
        )
    except (OSError, ValueError) as error:
        return {**result, 'recovery_status': 'resumed', 'resumption': resumption,
                'evidence_error': str(error)}
    return {**result, 'recovery_status': 'resumed', 'resumption': resumption}
