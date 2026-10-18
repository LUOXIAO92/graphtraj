"""Project-only migration copies with portable native bytes and original provenance.

A rehearsal retains Runner records as evidence outside the active Runner path.
It never copies Runtime Home, credentials, running channels or Worktree code.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.sessions.storage import SessionStore
from graphtraj.workspace.session_migration import session_sources


MANIFEST = '.graphtraj/migration-snapshot.yml'


def source_map(root: Path, manifest: dict) -> dict[str, Path]:
    """Resolve only local captured files; provenance paths are never fallback reads."""
    result = {}
    for entry in manifest.get('files', []):
        if not entry.get('stored'):
            continue
        relative = Path(entry['stored'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Snapshot source must be a contained relative path.')
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Snapshot source escapes its directory.')
        for original in entry['paths']:
            result[original] = path
    return result


def capture_sources(
    destination: Path,
    sources: list[dict],
    project: Path,
    available: dict[str, Path] | None = None,
) -> dict:
    """Copy associated native bytes and explicit in-project Pi attachments.

    Each capture is bounded by the source's observed byte length. Appended
    bytes are reported as a later tail; truncation fails the copy. Missing
    sources remain gaps rather than triggering discovery of other Sessions.
    """
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    files = []
    seen = set()
    pending = []
    for item in sources:
        if item.get('source'):
            paths = list(dict.fromkeys([item['source'], item.get('resolved_source', item['source'])]))
            pending.append((paths, item.get('runtime') or 'unknown'))
    while pending:
        paths, runtime = pending.pop(0)
        if paths[0] in seen:
            continue
        seen.update(paths)
        original = Path(paths[0])
        actual = (available.get(str(original)) if available is not None else original)
        entry = {'paths': paths}
        if actual is None:
            files.append({**entry, 'missing': 'Source was not captured; original paths are not read.'})
            continue
        temporary = destination / ('copy-' + hashlib.sha256(str(original).encode()).hexdigest())
        try:
            if runtime is None and available is None and not actual.resolve().is_relative_to(project):
                files.append({**entry, 'missing': 'Attachment resolves outside the project; not copied.'})
                continue
            with actual.open('rb') as reader, temporary.open('xb') as writer:
                temporary.chmod(0o600)
                before = os.fstat(reader.fileno())
                remaining = before.st_size
                digest = hashlib.sha256()
                while remaining:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Native source was truncated during capture.')
                    writer.write(block)
                    digest.update(block)
                    remaining -= len(block)
                after = os.fstat(reader.fileno())
                if after.st_size < before.st_size:
                    raise ValueError('Native source was truncated during capture.')
            stored = destination / digest.hexdigest()
            os.replace(temporary, stored)
            entry.update(stored=stored.name, sha256=digest.hexdigest(), bytes=before.st_size,
                         later_bytes=max(0, after.st_size - before.st_size))
            files.append(entry)
            if runtime == 'pi':
                # Only explicit file/image content inside this project is eligible.
                with stored.open('rb') as stream:
                    header = json.loads(stream.readline())
                    cwd = Path(header.get('cwd') or project)
                    for line in stream:
                        if not line.endswith(b'\n'):
                            break
                        record = json.loads(line)
                        message = record.get('message', {})
                        content = message.get('content', []) if isinstance(message, dict) else []
                        for block in content if isinstance(content, list) else []:
                            if not isinstance(block, dict) or block.get('type') not in {'file', 'image'}:
                                continue
                            value = block.get('path')
                            if not isinstance(value, str):
                                continue
                            candidate = Path(os.path.abspath(cwd / value))
                            if (candidate.is_relative_to(project)
                                    and not any(candidate.is_relative_to(project / name)
                                                for name in ('.graphtraj', '.codex'))):
                                pending.append(([str(candidate)], None))
        except OSError as error:
            temporary.unlink(missing_ok=True)
            files.append({**entry, 'missing': type(error).__name__ + ': source bytes unavailable.'})
    return {'files': files}


def copy_records(source: Path, destination: Path) -> list[dict]:
    """Copy retained regular files without following links or live channels.

    SQLite archives use their native consistent backup. Original link spellings
    are returned separately and are installed only after all local files exist.
    """
    links = []
    if not source.is_dir():
        return links
    for directory, children, names in os.walk(source, followlinks=False):
        parent = Path(directory)
        target = destination / parent.relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in list(children) + names:
            path = parent / name
            relative = path.relative_to(source)
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                links.append({'path': relative.as_posix(), 'target': os.readlink(path),
                              'resolved': os.path.abspath(path.parent / os.readlink(path))})
                if name in children:
                    children.remove(name)
            elif stat.S_ISREG(mode):
                if name == 'session.sqlite3':
                    with SessionStore(path, readonly=True) as store:
                        store.export(destination / relative)
                elif not name.endswith(('.sqlite3-wal', '.sqlite3-shm')):
                    shutil.copy2(path, destination / relative)
            # FIFOs, sockets, devices and live process channels are not evidence files.
    return links


def install_links(
    root: Path,
    links: list[dict],
    roots: dict[str, Path],
    captured: dict[str, Path],
) -> list[dict]:
    """Install only links into copied data; retain unavailable original targets as gaps."""
    gaps = []
    for entry in links:
        path = root / entry['path']
        original = Path(entry['resolved'])
        target = captured.get(str(original))
        if target is None:
            for old, new in roots.items():
                if original.is_relative_to(old):
                    target = new / original.relative_to(old)
                    break
        if target is None:
            gaps.append({**entry, 'missing': 'External link target was not an associated captured source.'})
            target = root / 'unavailable' / hashlib.sha256(str(original).encode()).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path):
            path.unlink()
        path.symlink_to(os.path.relpath(target, path.parent))
    return gaps


def task_signatures(state: Path) -> dict[str, str]:
    """Identify graph facts before/after copying without following report links."""
    paths = list((state / 'tickets').glob('*/ticket.yml'))
    paths += list((state / 'tickets').glob('*/ticket.md'))
    paths += list((state / 'tickets').glob('*/definitions/*.md'))
    paths += list((state / 'worldline').glob('*.jsonl'))
    paths += list((state / 'tasks').glob('*/task.yml'))
    paths += list((state / 'tasks').glob('*/task.md'))
    paths += list((state / 'tasks').glob('*/definitions/*.md'))
    paths += list((state / 'tasks').glob('*/teams/*/team.yml'))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if not path.is_symlink()}


def _control_signatures(project: Path) -> dict[str, str]:
    """Observe durable identity/config changes, excluding active heartbeats/channels."""
    data = project / '.graphtraj'
    paths = [data / 'config.yml', data / 'roles.yml', data / 'swarm/config.yml']
    paths += list((data / 'runner').glob('sessions/*/mapping.yml'))
    paths += list((data / 'runner').glob('sessions/*/session.yml'))
    paths += list((data / 'runner').glob('main-sessions/*/session.yml'))
    paths += list((data / 'swarm/control').rglob('*.json'))
    # Native Main rebinding atomically rewrites even an unchanged binding.
    # Inode/mtime changes do not mean its retained facts changed.
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file() and not path.is_symlink()}


def _changed_records(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Name changed records without disclosing their bodies or credentials."""
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def _clone_snapshot(project: Path, destination: Path) -> dict:
    """Create a writable rehearsal from a retained copy without original reads."""
    destination.mkdir(mode=0o700, parents=True)
    try:
        links = copy_records(project / '.graphtraj', destination / '.graphtraj')
        gaps = install_links(destination / '.graphtraj', links, {str(project): destination}, {})
        manifest = yaml.safe_load((destination / MANIFEST).read_text(encoding='utf-8'))
        # Validate every captured-source reference against the new local root.
        source_map(destination, manifest)
        return {'snapshot': str(destination), 'source_snapshot': str(project),
                'project': manifest['project'], 'missing_links': gaps,
                'notice': 'Isolated copy of retained snapshot; no original paths read or Runtime activated.'}
    except BaseException:
        shutil.rmtree(destination)
        raise


