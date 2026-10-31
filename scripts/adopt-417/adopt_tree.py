"""Standard-library helpers of steps.zsh: tree manifests, archive rollback, read-only reports.

Runs under the Conda Python with -I, so it works while the venv is broken.

  manifest <dir> <out>                 sha256 of every file, target of every link, no __pycache__
  compare <manifest> <dir>             SAME n / DIFF lines; exit 1 on any difference
  archives <sessions> <out>            one line per archive: version sha256 relative-path
  versions <sessions>                  archive count by version, total size, unreadable ones
  rollback <sessions> <snapshot> <manifest> <keep>
                                       make every archive readable by the old reader again
  held <swarm root>                    Agents with a notice 0.2.4 holds and the old code will not deliver
  mcp <.mcp.json>                      agents entry (secret-like values hidden), other entries by name
  inbox <inbox file>                   queued notices without bodies; duplicate ids
  stream <stream-json> <tool>...       answers to these MCP tools in one claude -p stream
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SECRET = re.compile(r'key|token|secret|password|authorization', re.I)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def tree(directory: Path) -> dict[str, str]:
    """Return relative path -> content identity; directories themselves count too."""
    found = {}
    for root, directories, files in os.walk(directory):
        directories[:] = [item for item in directories if item != '__pycache__']
        for item in directories + files:
            path = Path(root) / item
            relative = str(path.relative_to(directory))
            if path.is_symlink():
                found[relative] = 'link:' + os.readlink(path)
            elif path.is_dir():
                found[relative] = 'dir'
            elif path.is_file():
                found[relative] = 'file:' + digest(path)
    return found


def manifest(directory: str, output: str) -> int:
    found = tree(Path(directory))
    Path(output).write_text(json.dumps(found, indent=0, sort_keys=True))
    print(f'manifest {output}: {len(found)} entries')
    return 0


def compare(saved: str, directory: str) -> int:
    before, now = json.loads(Path(saved).read_text()), tree(Path(directory))
    lines = [f'REMOVED {key}' for key in sorted(before.keys() - now.keys())]
    lines += [f'ADDED {key}' for key in sorted(now.keys() - before.keys())]
    lines += [f'CHANGED {key}' for key in sorted(before.keys() & now.keys()) if before[key] != now[key]]
    print('\n'.join(lines[:40]))
    if len(lines) > 40:
        print(f'... and {len(lines) - 40} more')
    print(f'{"SAME" if not lines else "DIFF"} entries={len(before)} differences={len(lines)} ({directory})')
    return 1 if lines else 0


def version_of(path: Path) -> object:
    """Return the archive's header.version, or a label when it cannot be read."""
    try:
        with path.open(encoding='utf-8') as stream:
            return json.loads(next(stream))['header']['version']
    except Exception as error:
        return f'unreadable:{type(error).__name__}'


def archive_files(sessions: Path) -> list[Path]:
    # The same files the old native_header lookup globs.
    return sorted(sessions.glob('*/session.jsonl'))


def archives(sessions: str, output: str) -> int:
    root = Path(sessions)
    with open(output, 'w') as stream:
        for path in archive_files(root):
            stream.write(f'{version_of(path)} {digest(path)} {path.relative_to(root)}\n')
    return versions(sessions)


def versions(sessions: str) -> int:
    paths = archive_files(Path(sessions))
    counts = collections.Counter(str(version_of(path)) for path in paths)
    size = sum(path.stat().st_size for path in paths)
    print(f'archives={len(paths)} by-version={dict(sorted(counts.items()))} total-bytes={size}')
    for path in paths:
        if str(version_of(path)).startswith('unreadable'):
            print(f'UNREADABLE {path}')
    return 0


