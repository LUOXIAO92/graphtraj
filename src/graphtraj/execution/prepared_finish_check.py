"""Retain approved native checker preparations in existing execution records."""

from __future__ import annotations

import secrets
from importlib.resources import files
from pathlib import Path
from typing import Iterator

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.main_finalize import PREFIX, parse_check_result
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    read_alias_mapping, require_execution_allowed, unestablished_execution_allocation,
)
from graphtraj.graph.ticket_graph import read_graph
from graphtraj.runtimes.runtime_adapter import select_runtime_adapter
from graphtraj.workspace.runner_project import discover_runner_directory


def owner(host: object, stopping: bool = False) -> tuple[Path, object, dict]:
    """Require the actual registered Main and its retained native connection."""
    if host.closed or (host.closing and not stopping) or not host.alias:
        raise RunnerError('authority-denied', 'An open registered Main is required.')
    runner = discover_runner_directory(host.cwd)
    mapping, _ = read_alias_mapping(runner, host.alias)
    if mapping.get('purpose') != 'main':
        raise RunnerError('authority-denied', 'Only the registered Main may operate a prepared check.')
    if not stopping:
        require_execution_allowed(runner, host.alias, mapping)
    connection = host.finish_connection
    if not connection:
        raise RunnerError('unsupported-operation', 'The Main has no retained native host connection.')
    return runner, select_runtime_adapter(mapping['runtime']), connection


def records(host: object, runner: Path) -> Iterator[tuple[Path, dict]]:
    """Find only this Main's existing checker execution preparations, preserving history."""
    for directory in (runner / 'sessions').iterdir():
        if unestablished_execution_allocation(directory):
            continue
        mapping, directory = read_alias_mapping(runner, directory.name)
        if mapping.get('purpose') != 'checker' or mapping.get('parent') != host.alias:
            continue
        path = directory / 'execution.yml'
        if path.exists():
            document = yaml.safe_load(path.read_text())
            if isinstance(document, dict) and isinstance(document.get('finish_check'), dict):
                yield directory, document['finish_check']


def save(directory: Path, record: dict) -> None:
    """Update this preparation's lifecycle in the existing execution evidence file."""
    write_yaml_durably(directory / 'execution.yml', {'finish_check': record})


def material(record: dict) -> dict:
    """Expose exact native arguments and the follow-up public request, never credentials."""
    return {'systemMessage': f'{PREFIX} start: Preparing the registered native checker.\n'
            f'{PREFIX} prepare: Execute only the returned native action.',
            'status': record['state'], 'checker_alias': record['checker_alias'],
            'checked_turn': record['preparation']['turn'],
            'native_action': record['preparation']['native_action'],
            'configuration_status': record['preparation']['configuration_status'],
            'next_operation': {'action': 'execute', 'feature': 'finish_check', 'arguments': {
                'action': 'collect', 'checker_alias': record['checker_alias'],
                'task_name': '<actual native returned task_name>'}}}


def retain_checker(host: object, alias: str | None = None) -> object:
    """Keep the existing read-only GraphTraj checker interface on creation/restoration."""
    child = host.register_checker(host.receiver, resume=alias)
    child.allowed_features = {'agent_identity', 'ticket_graph', 'alias_status'}
    host.prepared_checks[child.alias] = child
    return child


def prepare(host: object, prompt: str | None = None, turn: str | None = None) -> dict:
    """Register one checker per checked turn and return its native full-history action."""
    runner, adapter, connection = owner(host)
    method = getattr(adapter, 'prepare_main_check', None)
    if method is None:
        raise RunnerError('unsupported-operation', 'This Runtime has no prepared checker interface.')
    if prompt is None:
        configuration = load_project_configuration(host.cwd)
        # Fail explicitly if project state is unreadable, but let the checker
        # identify and query its current task instead of copying all history.
        read_graph(configuration.state)
        prompt = files('graphtraj').joinpath('prompts/main_finalize_check.md').read_text()
    native = method(connection, 'finish_check_' + secrets.token_hex(16), prompt, turn)
    for directory, record in records(host, runner):
        # An explicit cancellation retains the old request as evidence and
        # permits a fresh public prepare, including after an owner update.
        if record['state'] == 'cancelled':
            continue
        if (record['preparation']['turn'] == native['turn']
                and record['preparation'].get('input_ids') == native['input_ids']
                and not record.get('actionable_delivered')):
            if record['state'] == 'prepared':
                if record['checker_alias'] not in host.prepared_checks:
                    retain_checker(host, record['checker_alias'])
                return material(record)
            if record['state'] == 'running':
                return {'status': 'running', 'checker_alias': record['checker_alias'],
                        'next_operation': {'action': 'execute', 'feature': 'finish_check', 'arguments': {
                            'action': 'collect', 'checker_alias': record['checker_alias'],
                            'wait_seconds': 30}}}
            return {'status': record['state'], 'checker_alias': record['checker_alias'],
                    'result': record.get('result'), 'native_observation': record.get('native_observation')}
        if record['state'] in ('prepared', 'running'):
            operate(host, 'cancel', record['checker_alias'], None, 0)
    child = retain_checker(host)
    _, directory = read_alias_mapping(runner, child.alias)
    record = {'state': 'prepared', 'checker_alias': child.alias, 'parent': host.alias,
              'preparation': native}
    save(directory, record)
    return material(record)


