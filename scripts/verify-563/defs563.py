"""Task 563 demo helper: per-Task definition hashes and a before/after comparison.

    python defs563.py hashes <state> <out.json>   every Task's versions in order and its current one
    python defs563.py compare <before.json> <after.json> <state>
                                                  PASS/FAIL per check; also loads the Task Graph

A version list is the initial text first (task.md while it exists), then
definitions/*.md by name. Only files are read; nothing is written but <out.json>.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path


def _sha(path: Path) -> str:
    """Return the sha256 hex digest of one file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(state: Path) -> dict:
    """Return {task directory: {versions, current, modes}} for every Task."""
    import yaml

    result = {}
    for directory in sorted((state / "tasks").iterdir()):
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        record   = yaml.safe_load((directory / "task.yml").read_text(encoding="utf-8"))
        versions = ([directory / "task.md"] if (directory / "task.md").exists() else [])
        versions += sorted((directory / "definitions").glob("*.md"))
        result[directory.name] = {
            "versions": [_sha(path) for path in versions],
            "names":    [path.relative_to(directory).as_posix() for path in versions],
            "current":  _sha(directory / record["current_definition"]),
            "current_definition": record["current_definition"],
            "modes":    sorted({oct(stat.S_IMODE(path.stat().st_mode)) for path in versions}),
        }
    return result


def compare(before: dict, after: dict, state: Path) -> int:
    """Print each check with PASS/FAIL and return the number of failures."""
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += not ok
        print("{0}: {1}{2}".format("PASS" if ok else "FAIL", name, " (" + detail + ")" if detail else ""))

    check("same Task directories", sorted(before) == sorted(after), "{0} before, {1} after".format(len(before), len(after)))
    shared = sorted(set(before) & set(after))
    changed_versions = [key for key in shared if before[key]["versions"] != after[key]["versions"]]
    changed_current  = [key for key in shared if before[key]["current"] != after[key]["current"]]
    check("every Task keeps all version contents in the same order", not changed_versions, ", ".join(changed_versions[:5]))
    check("every Task keeps its current definition content", not changed_current, ", ".join(changed_current[:5]))
    total = sum(len(after[key]["versions"]) for key in shared)
    check("version count unchanged", total == sum(len(before[key]["versions"]) for key in shared), "{0} versions".format(total))
    retired = [key for key in after if any(name == "task.md" for name in after[key]["names"])]
    check("no task.md remains", not retired, ", ".join(retired[:5]))
    unsorted = [key for key in after if after[key]["names"] != sorted(after[key]["names"])]
    check("names sort oldest first", not unsorted)
    writable = [key for key in after if after[key]["modes"] != ["0o444"]]
    check("every version stays read-only (0o444)", not writable, ", ".join(writable[:5]))
    pointing = [key for key in after if not after[key]["current_definition"].startswith("definitions/")]
    check("current_definition names a definitions/ file", not pointing, ", ".join(pointing[:5]))

    from graphtraj.graph.task_graph import read_graph

    graph = read_graph(state, view="full")
    check("Task Graph loads every Task", len(graph["tasks"]) == len(after), "{0} Tasks".format(len(graph["tasks"])))
    print("RESULT: {0}".format("PASS" if failures == 0 else "FAIL ({0} checks failed)".format(failures)))
    return failures


if __name__ == "__main__":
    if sys.argv[1] == "hashes":
        Path(sys.argv[3]).write_text(json.dumps(hashes(Path(sys.argv[2])), indent=1), encoding="utf-8")
        print("hashed {0} Tasks into {1}".format(len(json.loads(Path(sys.argv[3]).read_text())), sys.argv[3]))
    else:
        load = lambda name: json.loads(Path(name).read_text(encoding="utf-8"))
        sys.exit(1 if compare(load(sys.argv[2]), load(sys.argv[3]), Path(sys.argv[4])) else 0)