def snapshot_project(cwd: Path, destination: Path) -> dict:
    """Create a new isolated migration Harness without writing to the original project."""
    configuration = load_project_configuration(cwd)
    project = configuration.harness_root
    destination = destination.resolve()
    if destination.exists() or destination.is_symlink() or destination.is_relative_to(project):
        raise ValueError('Snapshot destination must be new and outside the source Harness.')
    if (project / MANIFEST).exists():
        return _clone_snapshot(project, destination)
    sources = session_sources(configuration.state, project / '.graphtraj/runner', project)
    task_facts = task_signatures(configuration.state)
    control_facts = _control_signatures(project)
    destination.mkdir(mode=0o700, parents=True)
    data = destination / '.graphtraj'
    data.mkdir()
    try:
        captured = capture_sources(data / 'migration-sources', sources, project)
        for item in captured['files']:
            if item.get('stored'):
                item['stored'] = '.graphtraj/migration-sources/' + item['stored']
        manifest = {'version': 1, 'project': str(project), 'sources': sources, **captured,
                    'state_source': str(configuration.state),
                    'runner_source': str(project / '.graphtraj/runner'), 'task_state_unchanged': True}
        state = data / 'state'
        runner = data / 'migration-runner'
        state_links = copy_records(configuration.state, state)
        runner_links = copy_records(project / '.graphtraj/runner', runner)
        changed = _changed_records(task_facts, task_signatures(configuration.state))
        if changed:
            raise ValueError('Task facts changed during snapshot: ' + ', '.join(changed[:20]))
        roots = {str(configuration.state): state, str(project / '.graphtraj/runner'): runner}
        local = source_map(destination, manifest)
        worktree_links = []
        for link in sorted(configuration.agent_worktrees.glob('*/.state')):
            if link.is_symlink():
                worktree_links.append({'path': link.parent.name + '/.state', 'target': os.readlink(link),
                                       'resolved': os.path.abspath(link.parent / os.readlink(link))})
        manifest['worktree_links'] = worktree_links
        install_links(data / 'worktrees', worktree_links, roots, local)
        manifest['links'] = {'state': state_links, 'runner': runner_links}
        manifest['missing_links'] = (install_links(state, state_links, roots, local)
                                     + install_links(runner, runner_links, roots, local))
        # Preserve tool-owned persistent data; never copy live communication
        # channels into a runnable location. Runtime homes are not enumerated.
        swarm = project / '.graphtraj/swarm'
        swarm_links = []
        for name in ('control', 'native', 'sessions'):
            if (swarm / name).is_dir():
                copied_links = copy_records(swarm / name, data / 'swarm' / name)
                swarm_links.extend({'path': name + '/' + link['path'], **{
                    key: value for key, value in link.items() if key != 'path'}} for link in copied_links)
        if (swarm / 'config.yml').is_file():
            (data / 'swarm').mkdir(exist_ok=True)
            shutil.copy2(swarm / 'config.yml', data / 'swarm/config.yml')
        roots[str(swarm)] = data / 'swarm'
        manifest['missing_links'] += install_links(data / 'swarm', swarm_links, roots, local)
        manifest['swarm_captured'] = swarm.is_dir()
        inputs = data / 'migration-input'
        inputs.mkdir()
        for name in ('config.yml', 'roles.yml'):
            original = project / '.graphtraj' / name
            if original.is_file():
                shutil.copy2(original, inputs / name)
        git = subprocess.run(['git', '-C', str(configuration.project_root), 'worktree', 'list', '--porcelain'],
                             capture_output=True, text=True, check=False)
        manifest['git_worktrees'] = (git.stdout if git.returncode == 0 else None)
        if git.returncode:
            manifest['git_missing'] = 'Source Repository Git worktree metadata is unavailable.'
        manifest['configuration_captured'] = [path.name for path in inputs.iterdir()]
        changed = (_changed_records(task_facts, task_signatures(configuration.state))
                   + _changed_records(control_facts, _control_signatures(project)))
        if changed:
            raise ValueError('Task or durable Agent/configuration facts changed during snapshot: '
                             + ', '.join(changed[:20]) + f' ({len(changed)} changed records).')
        manifest['control_state_unchanged'] = True
        # No active Runner, roles, connections, credentials or source checkout is
        # installed. This copy supports offline migration and Task graph queries.
        config = {'version': 1, 'paths': {'project_root': '.', 'docs': 'docs',
                  'state': '.graphtraj/state', 'agent_worktrees': '.graphtraj/worktrees'},
                  'agent_runner': {'dispatch_depth': configuration.dispatch_depth,
                                   'max_concurrency': configuration.max_concurrency}}
        (data / 'config.yml').write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
        (destination / MANIFEST).write_text(yaml.safe_dump(manifest, sort_keys=False), encoding='utf-8')
        return {'snapshot': str(destination), 'project': str(project), 'sources': sources,
                'files': captured['files'], 'missing_links': manifest['missing_links'],
                'notice': 'Offline copy only; original identity/provenance is retained. No live Runner is installed.'}
    except BaseException:
        shutil.rmtree(destination)
        raise