def operate(
    host: object,
    action: str,
    checker_alias: str | None,
    task_name: str | None,
    wait_seconds: float,
) -> dict:
    """Collect or cancel only a preparation owned by the calling registered Main."""
    runner, adapter, connection = owner(host, stopping=action == 'cancel')
    if action == 'prepare':
        return prepare(host)
    mapping, directory = read_alias_mapping(runner, checker_alias or '')
    if mapping.get('purpose') != 'checker' or mapping.get('parent') != host.alias:
        raise RunnerError('authority-denied', 'The preparation belongs to another Agent.')
    document = yaml.safe_load((directory / 'execution.yml').read_text())
    record = document.get('finish_check') if isinstance(document, dict) else None
    if not isinstance(record, dict) or record.get('parent') != host.alias:
        raise RunnerError('operation-failed', 'The checker has no valid preparation.')
    if record['state'] in ('completed', 'cancelled', 'failed'):
        return {'status': record['state'], 'checker_alias': checker_alias,
                'result': record.get('result'), 'native_observation': record.get('native_observation')}
    if checker_alias not in host.prepared_checks:
        retain_checker(host, checker_alias)
    if action == 'collect' and not task_name and not record.get('native'):
        raise RunnerError('invalid-input', 'Supply the actual returned native task_name.')

    def allowed() -> None:
        """Honor actual Main/checker stops during native waiting."""
        owner(host)
        require_execution_allowed(runner, checker_alias, mapping)

    def associated(native: dict) -> None:
        """Bind only verified native provenance; never promote another existing identity."""
        from graphtraj.execution.host_adoption import execution_associations

        for other, handle in execution_associations(runner):
            if handle['runtime'] == connection['runtime'] and handle['session'] == native['session']:
                if other['alias'] != checker_alias:
                    raise RunnerError('authority-denied', 'Native execution already belongs to another Agent.')
        if record.get('native') and record['native']['session'] != native['session']:
            raise RunnerError('authority-denied', 'A preparation cannot change its native execution.')
        write_yaml_durably(directory / 'native.yml', {
            **connection, 'session': native['session'], 'parent': host.alias,
        })
        record.update(state='running', native=native)
        save(directory, record)

    try:
        native = adapter.observe_main_check(connection, record['preparation'],
                                            task_name or record.get('native', {}).get('task_path'),
                                            wait_seconds, action == 'cancel', allowed, associated)
        record['native_observation'] = native
        record['state'] = native['state']
        if native['state'] == 'failed':
            record['result'] = {'status': 'error', 'reason': native['reason'], 'nodes': []}
        if native['state'] == 'completed':
            try:
                parsed = parse_check_result(native['output'])
            except ValueError as error:
                record['state'] = 'failed'
                record['result'] = {'status': 'error', 'reason': f'Native checker result is invalid: {error}',
                                    'nodes': []}
            else:
                if native.get('configuration_confirmed') is not True:
                    record['state'] = 'failed'
                    record['result'] = {'status': 'error', 'reason': native['configuration_error'], 'nodes': []}
                else:
                    record['result'] = parsed
                    record['actionable_delivered'] = parsed['status'] == 'actionable'
        save(directory, record)
    finally:
        if record['state'] in ('completed', 'cancelled', 'failed'):
            child = host.prepared_checks.pop(checker_alias, None)
            if child is not None:
                child.close()
    result = {'status': record['state'], 'checker_alias': checker_alias,
              'native_observation': record.get('native_observation')}
    if record.get('result'):
        result['result'] = record['result']
        result['hook_response'] = adapter.finalize_response(record['result'], True)
    else:
        result['systemMessage'] = f"{PREFIX} {record['state']}: Native checker lifecycle observed."
    return result


def close_preparations(host: object) -> None:
    """Cancel retained live native checks before releasing their owning Main."""
    errors = []
    for alias in list(host.prepared_checks):
        try:
            operate(host, 'cancel', alias, None, 5)
        except Exception as error:
            errors.append(error)
        finally:
            child = host.prepared_checks.pop(alias, None)
            if child is not None:
                child.close()
    if errors:
        raise RunnerError('operation-failed', f'Native checker closure failed: {errors[0]}') from errors[0]
