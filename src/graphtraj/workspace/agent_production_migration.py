"""Stopped-project cutover and recovery through the public migration command."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
from uuid import uuid4

import yaml

from agent_swarm import AgentControl, Caller
from graphtraj.configuration.project_configuration import load_project_configuration, runner_directory
from graphtraj.execution.runner_heartbeat import ownership_is_held
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.workspace.agent_cutover import _references, _rewrite_records, partition_snapshot
from graphtraj.workspace.agent_migration import migrate_agents
from graphtraj.workspace.migration_snapshot import MANIFEST, snapshot_project


def _stopped(root: Path) -> None:
    """Refuse a live or unconfirmed member; Main's stopped writes are operator-owned."""
    runner = runner_directory(root)
    for path in runner.glob('sessions/*/mapping.yml'):
        mapping = yaml.safe_load(path.read_text())
        terminal_path = path.parent / 'execution.yml'
        terminal = yaml.safe_load(terminal_path.read_text()) if terminal_path.is_file() else {}
        if (not terminal or terminal.get('outcome') not in {'completed', 'interrupted', 'runtime-error'}
                or terminal.get('terminal_confirmed') is False
                or (mapping.get('execution_id') and terminal.get('execution_id') != mapping['execution_id'])
                or ownership_is_held(path.parent, mapping.get('worker_pid', 0))):
            raise ValueError(f"Stop and confirm the retained execution before cutover: {mapping.get('alias', path.parent.name)}")
    for path in (root / '.graphtraj/swarm/control/agents').glob('*.json'):
        record = json.loads(path.read_text())
        if any(item.get('state') != 'ended' or item.get('terminal_confirmed') is False
               for item in record.get('executions', [])):
            raise ValueError(f"Stop and confirm the Agent before cutover: {record['agent']}")


def _facts(paths: list[Path]) -> dict:
    """Compare all retained file bytes and link spellings without following links."""
    result = {}
    for root in paths:
        for path in ([root] if root.is_file() else root.rglob('*')):
            if root.name == 'swarm' and path.relative_to(root).parts[:1] == ('live',):
                continue
            if path.is_symlink():
                result[str(path)] = ['link', os.readlink(path)]
            elif path.is_file() and not path.name.endswith('.sqlite3-shm'):
                with path.open('rb') as stream:
                    result[str(path)] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def _captured_unchanged(manifest: dict) -> None:
    """Require the specifically captured native sources to remain at that boundary."""
    for item in manifest['files']:
        if not item.get('stored'):
            continue
        path = Path(item['paths'][0])
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError('A captured native source changed after snapshot; keep writers stopped and retry.')


