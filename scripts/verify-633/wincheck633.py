"""Task 633 (W1) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck633.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE with only its push branches
                                       line changed, and its push branches are exactly BRANCHES (below)
  w1edit OLD NEW                       the expected list NEW differs from OLD only in lines whose Task is W1 (633):
                                       every other line byte-identical and in order; W1 lines deleted, or kept with
                                       owner W1 (633) and a note starting 'after W1: '
  newtests DIR LIST                    every node id in LIST passed in the merged per-file JUnit files of the artifact
                                       DIR (not failed, errored, skipped or absent); last line NEWTESTS PASS|FAIL
Writes nothing.
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify-632"))
from wincheck import load, nodeid  # noqa: E402

BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process", "dev"]
BASE_LINE = "    branches: [agent/632-graftling-windows-ci, dev]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
W1 = "W1 (633)"


def wfdiff(base_file, head_file):
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
        # Differences from the base with only the branches line replaced.
        old, new = wanted.splitlines(), head.splitlines()
        changed = [f"{n + 1}: {a!r} -> {b!r}" for n, (a, b) in enumerate(zip(old, new)) if a != b]
        print(f"FAIL: the workflow differs from the base beyond the push branches line "
              f"({len(old)} -> {len(new)} lines; first differences: {changed[:3]})")
        bad += 1
    sys.exit(1 if bad else 0)


def w1edit(old_file, new_file):
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")

    def owner(line):
        fields = line.split("\t")
        return fields[3] if line.startswith("fail\t") and len(fields) >= 4 else None

    old_w1 = {line.split("\t")[1]: line for line in old if owner(line) == W1}
    bad = []
    if [line for line in old if owner(line) != W1] != [line for line in new if owner(line) != W1]:
        bad.append("lines not owned by W1 (633) differ (changed, added, removed or reordered)")
    kept = deleted = 0
    for line in new:
        if owner(line) != W1:
            continue
        fields = line.split("\t")
        before = old_w1.get(fields[1], "").split("\t")
        if len(before) < 5 or fields[:4] != before[:4] or len(fields) != 5 or not fields[4].startswith("after W1: "):
            bad.append(f"W1 line changed beyond its note or without 'after W1: ': {fields[1]}")
        kept += 1
    deleted = len(old_w1) - kept
    print(f"expected list: {len(old_w1)} W1 (633) entries at the base: {deleted} deleted (predicted to pass), "
          f"{kept} kept with an 'after W1:' note")
    for problem in bad:
        print("FAIL: " + problem)
    if not bad:
        print("PASS: only W1 (633) lines changed; every other line is byte-identical and in order")
    sys.exit(1 if bad else 0)


def newtests(directory, list_file):
    wanted = [line.strip() for line in open(list_file, encoding="utf-8") if line.strip() and not line.startswith("#")]
    outcome = {}
    records = load(os.path.join(directory, "files.json")).get("files", []) if os.path.exists(
        os.path.join(directory, "files.json")) else []
    for record in records:
        if not record.get("junit"):
            continue
        # The Windows runner writes junit\test_x.xml (run 45608819873).
        path = os.path.join(directory, record["junit"].replace("\\", "/"))
        if not os.path.exists(path):
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            tags = {child.tag for child in case}
            state = ("failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed")
            outcome[nodeid(case)] = state
    passed = 0
    print(f"--- the W1 tests (633) in this run: {len(wanted)} expected to pass")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    if passed == len(wanted):
        print(f"NEWTESTS PASS {passed} of {len(wanted)} W1 tests passed")
    else:
        print(f"NEWTESTS FAIL {passed} of {len(wanted)} W1 tests passed")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "w1edit": w1edit, "newtests": newtests}[command](*rest)