def restore_sources(backup: Path, state: Path, runner: Path, *, allow_original: bool) -> None:
    """Restore absent native source bytes locally, never writing to Runtime Home.

    Original provenance remains in the backup manifest and Session headers.
    Only operational source locations and Trace links are updated when their
    original bytes no longer exist. Restored business reads use local files,
    not the backup directory or a second-format fallback.
    """
    path = backup / 'native-sources.yml'
    if not path.is_file():
        return
    manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
    captured = source_map(backup, manifest)
    replacements = {}
    for original, source in captured.items():
        if allow_original and Path(original).is_file():
            continue
        target = state / 'restored-sources' / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
        replacements[original] = target
    if not replacements:
        return
    for root in (state, runner):
        for path in root.rglob('*'):
            if path.is_symlink():
                original = os.path.abspath(path.parent / os.readlink(path))
                if original in replacements:
                    path.unlink()
                    path.symlink_to(os.path.relpath(replacements[original], path.parent))
            elif path.name in {'mapping.yml', 'session.yml', 'native-session.yml'} and path.is_file():
                record = yaml.safe_load(path.read_text(encoding='utf-8'))
                if not isinstance(record, dict):
                    continue
                changed = False
                for container in (record, record.get('activity', {}),
                                  record.get('retirement', {}).get('mapping', {})):
                    for field in ('trace_file', 'rollout_path'):
                        if container.get(field) in replacements:
                            container[field] = str(replacements[container[field]])
                            changed = True
                if changed:
                    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding='utf-8')
