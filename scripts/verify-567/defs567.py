"""Task 567 P-step helper; works only on a copy below <copy root>.

    python defs567.py retire <copy root> <state>   put each renamed initial definition back at task.md
    python defs567.py tree <state> <out.json>      sha256 of every file, target of every link

``retire`` undoes, in the copy only, the renames recorded by every
``task-definitions-renamed`` event, so the copy again has the layout the
migration acts on (production was already migrated). ``tree`` is the
nothing-changed record; it reads files only and writes <out.json>.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def retire(root: Path, state: Path) -> None:
    """Rename definitions/<event>.md back to task.md inside the copy at ``root``."""
    import yaml

    from graphtraj.graph.delivery_worldline import read_worldline

    if root.resolve() not in state.resolve().parents:
        raise SystemExit("STOP: {0} is not inside the copy {1}".format(state, root))
    mapping: dict[str, str] = {}
    for event in read_worldline(state):
        if event["event"] == "task-definitions-renamed":
            mapping.update(event["renamed_definitions"])
    restored = current = 0
    for old, new in sorted(mapping.items()):
        source, target = root / new, root / old
        if not source.is_file() or os.path.lexists(target):
            continue
        os.rename(source, target)
        restored += 1
        record_path = target.parent / "task.yml"
        record = yaml.safe_load(record_path.read_text(encoding="utf-8"))
        if record.get("current_definition") == source.relative_to(target.parent).as_posix():
            record["current_definition"] = "task.md"
            record_path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
            current += 1
    print("copy: {0} initial definitions put back at task.md ({1} current_definition reset); "
          "{2} rename mappings read".format(restored, current, len(mapping)))


def tree(state: Path) -> dict[str, str]:
    """Return {relative path: sha256 or link target} for everything under ``state``."""
    result = {}
    for path in sorted(state.rglob("*")):
        key = path.relative_to(state).as_posix()
        if path.is_symlink():
            result[key] = "link:" + os.readlink(path)
        elif path.is_file():
            result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == "__main__":
    command, first, second = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if command == "retire":
        retire(first, second)
    elif command == "tree":
        entries = tree(first)
        second.write_text(json.dumps(entries, indent=0, sort_keys=True), encoding="utf-8")
        print("{0}: {1} files and links recorded".format(second.name, len(entries)))
    else:
        raise SystemExit("usage: defs567.py retire <copy root> <state> | tree <state> <out.json>")
