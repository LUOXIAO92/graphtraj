"""Stopped-project cutover and recovery through the public migration command."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
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
from graphtraj.workspace.task_migration import foreign_entries


def _terminal_confirmed(turn_file: Path) -> bool:
    """Accept the original terminal evidence or the Runner's retained confirmation receipt.

    An unconfirmed failure is never rewritten; interrupt confirms its end in a
    separate receipt, which the Runner's own stop check (read_terminal_outcome) accepts.
    """
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import read_terminal_outcome

    try:
        read_terminal_outcome(turn_file)
    except RunnerError:
        return False
    return True


# agent_swarm ends whose owner or worker vanished without a recorded end
# (user-approved scheme B: owner-exited; B+: RUNTIME_WORKER_FAILED).
CARRIED_UNCONFIRMED_CODES = frozenset({'owner-exited', 'RUNTIME_WORKER_FAILED'})


def _carried_unconfirmed(execution: dict) -> bool:
    """The single rule for which unconfirmed swarm end cutover may carry.

    The end must be one of the approved error codes with a recorded worker,
    and the worker and any recorded Runtime process must be rechecked as gone
    now. A process that cannot be checked counts as alive. A Runtime that was
    never recorded cannot be checked; it is reported, not assumed to exist.
    """
    from agent_swarm.control import _alive

    process = execution.get('process') or {}
    worker = process.get('worker_pid')
    return (execution.get('state') == 'ended' and execution.get('terminal_confirmed') is False
            and (execution.get('error') or {}).get('code') in CARRIED_UNCONFIRMED_CODES
            and isinstance(worker, int) and not isinstance(worker, bool) and worker > 0
            and not _alive(worker) and not _alive(process.get('runtime_pid')))


def _owner_exited(agent: str, execution: dict) -> dict | None:
    """Describe an unconfirmed swarm execution cutover carries, or ``None``.

    The execution keeps terminal_confirmed false; nothing here confirms its end.
    """
    if not _carried_unconfirmed(execution):
        return None
    process = execution['process']
    entry = {'agent': agent, 'execution': execution.get('id'), 'error_code': execution['error']['code'],
             'worker_pid': process['worker_pid'], 'runtime_pid': process.get('runtime_pid'),
             'worker_alive': False, 'runtime_alive': False,
             'terminal_confirmed': 'retained false; not confirmed by cutover'}
    if process.get('runtime_pid') is None:
        entry['runtime_alive'] = None
        entry['runtime_note'] = 'runtime_pid was never recorded; whether a Runtime started cannot be verified.'
    return entry


def stop_facts(root: Path) -> dict:
    """Read every cutover stop blocker and accepted gap, without writing anything."""
    from graphtraj.execution.runner_status import is_session_mapping

    runner = runner_directory(root)
    blocking, unavailable, owner_exited = [], [], []
    for path in sorted(runner.glob('sessions/*/mapping.yml')):
        mapping = yaml.safe_load(path.read_text())
        alias = mapping.get('alias', path.parent.name)
        terminal_path = path.parent / 'execution.yml'
        terminal = yaml.safe_load(terminal_path.read_text()) if terminal_path.is_file() else {}
        held = ownership_is_held(path.parent, mapping.get('worker_pid', 0))
        if not terminal and not held and not mapping.get('execution_id') and not is_session_mapping(mapping):
            unavailable.append({'alias': alias,
                                'missing': 'Historical binding has no current execution schema; activity and continuation are not inferred.'})
            continue
        if (not terminal or terminal.get('outcome') not in {'completed', 'interrupted', 'runtime-error'}
                or (mapping.get('execution_id') and terminal.get('execution_id') != mapping['execution_id'])
                or held or not _terminal_confirmed(terminal_path)):
            blocking.append({'runner': alias, 'message': (
                f'Stop and confirm the retained execution before cutover: {alias}. '
                'Its direct parent confirms an unconfirmed end through the public interrupt '
                '(agents interrupt), which retains a terminal-confirmation receipt.')})
    for path in sorted((root / '.graphtraj/swarm/control/agents').glob('*.json')):
        record = json.loads(path.read_text())
        for execution in record.get('executions', []):
            if execution.get('state') == 'ended' and execution.get('terminal_confirmed') is not False:
                continue
            accepted = _owner_exited(record['agent'], execution)
            if accepted is None:
                blocking.append({'swarm': record['agent'], 'execution': execution.get('id'),
                                 'message': f"Stop and confirm the Agent before cutover: {record['agent']}"})
            else:
                owner_exited.append(accepted)
    configuration = load_project_configuration(root)
    listing = _git(configuration.project_root, 'worktree', 'list', '--porcelain')
    try:
        moves = _worktree_moves(configuration, root / '.graphtraj', listing)
    except ValueError as error:
        blocking.append({'worktrees': str(configuration.agent_worktrees), 'message': str(error)})
        moves = {}
    return {'blocking': blocking, 'control_missing': unavailable, 'unconfirmed_swarm_executions': owner_exited,
            'worktree_moves': _worktree_plan(listing, moves),
            'claude_continuations': [_continuation_plan(item) for item in _claude_continuations(root, moves)]}


def _worktree_plan(listing: str, moves: dict[str, str]) -> list[dict]:
    """Show what cutover does to every registered worktree, read-only.

    Worktrees outside the moved root (including prunable ones) stay untouched:
    cutover never moves, repairs or prunes them.
    """
    nested = _nested(moves)
    plan = []
    for block in listing.strip().split('\n\n'):
        lines = block.splitlines()
        old = lines[0].removeprefix('worktree ')
        prunable = next((line.removeprefix('prunable ') for line in lines if line.startswith('prunable')), False)
        action = 'repair' if old in nested else 'move' if old in moves else 'untouched'
        entry = {'old': old, 'new': moves.get(old), 'action': action, 'prunable': prunable}
        if action != 'untouched':
            entry['links'] = {name: os.readlink(Path(old) / name) for name in ('.state', 'CONTEXT.md', 'docs')
                              if (Path(old) / name).is_symlink()}
        plan.append(entry)
    return plan


def _continuation_plan(item: dict) -> dict:
    """Show one planned Claude continuation copy and the files it would read and add."""
    if 'status' in item:
        return {key: item.get(key) for key in ('session', 'old', 'new', 'status', 'reason')}
    home = Path(item['home'])
    source = _claude_project(home, item['old'])
    if not source.is_dir():
        source = _claude_project(home, os.path.realpath(item['old']))
    target = _claude_project(home, item['new'])
    names = (item['session'] + '.jsonl', item['session'])
    return {'session': item['session'], 'old': item['old'], 'new': item['new'], 'home': item['home'],
            'source_exists': any((source / name).exists() for name in names),
            'target_exists': any((target / name).exists() for name in names)}


def _stopped(root: Path) -> dict:
    """Refuse a live or unconfirmed member; Main's stopped writes are operator-owned."""
    facts = stop_facts(root)
    if facts['blocking']:
        others = len(facts['blocking']) - 1
        raise ValueError(facts['blocking'][0]['message']
                         + (f' ({others} more; list them with migrate-agents --check-stopped).' if others else ''))
    return facts