def rollback(sessions: str, snapshot: str, saved: str, keep: str) -> int:
    root, copies, kept = Path(sessions), Path(snapshot), Path(keep)
    before = {}
    for line in Path(saved).read_text().splitlines():
        version, sha, relative = line.split(' ', 2)
        before[relative] = (version, sha)
    restored, moved, problems = [], [], []
    for path in archive_files(root):
        if version_of(path) == 4:
            continue
        relative = str(path.relative_to(root))
        target = kept / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Clone first, so the events recorded after the install stay in the kept copy.
        subprocess.run(['/bin/cp', '-cp', str(path), str(target)], check=True)
        original = before.get(relative)
        if original is None:
            path.unlink()
            moved.append(relative)
        elif original[0] != '4':
            problems.append(f'{relative}: was already version {original[0]} before the install')
        else:
            temporary = path.with_name('.session.jsonl.restore')
            subprocess.run(['/bin/cp', '-cp', str(copies / relative), str(temporary)], check=True)
            if digest(temporary) != original[1]:
                temporary.unlink()
                problems.append(f'{relative}: snapshot bytes differ from the manifest; left as is')
                continue
            os.replace(temporary, path)
            restored.append(relative)
    for relative in restored:
        print(f'RESTORED {relative}')
    for relative in moved:
        print(f'MOVED-OUT {relative}')
    for line in problems:
        print(f'PROBLEM {line}')
    print(f'restored-to-pre-install={len(restored)} moved-out-of-glob={len(moved)} problems={len(problems)}')
    print(f'kept copies: {kept}')
    versions(sessions)
    left = [path for path in archive_files(root) if version_of(path) != 4]
    print(f'not-version-4 left for the old reader: {len(left)}')
    return 1 if problems or left else 0


def holds(value: object) -> bool:
    if isinstance(value, dict):
        return any((key == 'notification' and item == 'held')
                   or (key == 'request_notices' and isinstance(item, dict) and 'held' in item.values())
                   or holds(item) for key, item in value.items())
    return isinstance(value, list) and any(holds(item) for item in value)


def held(root: str) -> int:
    names = []
    for path in sorted((Path(root) / 'control' / 'agents').glob('*.json')):
        try:
            if holds(json.loads(path.read_text(encoding='utf-8'))):
                names.append(path.stem)
        except (OSError, ValueError) as error:
            print(f'UNREADABLE {path.name}: {type(error).__name__}')
    print(f'agents with a held notice: {len(names)} {names}')
    return 0


def mcp(path: str) -> int:
    servers = json.loads(Path(path).read_text(encoding='utf-8'))['mcpServers']
    entry = json.loads(json.dumps(servers.get('agents')))
    if isinstance(entry, dict):
        for key in entry.get('env') or {}:
            if SECRET.search(key):
                entry['env'][key] = '<hidden>'
    print('agents:', json.dumps(entry, ensure_ascii=False))
    print('other entries:', sorted(set(servers) - {'agents'}))
    return 0


def inbox(path: str) -> int:
    file = Path(path)
    if not file.exists():
        print(f'no inbox file {file}')
        return 0
    records = [json.loads(line) for line in file.read_text(encoding='utf-8').splitlines() if line.strip()]
    cursor = file.with_suffix('.cursor')
    print(f'records={len(records)} cursor={cursor.read_text() if cursor.exists() else None}')
    for record in records[-12:]:
        event = record.get('event') or {}
        print(record.get('id'), event.get('alias'), event.get('event'), event.get('execution'))
    counts = collections.Counter(record.get('id') for record in records)
    duplicates = {key: count for key, count in counts.items() if count > 1}
    print(f'duplicate ids: {len(duplicates)} {duplicates}')
    return 1 if duplicates else 0


def stream(path: str, *tools: str) -> int:
    calls, answers = {}, collections.defaultdict(list)
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            document = json.loads(line)
        except ValueError:
            continue
        message = document.get('message') if isinstance(document, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use':
                calls[item.get('id')] = item.get('name')
            elif item.get('type') == 'tool_result' and item.get('tool_use_id') in calls:
                body = item.get('content')
                text = ' '.join(part.get('text', '') for part in body if isinstance(part, dict)) \
                    if isinstance(body, list) else str(body)
                answers[calls[item['tool_use_id']]].append((bool(item.get('is_error')), text))
    failed = 0
    for tool in tools:
        good = [text for error, text in answers[tool] if not error and text]
        print(f'{"PASS" if good else "FAIL"} {tool}: answers={len(answers[tool])} ok={len(good)}')
        for error, text in answers[tool]:
            print(f'   error={error} {text[:300]}')
        failed += not good
    return 1 if failed else 0


OPERATIONS = {'manifest': manifest, 'compare': compare, 'archives': archives, 'versions': versions,
              'rollback': rollback, 'held': held, 'mcp': mcp, 'inbox': inbox, 'stream': stream}
sys.exit(OPERATIONS[sys.argv[1]](*sys.argv[2:]))
