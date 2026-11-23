"""593 C5: before/after snapshots of the USER's directories that requirement 5 must leave unchanged. Read only.

usage: homesnap593.py snap <out.json> <label>=<directory>...
       homesnap593.py compare <before.json> <after.json>

Labels decide how a tree is read:
  codex  - every file by name and sha256, leaving out logs_*.sqlite* and models_cache.json (the USER's running Codex
           writes them; they are not evidence of an install).
  conda  - what an install into conda would change: every conda-meta/*.json (name and sha256) of the base and of each
           env, and the *.dist-info / *.egg-info names in every site-packages (names only).
  other  - every file by name, size and modification time (ns); symbolic links by their target.
A missing directory is recorded as absent. compare prints added, removed and changed names per label and one line
'REPORT 593 <label> unchanged: yes|NO'; exit 0 only when every label is unchanged.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

CODEX_SKIP = ('models_cache.json',)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def entries(label: str, root: Path) -> dict[str, str] | None:
    if not root.exists():
        return None
    found: dict[str, str] = {}
    if label == 'conda':
        for meta in [root / 'conda-meta', *sorted((root / 'envs').glob('*/conda-meta'))]:
            for item in sorted(meta.glob('*.json')):
                found[str(item.relative_to(root))] = sha(item)
        for site in sorted(root.glob('lib/python*/site-packages')) + sorted(root.glob('envs/*/lib/python*/site-packages')):
            for item in sorted(site.glob('*.*-info')):
                found[str(item.relative_to(root))] = 'present'
        return found
    for directory, names, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            if label == 'codex' and (name in CODEX_SKIP or (name.startswith('logs_') and '.sqlite' in name)):
                continue
            try:
                if path.is_symlink():
                    found[relative] = 'link ' + os.readlink(path)
                elif label == 'codex':
                    found[relative] = sha(path)
                else:
                    stat = path.stat()
                    found[relative] = f'{stat.st_size} {stat.st_mtime_ns}'
            except OSError as error:
                found[relative] = f'unreadable {type(error).__name__}'
    return found


def snap(out: str, pairs: list[str]) -> int:
    document = {}
    for pair in pairs:
        label, _, directory = pair.partition('=')
        kind = 'codex' if label == 'codex' else 'conda' if label == 'conda' else 'other'
        document[label] = {'directory': directory, 'kind': kind, 'entries': entries(kind, Path(directory))}
        found = document[label]['entries']
        print(f"snap {label} {directory}: {'absent' if found is None else f'{len(found)} entries'}"
              f"{' (codex: logs_*.sqlite* and models_cache.json left out)' if kind == 'codex' else ''}")
    Path(out).write_text(json.dumps(document, indent=1, sort_keys=True))
    return 0


def compare(before: str, after: str) -> int:
    a, b = json.loads(Path(before).read_text()), json.loads(Path(after).read_text())
    bad = 0
    for label in sorted(a.keys() | b.keys()):
        old, new = (a.get(label) or {}).get('entries'), (b.get(label) or {}).get('entries')
        if old is None or new is None:
            same = old is None and new is None
            print(f"{label}: {'absent before and after' if same else f'absent {'before' if old is None else 'after'} only'}")
        else:
            added = sorted(new.keys() - old.keys())
            removed = sorted(old.keys() - new.keys())
            changed = sorted(k for k in old.keys() & new.keys() if old[k] != new[k])
            same = not (added or removed or changed)
            print(f'{label}: added {len(added)} {added[:5]} | removed {len(removed)} {removed[:5]} | changed {len(changed)} {changed[:5]}')
        print(f"REPORT 593 {label} unchanged: {'yes' if same else 'NO'}")
        bad += not same
    return 1 if bad else 0


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'snap':
        sys.exit(snap(sys.argv[2], sys.argv[3:]))
    if len(sys.argv) == 4 and sys.argv[1] == 'compare':
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    print(__doc__)
    sys.exit(2)