def _relocate_owner_exited(swarm: Path, agent: str, settings: dict) -> None:
    """Replace only the staged copy's settings for an Agent with an accepted owner-exited execution.

    agent_swarm's configure_stopped rightly refuses unconfirmed executions and
    stays unchanged. Cutover owns this staging copy, so it writes the settings
    under the same per-Agent lock, atomic replacement and JSON form agent_swarm
    uses; executions, including terminal_confirmed false and error, are kept.
    """
    from agent_swarm.locks import exclusive

    path = swarm / 'control' / 'agents' / f'{agent}.json'
    with exclusive(swarm / 'live' / 'agents' / f'{agent}.lock'):
        record = json.loads(path.read_text(encoding='utf-8'))
        record['settings'] = settings
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.record-')
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=True))
        os.replace(temporary, path)


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


def _nested(moves: dict[str, str]) -> dict[str, str]:
    """Return the moved worktrees that lie inside another moved worktree.

    Their directories travel with that outer worktree, so Git only needs its
    administrative path repaired at the new location.
    """
    return {old: new for old, new in moves.items()
            if any(old != other and Path(old).is_relative_to(other) for other in moves)}


def _move_worktrees(source: Path, moves: dict[str, str]) -> list[tuple[str, str]]:
    """Move each outermost linked worktree with Git, then repair nested ones.

    A failure moves completed outer worktrees back and repairs the nested
    ones at their original paths again.
    """
    nested = _nested(moves)
    completed = []
    try:
        for old, new in moves.items():
            if old in nested:
                continue
            Path(new).parent.mkdir(parents=True, exist_ok=True)
            _git(source, 'worktree', 'move', old, new)
            completed.append((old, new))
        if nested:
            _git(source, 'worktree', 'repair', *nested.values())
    except BaseException:
        _return_worktrees(source, dict(completed), nested)
        raise
    return completed


