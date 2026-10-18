"""Rehearse the ownership partition on an isolated, retained project snapshot.

Task/Team/Worldline records stay with GraphTraj. Native archives and imported
stopped Agent identities belong to agent_swarm. The original snapshot remains
the backup; this operation never edits a live Harness or activates a Runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import yaml

from agent_swarm import AgentControl, AgentsError
from graphtraj.configuration.project_configuration import configuration_file, load_project_configuration
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_transport import RUNTIME_DIAGNOSTIC_FILES
from graphtraj.workspace.migration_snapshot import MANIFEST, copy_records, install_links, source_map


PATH_FIELDS = frozenset({
    'path', 'state', 'state_directory', 'current_definition', 'definition_file',
    'task_file', 'task_directory', 'retained_batch_file', 'trace_file',
    'report_file', 'report_files', 'evidence_refs', 'result_refs', 'worktree',
    'worktree_path', 'worktree_root', 'control_directory', 'runner_directory',
    'read_paths', 'write_paths', 'deny_read', 'deny_write', 'read', 'write',
})


def _references(value: object, moves: dict[str, str], field: str = '') -> object:
    """Relocate structural references, never authored prose or native payloads."""
    if isinstance(value, dict):
        return {key: _references(item, moves, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_references(item, moves, field) for item in value]
    if isinstance(value, str) and field in PATH_FIELDS:
        for old in sorted(moves, key=len, reverse=True):
            if value == old or value.startswith(old + '/'):
                return moves[old] + value[len(old):]
    return value


def _rewrite_records(directory: Path, moves: dict[str, str]) -> None:
    """Rewrite only GraphTraj metadata; original records remain in the backup."""
    for path in directory.rglob('*.yml'):
        if path.is_symlink() or not (
            path.name in RUNTIME_DIAGNOSTIC_FILES
            or path.name in {'task.yml', 'team.yml', 'task-backups.yml', 'child-registration.yml'}
            or path.parent.name == 'batches'
        ):
            continue
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
        rewritten = _references(document, moves)
        if rewritten != document:
            write_yaml_durably(path, rewritten)
    worldline = directory / 'worldline'
    for path in worldline.glob('*.jsonl'):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        changed = [_references(row, moves) for row in rows]
        if changed != rows:
            path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in changed), encoding='utf-8')


def _import_controls(state: Path, runner: Path, swarm: Path) -> dict:
    """Retain existing aliases and parents; import only confirmed stopped history."""
    paths = list((runner / 'sessions').glob('*/mapping.yml'))
    paths += list(state.glob('tasks/*/teams/*/traces/*/runner/session.yml'))
    mappings = {}
    for path in paths:
        record = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        retired = record.get('retirement')
        mapping = retired.get('mapping', {}) if retired else record
        if mapping.get('alias'):
            mappings[mapping['alias']] = (path, mapping, retired)
    references = {alias: mapping.get('agent') or alias for alias, (_, mapping, _) in mappings.items()}
    control = AgentControl(swarm, {})
    imported, missing = [], []
    for alias, (path, mapping, retired) in mappings.items():
        if mapping.get('agent'):
            # The already independent identity is copied, never reconstructed.
            continue
        directory = path.parent
        terminal_path = directory / 'execution.yml'
        terminal = yaml.safe_load(terminal_path.read_text(encoding='utf-8')) if terminal_path.is_file() else {}
        if not retired and (not terminal or (mapping.get('execution_id') and terminal.get('execution_id')
                                             and mapping['execution_id'] != terminal['execution_id'])
                            or terminal.get('outcome') not in {'completed', 'interrupted', 'runtime-error'}
                            or terminal.get('terminal_confirmed') is False):
            missing.append({'agent': alias, 'missing': 'No retained confirmed terminal execution; control not fabricated.'})
            continue
        launch_path = directory / 'launch.yml'
        launch = yaml.safe_load(launch_path.read_text(encoding='utf-8')) if launch_path.is_file() else {}
        if not mapping.get('session') or not isinstance(launch.get('adapter_request'), dict):
            missing.append({'agent': alias, 'missing': 'Native Session or retained continuation settings unavailable.'})
            continue
        parent = references.get(mapping.get('parent'), mapping.get('parent'))
        settings = {'alias': alias, 'cwd': mapping['worktree_path'],
                    'adapter_request': launch['adapter_request'], 'connection': launch.get('connection', {}),
                    'evidence': launch.get('context_evidence', {})}
        ended = []
        if terminal:
            ended.append({'id': terminal.get('execution_id', mapping.get('execution_id')),
                          'state': 'ended', 'outcome': terminal['outcome'],
                          'last_message': terminal.get('last_agent_message'),
                          'terminal_confirmed': terminal.get('terminal_confirmed', True),
                          'process': {}, 'ended_at': terminal.get('ended_at')})
        record = {'agent': alias, 'name': alias, 'runtime': mapping['runtime'],
                  'host': 'graphtraj-tasks', 'parent': parent,
                  'creator': {'host': 'graphtraj-tasks', 'agent': parent, 'session': None},
                  'session': mapping['session'], 'sessions': [mapping['session']],
                  'settings': settings, 'created_at': None,
                  'retired_at': 'unknown' if retired else None, 'executions': ended}
        if retired:
            record['missing'] = [{'path': 'retired_at', 'reason': 'Retirement retained without its original time.'}]
        try:
            control.import_agent(record)
        except AgentsError as error:
            missing.append({'agent': alias, 'missing': str(error)})
            continue
        mapping['agent'] = alias
        if retired:
            retained = yaml.safe_load(path.read_text(encoding='utf-8'))
            retained['retirement']['mapping'] = mapping
            write_yaml_durably(path, retained)
        else:
            write_yaml_durably(path, mapping)
        imported.append(alias)
    return {'imported': imported, 'missing': missing}


def partition_snapshot(root: Path) -> dict:
    """Move an offline copy into core/swarm, retaining its old metadata backup.

    This proves the data transformation only. The copied Git worktree inventory
    and original Runtime cwd remain provenance; no live worktree, native trust
    configuration or running host connection is changed.
    """
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        raise ValueError('Ownership partition currently requires an isolated public snapshot.')
    data = root / '.graphtraj'
    core = data / 'core'
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    if (core / 'config.yml').is_file():
        gaps = _backup_links(root, manifest)
        return {'partition': 'already-migrated', 'core': str(core),
                'missing_links': gaps, 'production_cutover': False}
    if core.exists():
        raise ValueError('Incomplete core destination exists; preserve it for diagnosis.')
    configuration = load_project_configuration(root)
    state, runner = configuration.state, data / 'migration-runner'
    original_config = configuration_file(root)
    document = yaml.safe_load(original_config.read_text(encoding='utf-8'))
    original_state = manifest['state_source']
    original_runner = manifest['runner_source']
    moves = {
        original_state: str(core / 'state'), original_runner: str(core / 'runner'),
        str(state): str(core / 'state'), str(runner): str(core / 'runner'),
        '.graphtraj/state': '.graphtraj/core/state',
        '.graphtraj/runner': '.graphtraj/core/runner',
    }
    core.mkdir()
    backup = core / 'backups' / 'before-agent-partition'
    backup.mkdir(parents=True)
    committed = False
    added_controls = []
    state_links, runner_links = [], []
    try:
        state_links = copy_records(state, core / 'state')
        runner_links = copy_records(runner, core / 'runner')
        roots = {str(state): core / 'state', str(runner): core / 'runner', str(data): data}
        gaps = install_links(core / 'state', state_links, roots, {})
        gaps += install_links(core / 'runner', runner_links, roots, {})
        _rewrite_records(core / 'state', moves)
        _rewrite_records(core / 'runner', moves)
        staged_agents = core / 'agent-import'
        existing_controls = data / 'swarm/control'
        if existing_controls.is_dir():
            copy_records(existing_controls, staged_agents / 'control')
        controls = _import_controls(core / 'state', core / 'runner', staged_agents)
        # SQLite is retained in the backup, not a second daily Session reader.
        legacy = core / 'state/sessions'
        if legacy.exists():
            shutil.rmtree(legacy)
        document['paths']['state'] = '.graphtraj/core/state'
        # The offline .state views are portable. Real native cwd/Git movement is
        # a distinct stopped-host operation and cannot be simulated by a copy.
        worktrees = configuration.agent_worktrees
        if worktrees.is_dir():
            links = copy_records(worktrees, core / 'worktrees')
            gaps += install_links(core / 'worktrees', links, roots, {})
            document['paths']['agent_worktrees'] = '.graphtraj/core/worktrees'
        roles = data / 'migration-input/roles.yml'
        if roles.is_file():
            shutil.copy2(roles, core / 'roles.yml')
        state.rename(backup / 'state')
        if runner.exists():
            runner.rename(backup / 'runner')
        original_config.rename(backup / 'config.yml')
        gaps += _backup_links(root, manifest)
        for path in (staged_agents / 'control/agents').glob('*.json'):
            target = data / 'swarm/control/agents' / path.name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                path.rename(target)
                added_controls.append(target)
        write_yaml_durably(core / 'config.yml', document)
        if staged_agents.exists():
            shutil.rmtree(staged_agents)
        committed = True
        return {'partition': 'migrated', 'core': str(core), 'backup': str(backup),
                'agents': controls, 'missing_links': gaps, 'production_cutover': False,
                'remaining': ['Live Git worktree/native cwd transition and host trust adoption are not exercised by an offline snapshot.',
                              'Legacy Task runtime resources and Main host bindings still require native control adoption.']}
    finally:
        if not committed:
            for path in added_controls:
                path.unlink(missing_ok=True)
            for name, destination in [('state', state), ('runner', runner), ('config.yml', original_config)]:
                if (backup / name).exists() and not destination.exists():
                    (backup / name).rename(destination)
            for directory, entries in ((state, state_links), (runner, runner_links)):
                for entry in entries:
                    path = directory / entry['path']
                    path.unlink(missing_ok=True)
                    path.symlink_to(entry['target'])
            shutil.rmtree(core)


def _backup_links(root: Path, manifest: dict) -> list[dict]:
    """Keep moved backup links readable from the captured inputs, including replay."""
    backup = root / '.graphtraj/core/backups/before-agent-partition'
    roots = {manifest['state_source']: backup / 'state',
             manifest['runner_source']: backup / 'runner'}
    captured = source_map(root, manifest)
    gaps = []
    for name in ('state', 'runner'):
        gaps += install_links(backup / name, manifest.get('links', {}).get(name, []), roots, captured)
    return gaps
