"""Task 637 (W5) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck637.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE (graftling dev 75cb93b2) with
                                       only its push branches line changed, and its push branches are exactly BRANCHES
  as632 BASE_WF OUT                    write to OUT the base workflow with its push branches line set back to 632's,
                                       so 632's wfcheck judges every other property of it unchanged; fails unless
                                       that line is there exactly once
  w5edit OLD NEW                       the expected list NEW is OLD (GraphTraj dev 035c3fa3) with exactly its W5 (637)
                                       lines of DELETED removed; no W5 (637) line left; every other line
                                       byte-identical and in order
  newtests DIR LIST                    every node id in LIST passed in the merged per-file JUnit files of the artifact
                                       DIR (not failed, errored, skipped or absent); last line NEWTESTS PASS|FAIL
Writes nothing, except as632's OUT.
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify-632"))
from wincheck import load, nodeid  # noqa: E402

# graftling dev 75cb93b2's push branches, in the workflow's order; the candidate appends only its own branch.
BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
                 "agent/638-graftling-windows-paths-encoding", "dev", "agent/636-graftling-windows-named-pipe"]
BRANCHES = BASE_BRANCHES + ["agent/637-graftling-windows-process-listing"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
W5 = "W5 (637)"
# The W5 (637) lines of scripts/verify-632/windows-expected.txt at GraphTraj dev 035c3fa3, all deleted: the test
# runs on Windows through the service's job and must pass (it is in new-tests.txt).
DELETED = [
    "tests/test_codex_child_interpreter_shutdown_473.py::test_child_ends_completed_after_the_owner_main_thread_returns",
]


def wfdiff(base_file: str, head_file: str) -> None:
    """The head workflow is the base one with only the push branches line changed, to exactly BRANCHES."""
    import yaml

    base = open(base_file, encoding="utf-8").read()
    head = open(head_file, encoding="utf-8").read()
    bad = 0
    on = yaml.safe_load(head)
    on = on.get("on", on.get(True)) or {}
    branches = ((on.get("push") or {}).get("branches") or []) if isinstance(on, dict) else []
    if branches == BRANCHES:
        print(f"PASS: push branches are exactly {BRANCHES}")
    else:
        print(f"FAIL: push branches are {branches}, not {BRANCHES}")
        bad += 1
    wanted = base.replace(BASE_LINE + "\n", HEAD_LINE + "\n")
    if base.count(BASE_LINE + "\n") == 1 and wanted == head:
        print("PASS: the workflow is the base one with only its push branches line changed")
    else:
        old, new = wanted.splitlines(), head.splitlines()
        changed = [f"{n + 1}: {a!r} -> {b!r}" for n, (a, b) in enumerate(zip(old, new)) if a != b]
        print(f"FAIL: the workflow differs from the base beyond the push branches line "
              f"({len(old)} -> {len(new)} lines; first differences: {changed[:3]})")
        bad += 1
    sys.exit(1 if bad else 0)


def as632(base_file: str, out_file: str) -> None:
    """Write the base workflow with its push branches line set back to 632's."""
    base = open(base_file, encoding="utf-8").read()
    if base.count(BASE_LINE + "\n") != 1:
        print(f"FAIL: the base workflow does not have exactly one line {BASE_LINE.strip()!r}")
        sys.exit(1)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write(base.replace(BASE_LINE + "\n", LINE_632 + "\n"))
    print(f"PASS: the base workflow's push branches line is {BASE_BRANCHES}; judged below with it set back to 632's")


def _owner(line: str) -> str | None:
    fields = line.split("\t")
    return fields[3] if line.startswith("fail\t") and len(fields) >= 4 else None


def w5edit(old_file: str, new_file: str) -> None:
    """NEW is OLD without exactly the W5 (637) lines of DELETED; nothing else changed."""
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")
    bad = []
    old_w5 = [line.split("\t")[1] for line in old if _owner(line) == W5]
    if sorted(old_w5) != sorted(DELETED):
        bad.append(f"the base's W5 (637) lines are {old_w5}, not exactly {DELETED}")
    expected = [line for line in old if not (_owner(line) == W5 and line.split("\t")[1] in DELETED)]
    if new != expected:
        changed = [f"{n + 1}: {a[:100]!r} -> {b[:100]!r}" for n, (a, b) in enumerate(zip(expected, new)) if a != b]
        bad.append(f"{len(new)} lines, expected {len(expected)}; first differences: {changed[:3]}")
    if any(_owner(line) == W5 for line in new):
        bad.append("a W5 (637) line remains")
    leader = [line.split("\t")[1] for line in new if "\tLeader-placed (inference)" in line]
    print(f"expected list: {len(old_w5)} W5 (637) entries at the base, {len(DELETED)} to delete; "
          f"{len(leader)} 'Leader-placed (inference)' entries kept as they were: {leader}")
    for problem in bad:
        print("FAIL: " + problem)
    if not bad:
        print("PASS: the W5 (637) line is deleted; no W5 (637) line remains; every other line is byte-identical "
              "and in order")
    sys.exit(1 if bad else 0)


def newtests(directory: str, list_file: str) -> None:
    """Every node id of LIST passed in the artifact DIR's per-file JUnit files."""
    wanted = [line.strip() for line in open(list_file, encoding="utf-8") if line.strip() and not line.startswith("#")]
    outcome = {}
    files = os.path.join(directory, "files.json")
    for record in (load(files).get("files", []) if os.path.exists(files) else []):
        if not record.get("junit"):
            continue
        # The Windows runner writes junit\test_x.xml (run 45608819873).
        path = os.path.join(directory, record["junit"].replace("\\", "/"))
        if not os.path.exists(path):
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            tags = {child.tag for child in case}
            outcome[nodeid(case)] = ("failed" if tags & {"failure", "error"} else
                                     "skipped" if "skipped" in tags else "passed")
    passed = 0
    print(f"--- the W5 tests (637) in this run: {len(wanted)} expected to pass")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    verdict = "PASS" if passed == len(wanted) else "FAIL"
    print(f"NEWTESTS {verdict} {passed} of {len(wanted)} W5 tests passed")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "w5edit": w5edit, "as632": as632, "newtests": newtests}[command](*rest)