def _return_worktrees(source: Path, moves: dict[str, str], nested: dict[str, str]) -> None:
    """Move outer worktrees that reached their new path back; repair nested ones there."""
    for old, new in reversed(list(moves.items())):
        if old not in nested and Path(new).exists() and not Path(old).exists():
            _git(source, 'worktree', 'move', new, old)
    present = [old for old in nested if Path(old).exists()]
    if present:
        _git(source, 'worktree', 'repair', *present)


def _worktree_moves(configuration, data: Path, listing: str) -> dict[str, str]:
    """Map every registered linked worktree under the worktree root to its core path."""
    worktrees = {}
    for line in listing.splitlines():
        if line.startswith('worktree '):
            path = Path(line.removeprefix('worktree '))
            if path.is_relative_to(configuration.agent_worktrees):
                if path == configuration.project_root:
                    raise ValueError('The Source Repository must remain outside the worktree directory being moved.')
                worktrees[str(path)] = str(data / 'core/worktrees' / path.relative_to(configuration.agent_worktrees))
    return worktrees


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


def _claude_project(home: Path, cwd: str) -> Path:
    """Claude Code keeps a cwd's Sessions in one directory named by its encoded path."""
    return home / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', cwd)


def _claude_continuations(root: Path, worktrees: dict[str, str]) -> list[dict]:
    """Plan each Claude Session whose cwd a moved worktree carries.

    The native home is the one recorded for the Session's launch, else the
    same CLAUDE_CONFIG_DIR / ~/.claude default the Claude Adapter applies.
    Both cwd spellings are compared by real path; the new cwd keeps Git's
    registered spelling. A Claude record that cannot be planned is a listed gap.
    Retired and handed-over trace records are not scanned; they are not resumed.
    """
    default = os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))
    candidates = []
    for path in runner_directory(root).glob('sessions/*/mapping.yml'):
        mapping = yaml.safe_load(path.read_text()) or {}
        launch_path = path.parent / 'launch.yml'
        launch = yaml.safe_load(launch_path.read_text()) if launch_path.is_file() else None
        request = (launch or {}).get('adapter_request') or {}
        candidates.append((str(path), mapping.get('runtime'), [mapping.get('session')],
                           mapping.get('worktree_path') or request.get('worktree_path'), request.get('runtime_home')))
    for path in (root / '.graphtraj/swarm/control/agents').glob('*.json'):
        record = json.loads(path.read_text())
        settings = record.get('settings') or {}
        request = settings.get('adapter_request') or settings
        candidates.append((str(path), record.get('runtime'), record.get('sessions') or [record.get('session')],
                           settings.get('cwd') or request.get('worktree_path'), request.get('runtime_home')))
    moved = {os.path.realpath(old): new for old, new in worktrees.items()}
    planned, seen = [], set()
    for reference, runtime, sessions, cwd, home in candidates:
        if runtime != 'claude':
            continue
        if not isinstance(cwd, str) or not cwd:
            planned.append({'runtime': 'claude', 'session': next((item for item in sessions if item), None),
                            'old': None, 'new': None, 'status': 'unplanned', 'record': reference,
                            'reason': 'The Claude record has no cwd; its native continuation cannot be planned.'})
            continue
        real = os.path.realpath(cwd)
        # A nested worktree also lies in its outer one; their mappings agree.
        for old, new in moved.items():
            if real != old and not real.startswith(old + '/'):
                continue
            target = new + real[len(old):]
            if not any(isinstance(session, str) and session for session in sessions):
                planned.append({'runtime': 'claude', 'session': None, 'old': cwd, 'new': target,
                                'status': 'unplanned', 'record': reference,
                                'reason': 'The Claude record has no native Session identity.'})
            for session in sessions:
                key = (str(home or default), session, cwd)
                if isinstance(session, str) and session and key not in seen:
                    seen.add(key)
                    planned.append({'runtime': 'claude', 'session': session, 'home': key[0],
                                    'old': cwd, 'new': target})
            break
    return planned