def _git(source: Path, *arguments: str) -> str:
    """Use Git's own worktree metadata operations, preserving its refusal reasons."""
    result = subprocess.run(['git', '-C', str(source), *arguments], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Git worktree operation failed.')
    return result.stdout


def _launch_arguments(value: object, moves: dict[str, str]) -> object:
    """Relocate Codex's duplicate CLI permission encoding without changing grants."""
    if isinstance(value, list):
        return [_launch_arguments(item, moves) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _launch_arguments(item, moves) for key, item in value.items()}
    if isinstance(result.get('arguments'), list):
        from graphtraj.runtimes.codex.codex_adapter import _toml_value

        arguments = list(result['arguments'])
        for index, argument in enumerate(arguments):
            if index and arguments[index - 1] == '-c' and argument.startswith('permissions='):
                permissions = tomllib.loads(argument)['permissions']
                arguments[index] = 'permissions=' + _toml_value(_references(permissions, moves))
            elif index and arguments[index - 1] in {'--cd', '-C'}:
                arguments[index] = _references(argument, moves, 'path')
        result['arguments'] = arguments
    return result


def _move_worktrees(source: Path, moves: dict[str, str]) -> list[tuple[str, str]]:
    """Move each registered linked worktree with Git; undo completed moves on failure."""
    completed = []
    try:
        for old, new in moves.items():
            Path(new).parent.mkdir(parents=True, exist_ok=True)
            _git(source, 'worktree', 'move', old, new)
            completed.append((old, new))
    except BaseException:
        for old, new in reversed(completed):
            _git(source, 'worktree', 'move', new, old)
        raise
    return completed


def _native_resources(staging: Path, root: Path, manifest: dict) -> tuple[dict[str, str], list[dict]]:
    """Move only project-owned Pi/DSH native resources out of Task evidence.

    Global Runtime homes remain references. Their files are never opened here.
    Missing historical native resources stay explicit rather than reconstructed.
    """
    from graphtraj.execution.task_agents import native_directory

    core = staging / '.graphtraj/core'
    records = list((core / 'runner').glob('sessions/*/mapping.yml'))
    records += list((core / 'state').glob('tasks/*/teams/*/traces/*/runner/session.yml'))
    moves, missing = {}, []
    for path in records:
        value = yaml.safe_load(path.read_text())
        mapping = value.get('retirement', {}).get('mapping', value)
        runtime, alias = mapping.get('runtime'), mapping.get('alias')
        if runtime not in {'pi', 'dsh'} or not alias:
            continue
        trace = Path(mapping['trace_file'])
        destination = native_directory(staging, alias, runtime)
        final = native_directory(root, alias, runtime)
        resources = ([(trace.with_suffix('.pi'), destination, final)] if runtime == 'pi' else [
            (path.parent / 'dsh-home', destination / 'dsh-home', final / 'dsh-home'),
            (trace.parent / 'dsh-native', destination / 'dsh-native', final / 'dsh-native')])
        for source, target, installed in resources:
            # Native material outside the captured project is not discovered.
            owner = next((name for name in ('state', 'runner') if source.is_relative_to(core / name)), None)
            if owner is None:
                missing.append({'agent': alias, 'path': str(source), 'missing': 'Native resource is outside retained project material.'})
                continue
            original = Path(manifest[owner + '_source']) / source.relative_to(core / owner)
            moves[str(source)] = str(installed)
            moves[str(original)] = str(installed)
            if not source.exists():
                missing.append({'agent': alias, 'path': str(original), 'missing': 'Retained native resource is unavailable.'})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError('Native migration destination already contains material; preserve it for comparison.')
            source.rename(target)
    return moves, missing


def _restore_native_references(root: Path, manifest: dict, moves: dict[str, str]) -> None:
    """Retain original reference targets without following or copying external data."""
    origins = {'state': Path(manifest['state_source']), 'runner': Path(manifest['runner_source']),
               'swarm': root / '.graphtraj/swarm'}
    for name, original in origins.items():
        for entry in manifest.get('links', {}).get(name, []):
            link = Path(_references(str(original / entry['path']), moves, 'path'))
            target = Path(_references(entry['resolved'], moves, 'path'))
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(os.path.relpath(target, link.parent))


def cutover_project(
    root: Path, snapshot: Path, *, writes_stopped: bool, main_session: str | None = None,
) -> dict:
    """Capture, verify and install one stopped project, retaining originals for recovery.

    The operator must stop all writers, including external Main entry hooks,
    throughout this command. This operation never stops an Agent itself and
    never supplies native trust approval. Failures retain the snapshot/staging
    evidence and restore moved directories and Git worktrees where possible.
    """
    root, snapshot = root.resolve(), snapshot.resolve()
    if not writes_stopped:
        raise ValueError('--writes-stopped is required after all project writers have stopped.')
    if (root / MANIFEST).exists() or (root / '.graphtraj/core').exists():
        raise ValueError('Cutover requires an original project without an existing core destination.')
    configuration = load_project_configuration(root)
    data = root / '.graphtraj'
    runner = runner_directory(root)
    _stopped(root)
    old_paths = [configuration.state, runner, data / 'swarm', data / 'config.yml', data / 'roles.yml', data / 'cli']
    before = _facts(old_paths)
    git_before = _git(configuration.project_root, 'worktree', 'list', '--porcelain')
    worktrees = {}
    for line in git_before.splitlines():
        if line.startswith('worktree '):
            path = Path(line.removeprefix('worktree '))
            if path.is_relative_to(configuration.agent_worktrees):
                if path == configuration.project_root:
                    raise ValueError('The Source Repository must remain outside the worktree directory being moved.')
                worktrees[str(path)] = str(data / 'core/worktrees' / path.relative_to(configuration.agent_worktrees))
    for path in configuration.agent_worktrees.glob('*'):
        if path.is_dir() and not any(Path(old).is_relative_to(path) for old in worktrees):
            raise ValueError(f'An unregistered worktree directory needs native reconciliation before cutover: {path}')
    snapshot_project(root, snapshot)
    manifest = yaml.safe_load((snapshot / MANIFEST).read_text())
    staging = snapshot.with_name(snapshot.name + '-cutover')
    snapshot_project(snapshot, staging)
    if any(item.get('kind') == 'main' for item in manifest['sources']) and not main_session:
        raise ValueError('Supply --main-session from the actual Main binding before production cutover.')
    imported = migrate_agents(staging, main_session=main_session)
    verified = migrate_agents(staging, verify=True, against=snapshot)
    if not verified['verification']['matches']:
        raise ValueError('Migration verification failed; retained input and staging were not installed.')
    partitioned = partition_snapshot(staging)
    if partitioned['agents']['missing']:
        raise ValueError('Some stopped identities lack continuation settings; retained staging was not installed.')
    staged_core = staging / '.graphtraj/core'
    staged_swarm = staging / '.graphtraj/swarm'
    native_moves, native_missing = _native_resources(staging, root, manifest)
    moves = {str(staging / '.graphtraj/core'): str(data / 'core'),
             str(staging / '.graphtraj/swarm'): str(data / 'swarm'),
             str(configuration.state): str(data / 'core/state'), str(runner): str(data / 'core/runner'),
             str(configuration.agent_worktrees): str(data / 'core/worktrees'),
             **worktrees, **native_moves}
    _rewrite_records(staged_core / 'state', moves)
    _rewrite_records(staged_core / 'runner', moves)
    for directory in (staged_core / 'runner', staged_core / 'state'):
        for path in directory.rglob('launch.yml'):
            if not path.is_symlink():
                write_yaml_durably(path, _launch_arguments(yaml.safe_load(path.read_text()), moves))
    # Runtime cwd and launch paths are owned settings, not native transcript edits.
    control = AgentControl(staged_swarm, {})
    for path in (staged_swarm / 'control/agents').glob('*.json'):
        record = json.loads(path.read_text())
        settings = _launch_arguments(_references(record['settings'], moves), moves)
        if (record['runtime'] in {'pi', 'dsh'} and record['host'] == 'graphtraj-tasks'
                and isinstance(settings.get('adapter_request'), dict)):
            from graphtraj.execution.task_agents import native_directory

            settings['adapter_request']['native_directory'] = str(native_directory(
                root, settings.get('alias', record['name']), record['runtime']))
        control.configure_stopped(record['agent'], settings, Caller(record['host'], record['parent']))
    original_config = yaml.safe_load((data / 'config.yml').read_text())
    original_config['paths']['state'] = '.graphtraj/core/state'
    original_config['paths']['agent_worktrees'] = '.graphtraj/core/worktrees'
    write_yaml_durably(staged_core / 'config.yml', original_config)
    # The live originals become the backup, so copied rehearsal backups/views
    # must not become a second production authority or fake Git worktrees.
    shutil.rmtree(staged_core / 'backups')
    if (staged_core / 'worktrees').exists():
        shutil.rmtree(staged_core / 'worktrees')
    backup = data / 'backups' / ('agents-' + uuid4().hex)
    backup.mkdir(parents=True)
    retained = {str(path): str(backup / name) for path, name in zip(old_paths, ['state', 'runner', 'swarm', 'config.yml', 'roles.yml', 'cli']) if path.exists()}
    link_targets = {}
    for old, new in worktrees.items():
        for name in ('.state', 'CONTEXT.md', 'docs'):
            link = Path(old) / name
            if link.is_symlink():
                link_targets[str(Path(new) / name)] = os.readlink(link)
    recovery = {'project': str(root), 'snapshot': str(snapshot), 'source_repository': str(configuration.project_root),
                'originals': retained, 'worktrees': worktrees, 'worktree_links': link_targets}
    write_yaml_durably(backup / 'migration.yml', recovery)
    _stopped(root)
    if before != _facts(old_paths) or git_before != _git(configuration.project_root, 'worktree', 'list', '--porcelain'):
        raise ValueError('Project changed during preparation; preserve the evidence and retry in a stopped window.')
    _captured_unchanged(manifest)
    moved = []
    installed = []
    try:
        for old, saved in retained.items():
            Path(old).rename(saved)
            moved.append((old, saved))
        # Keep the new config unselected until its data and Git paths exist.
        staged_config = staged_core / 'config.yml'
        staged_config.rename(staging / 'cutover-config.yml')
        installed.append(data / 'core')
        shutil.copytree(staged_core, data / 'core', symlinks=True)
        installed.append(data / 'swarm')
        shutil.copytree(staged_swarm, data / 'swarm', symlinks=True)
        _restore_native_references(root, manifest, moves)
        _move_worktrees(configuration.project_root, worktrees)
        for path, target in link_targets.items():
            link = Path(path)
            old_link = next(Path(old) / Path(path).relative_to(new) for old, new in worktrees.items() if Path(path).is_relative_to(new))
            resolved = os.path.abspath(old_link.parent / target)
            replacement = _references(resolved, moves, 'path')
            link.unlink()
            link.symlink_to(os.path.relpath(replacement, link.parent))
        shutil.copy2(staging / 'cutover-config.yml', data / 'core/config.yml')
        recovery['installed_facts'] = _facts([data / 'core/state', data / 'core/runner', data / 'swarm'])
        write_yaml_durably(backup / 'migration.yml', recovery)
    except BaseException:
        # Recovery uses the same retained manifest; do not discard failed data.
        for old, new in reversed(list(worktrees.items())):
            if Path(new).exists() and not Path(old).exists():
                _git(configuration.project_root, 'worktree', 'move', new, old)
                for path, target in link_targets.items():
                    if Path(path).is_relative_to(new):
                        link = Path(old) / Path(path).relative_to(new)
                        link.unlink(missing_ok=True)
                        link.symlink_to(target)
        for path in installed:
            if path.exists():
                path.rename(backup / ('failed-' + path.name))
        for old, saved in reversed(moved):
            Path(saved).rename(old)
        raise
    finally:
        if (staging / 'cutover-config.yml').exists():
            shutil.copy2(staging / 'cutover-config.yml', staged_core / 'config.yml')
    return {'cutover': 'installed', 'backup': str(backup), 'snapshot': str(snapshot),
            'worktrees': worktrees, 'identities': partitioned['agents'],
            'native_missing': [item for item in imported['native_results'] if item.get('missing')],
            'native_resource_missing': native_missing,
            'missing_links': imported['missing_links'],
            'legacy_native_registrations': imported['legacy_native_registrations'],
            'legacy_codex_policy': 'Retained declarations remain visible; old calls fail and direct callers to MCP. Native history is unchanged and old business callbacks are not restored.',
            'next': 'Use this same installed version. Native host trust and same-ID resume require their normal public entry; no host was started. Restore is available before new execution/state writes; afterward preserve and reconcile the new history.'}


def restore_cutover(root: Path, backup: Path, *, writes_stopped: bool) -> dict:
    """Restore retained originals and Git paths, keeping post-cutover data for inspection."""
    root, backup = root.resolve(), backup.resolve()
    if not writes_stopped:
        raise ValueError('--writes-stopped is required before recovery.')
    if backup.parent != root / '.graphtraj/backups':
        raise ValueError('Choose this project\'s retained Agent migration backup.')
    record = yaml.safe_load((backup / 'migration.yml').read_text())
    if record['project'] != str(root) or not (root / '.graphtraj/core/config.yml').is_file():
        raise ValueError('The project does not have the selected installed cutover.')
    _stopped(root)
    current = _facts([root / '.graphtraj/core/state', root / '.graphtraj/core/runner', root / '.graphtraj/swarm'])
    if current != record.get('installed_facts'):
        raise ValueError('Post-cutover data changed. Preserve and reconcile the new history before recovery; nothing was restored.')
    if any(not Path(saved).exists() for saved in record['originals'].values()):
        raise ValueError('Original backup is incomplete; no recovery was applied.')
    if any(Path(old).exists() and Path(old) != root / '.graphtraj/swarm' for old in record['originals']):
        raise ValueError('An original destination is occupied; preserve it before recovery.')
    if any((backup / ('after-' + name)).exists() for name in ('core', 'swarm')):
        raise ValueError('Recovery evidence already exists; preserve it for diagnosis.')
    source = Path(record['source_repository'])
    _move_worktrees(source, {new: old for old, new in record['worktrees'].items()})
    for old, new in record['worktrees'].items():
        for path, target in record['worktree_links'].items():
            if Path(path).is_relative_to(new):
                link = Path(old) / Path(path).relative_to(new)
                link.unlink(missing_ok=True)
                link.symlink_to(target)
    for name in ('core', 'swarm'):
        (root / '.graphtraj' / name).rename(backup / ('after-' + name))
    for old, saved in record['originals'].items():
        Path(saved).rename(old)
    return {'restored': str(backup), 'retained_after_cutover': str(backup / 'after-core'),
            'next': 'Keep writers stopped until the matching previous installation and native host entry are selected.'}
