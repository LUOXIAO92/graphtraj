"""Snapshot and compare production Main records and sessions around a test run (482). Read-only on production.

    snap.py take <harness> <out.json>
    snap.py compare <before.json> <after.json> <marker>...

A changed or new entry is "test-caused" when its path or content names a marker
(pytest temporary paths, the 482 test directory, fixture session ids); every
other change is reported as ordinary production activity.
"""

import hashlib
import json
import os
import sys
from pathlib import Path


def _files(root: Path) -> dict:
    found = {}
    if root.is_dir():
        for directory, _, names in os.walk(root):
            for name in names:
                path = Path(directory) / name
                try:
                    status = path.lstat()
                except OSError:
                    continue
                found[str(path)] = [status.st_size, status.st_mtime_ns]
    return found


def take(harness: Path, out: Path) -> None:
    continuity = harness / ".graphtraj/core/runner/main-sessions/continuity.jsonl"
    data = continuity.read_bytes() if continuity.is_file() else b""
    out.write_text(json.dumps({
        "continuity": {"path": str(continuity), "lines": data.decode("utf-8", "replace").splitlines(),
                       "sha256": hashlib.sha256(data).hexdigest()},
        "main-sessions": _files(harness / ".graphtraj/core/runner/main-sessions"),
        "swarm-sessions": _files(harness / ".graphtraj/swarm/sessions"),
    }))
    print("snapshot {0}: continuity.jsonl lines={1} sha256={2}; main-sessions files={3}; swarm/sessions files={4}".format(
        out.name, len(data.splitlines()), hashlib.sha256(data).hexdigest(), len(json.loads(out.read_text())["main-sessions"]),
        len(json.loads(out.read_text())["swarm-sessions"])))


def _names_marker(text: str, markers: list) -> bool:
    return any(marker in text for marker in markers)


def _content(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except OSError:
        return ""


def compare(before_path: Path, after_path: Path, markers: list) -> int:
    before, after = json.loads(before_path.read_text()), json.loads(after_path.read_text())
    caused = 0
    old, new = before["continuity"], after["continuity"]
    print("continuity.jsonl before: lines={0} sha256={1}".format(len(old["lines"]), old["sha256"]))
    print("continuity.jsonl after:  lines={0} sha256={1}".format(len(new["lines"]), new["sha256"]))
    if old["sha256"] == new["sha256"]:
        print("continuity.jsonl: UNCHANGED")
    else:
        prefix = new["lines"][:len(old["lines"])] == old["lines"]
        added = new["lines"][len(old["lines"]):] if prefix else new["lines"]
        print("continuity.jsonl: CHANGED ({0})".format("appended" if prefix else "rewritten; all lines follow"))
        for line in added:
            test = _names_marker(line, markers)
            caused += test
            print("  [{0}] {1}".format("TEST-CAUSED" if test else "production", line[:400]))
    for key in ("main-sessions", "swarm-sessions"):
        old_files, new_files = before[key], after[key]
        changes = [("new", p) for p in sorted(set(new_files) - set(old_files))]
        changes += [("changed", p) for p in sorted(set(new_files) & set(old_files)) if new_files[p] != old_files[p]]
        changes += [("removed", p) for p in sorted(set(old_files) - set(new_files))]
        # Content is checked only for new files: a live Session's existing transcript may quote these paths.
        test_changes = [(kind, p) for kind, p in changes if _names_marker(p, markers)
                        or (kind == "new" and _names_marker(_content(p), markers))]
        caused += len(test_changes)
        print("{0}: {1} ({2} entries; {3} test-caused, {4} ordinary production activity)".format(
            key, "UNCHANGED" if not changes else "CHANGED", len(changes), len(test_changes), len(changes) - len(test_changes)))
        for kind, path in changes:
            print("  [{0}] {1} {2}".format("TEST-CAUSED" if (kind, path) in test_changes else "production", kind, path))
    print("== production verdict: {0}".format("CHANGED BY TESTS ({0} entries)".format(caused) if caused
                                             else "UNCHANGED BY TESTS"))
    return 1 if caused else 0


if __name__ == "__main__":
    if sys.argv[1] == "take":
        take(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        sys.exit(compare(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4:]))