def _digests(directory: Path, names: list[str]) -> dict[str, str]:
    """Digest each regular file of these Session entries, keyed relative to the project directory."""
    result = {}
    for name in names:
        entry = directory / name
        for path in ([entry] if entry.is_file() else entry.rglob('*')):
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as stream:
                    result[path.relative_to(directory).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def _copy_continuation(item: dict, continuations: list[dict]) -> None:
    """Add the native Session under its new cwd; never replace or move the original.

    The entry is recorded before any write, so a failed copy or digest is
    removed by the same rollback that removes completed copies.
    """
    home = Path(item['home'])
    source = _claude_project(home, item['old'])
    if not source.is_dir():
        source = _claude_project(home, os.path.realpath(item['old']))
    target = _claude_project(home, item['new'])
    names = [name for name in (item['session'] + '.jsonl', item['session']) if (source / name).exists()]
    if not names:
        continuations.append({**item, 'status': 'missing', 'reason': 'No native transcript under the original cwd.'})
        return
    if any((target / name).exists() for name in names):
        same = _digests(source, names) == _digests(target, names)
        continuations.append({**item, 'status': 'existing' if same else 'conflict', 'reason': (
            'The new cwd already has this identical Session; nothing replaced.' if same else
            'The new cwd has a different record for this Session; it was not replaced or verified.')})
        return
    entry = {**item, 'status': 'copied', 'copies': [str(target / name) for name in names], 'files': {},
             'created': [str(directory) for directory in (target.parent, target) if not directory.exists()]}
    continuations.append(entry)
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name, symlinks=True)
        else:
            shutil.copy2(source / name, target / name)
    entry['files'] = {str(target / path): digest for path, digest in _digests(target, names).items()}


def _changed_copies(continuations: list[dict]) -> list[str]:
    """Name copied native files that changed or appeared since cutover."""
    changed = []
    for item in continuations:
        if item.get('status') != 'copied':
            continue
        target = Path(item['copies'][0]).parent
        current = {str(target / path): digest
                   for path, digest in _digests(target, [Path(copy).name for copy in item['copies']]).items()}
        changed += sorted(path for path in current.keys() | item['files'].keys()
                          if current.get(path) != item['files'].get(path))
    return changed


