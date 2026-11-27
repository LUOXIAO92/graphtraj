"""Task 647 (W8 + W9) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck647.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE (graftling dev eb5ad8e) with
                                       only its push branches line changed, and its push branches are exactly BRANCHES
  as632 BASE_WF OUT                    write to OUT the base workflow with its push branches line set back to 632's,
                                       so 632's wfcheck judges every other property of it unchanged; fails unless
                                       that line is there exactly once
  listcheck OLD NEW                    the expected list NEW is OLD (GraphTraj afaf516d's) without this Task's line (the
                                       W8 entry, OWN below), and otherwise only without whole lines: a line another
                                       Task removed (648, 649) is named as a NOTE and accepted; an added or changed
                                       line, or OWN still present, fails
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

# graftling dev eb5ad8e's push branches, in the workflow's order; the candidate appends only its own branch.
BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
                 "agent/638-graftling-windows-paths-encoding", "dev", "agent/636-graftling-windows-named-pipe",
                 "agent/637-graftling-windows-process-listing", "agent/639-graftling-windows-codex"]
BRANCHES = BASE_BRANCHES + ["agent/647-graftling-windows-claude"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
# This Task's one line of the expected list: the W8 failure, by its node id.
OWN = "fail\ttests/test_unified_data_root_577.py::test_claude_launcher_logs_into_the_variable\t"


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


def listcheck(old_file: str, new_file: str) -> None:
    """NEW is OLD without OWN, and otherwise only without whole lines (other Tasks' removals, named)."""
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")
    own = [line for line in old if line.startswith(OWN)]
    if len(own) != 1:
        print(f"FAIL: the base list does not hold this Task's line exactly once ({len(own)} found)")
        sys.exit(1)
    # Walk OLD in order: every NEW line must be the next OLD line still unmatched; what OLD has beyond is removed.
    removed, position = [], 0
    for line in new:
        while position < len(old) and old[position] != line:
            removed.append(old[position])
            position += 1
        if position == len(old):
            print(f"FAIL: the expected list adds or changes a line: {line[:160]!r}")
            sys.exit(1)
        position += 1
    removed += old[position:]
    others = [line for line in removed if line != own[0]]
    if own[0] not in removed:
        print("FAIL: the expected list still holds this Task's W8 line (test_claude_launcher_logs_into_the_variable)")
        sys.exit(1)
    for line in others:
        print(f"NOTE: also removed, by another Task (not 647's to judge): {line[:160]!r}")
    print(f"PASS: the expected list is GraphTraj afaf516d's without the W8 line"
          + (f" and {len(others)} other removed line(s) named above" if others else ", nothing else changed"))
    sys.exit(0)


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
    print(f"--- the W8/W9 tests (647) in this run: {len(wanted)} expected to pass")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    verdict = "PASS" if passed == len(wanted) else "FAIL"
    print(f"NEWTESTS {verdict} {passed} of {len(wanted)} W8/W9 tests passed")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "listcheck": listcheck, "as632": as632, "newtests": newtests}[command](*rest)