def _remove_copies(continuations: list[dict]) -> None:
    """Remove only this cutover's copies, then the directories it created once empty."""
    copied = [item for item in continuations if item.get('status') == 'copied']
    for copy in (Path(copy) for item in copied for copy in item['copies']):
        if copy.is_dir() and not copy.is_symlink():
            shutil.rmtree(copy)
        else:
            copy.unlink(missing_ok=True)
    for directory in sorted({Path(path) for item in copied for path in item['created']}, reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _moved_role_grants(roles: Path, moves: dict[str, str]) -> list[dict]:
    """Name authored read grants that still point at moved project data.

    roles.yml is authored configuration: cutover installs it unchanged and its
    owner replaces these grants through role_organization before any Agent
    using that role is started or resumed.
    """
    if not roles.is_file():
        return []
    found = []

    def visit(value: object, location: list[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, [*location, str(key)])
        elif isinstance(value, list) and location[-1:] == ['read_paths']:
            for path in value:
                moved = _references(path, moves, 'path')
                if moved != path:
                    found.append({'field': '.'.join(location), 'old': path, 'new': moved})

    visit(yaml.safe_load(roles.read_text(encoding='utf-8')), [])
    return found


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
    stop = _stopped(root)
    old_paths = [configuration.state, runner, data / 'swarm', data / 'config.yml', data / 'roles.yml', data / 'cli']
    before = _facts(old_paths)
    git_before = _git(configuration.project_root, 'worktree', 'list', '--porcelain')
    worktrees = _worktree_moves(configuration, data, git_before)
    for path in configuration.agent_worktrees.glob('*'):
        if path.is_dir() and not any(Path(old).is_relative_to(path) for old in worktrees):
            raise ValueError(f'An unregistered worktree directory needs native reconciliation before cutover: {path}')
    planned_continuations = _claude_continuations(root, worktrees)
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
        if any(item['agent'] == record['agent'] for item in stop['unconfirmed_swarm_executions']):
            _relocate_owner_exited(staged_swarm, record['agent'], settings)
        else:
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
    continuations = []
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
        # Claude Code resumes a Session by ID across project directories and
        # prefers a copy under the current cwd: the copy keeps post-cutover
        # history under the moved worktree and lets restore detect continuation.
        for item in planned_continuations:
            if 'status' in item:
                continuations.append(item)
            else:
                _copy_continuation(item, continuations)
        recovery['native_continuations'] = continuations
        shutil.copy2(staging / 'cutover-config.yml', data / 'core/config.yml')
        recovery['installed_facts'] = _facts([data / 'core/state', data / 'core/runner', data / 'swarm'])
        write_yaml_durably(backup / 'migration.yml', recovery)
    except BaseException:
        # Recovery uses the same retained manifest; do not discard failed data.
        _remove_copies(continuations)
        _return_worktrees(configuration.project_root, worktrees, _nested(worktrees))
        for old, new in worktrees.items():
            for path, target in link_targets.items():
                if Path(path).is_relative_to(new) and Path(old).is_dir():
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
            'control_missing': stop['control_missing'],
            'unconfirmed_swarm_executions': stop['unconfirmed_swarm_executions'],
            'foreign_entries': foreign_entries(data / 'core/state/tasks'),
            'role_read_paths_to_update': _moved_role_grants(data / 'core/roles.yml', moves),
            'native_continuations': [{key: item[key] for key in ('runtime', 'session', 'old', 'new', 'status')}
                                     for item in continuations],
            'native_continuation_gaps': [{key: item.get(key) for key in ('session', 'old', 'status', 'reason')}
                                         for item in continuations if item['status'] not in {'copied', 'existing'}],
            'native_missing': [item for item in imported['native_results'] if item.get('missing')],
            'native_resource_missing': native_missing,
            'missing_links': imported['missing_links'],
            'legacy_native_registrations': imported['legacy_native_registrations'],
            'legacy_codex_policy': 'Retained declarations remain visible; old calls fail and direct callers to MCP. Native history is unchanged and old business callbacks are not restored.',
            'next': ('Use this same installed version. Every Main host already running before cutover, in any Runtime, '
                     'must exit and enter again so it selects the core layout. Before starting or continuing any member, '
                     'apply role_read_paths_to_update through role_organization. Native host trust and same-ID resume '
                     'require their normal public entry; no host was started. Restore is available before new '
                     'execution/state writes; afterward preserve and reconcile the new history.')}


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
    continuations = record.get('native_continuations', [])
    if _changed_copies(continuations):
        raise ValueError('A native Session continued under its new cwd. Preserve and reconcile the new history before recovery; nothing was restored.')
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
    _remove_copies(continuations)
    return {'restored': str(backup), 'retained_after_cutover': str(backup / 'after-core'),
            'next': 'Keep writers stopped until the matching previous installation and native host entry are selected.'}
