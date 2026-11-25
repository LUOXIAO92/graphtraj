"""Task 635 (W3) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck635.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE (graftling bc4298b6) with only
                                       its push branches line changed, and its push branches are exactly BRANCHES
  w3edit OLD NEW                       the expected list NEW differs from OLD (GraphTraj 8b37c970) only in its 7 W3
                                       (635) lines: the one of DELETED removed, the 6 of KEPT kept in place with node
                                       id, origin and owner unchanged and their note extended by ' | after W3: ...'
                                       naming the suggested owner; every other line byte-identical and in order
  as632 BASE_WF OUT                    write to OUT the base workflow with its push branches line (633's) set back
                                       to 632's, so 632's wfcheck judges every other property of it unchanged;
                                       fails unless 633's line is there exactly once
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

BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process", "dev"]
BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
            "agent/635-graftling-windows-process-tree", "dev"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
W3 = "W3 (635)"
# The 7 W3 (635) lines of scripts/verify-632/windows-expected.txt at GraphTraj 8b37c970.
# After W3 _group_alive answers on Windows, so the test goes on to its require_posix part: a POSIX-only skip,
# which needs no entry. Deleted:
DELETED = [
    "tests/test_agent_control.py::test_direct_parent_confirms_an_ended_execution_whose_processes_are_gone",
]
# Still failing after W3 for a cause outside W3; kept with owner W3 (635) for Main's decision, the note extended
# with the suggested owner.
KEPT = {
    "tests/test_codex_child_interpreter_shutdown_473.py::test_child_ends_completed_after_the_owner_main_thread_returns":
        "W5 (637)",
    "tests/test_envelope_validation_555.py::test_agents_mcp_reads_files_inside_the_verified_session_cwd": "W4 (636)",
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_flushes_once_after_ready_and_a_further_restart_"
    "delivers_nothing[dsh]": "W4 (636)",
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_flushes_once_after_ready_and_a_further_restart_"
    "delivers_nothing[pi]": "W4 (636)",
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_refused_notice_stays_held": "W4 (636)",
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_unacknowledged_notice_ends_as_held_at_shutdown_and_is_"
    "replayed": "W4 (636)",
}
NOTE_JOIN = " | after W3: "


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
        old, new = wanted.splitlines(), head.splitlines()
        changed = [f"{n + 1}: {a!r} -> {b!r}" for n, (a, b) in enumerate(zip(old, new)) if a != b]
        print(f"FAIL: the workflow differs from the base beyond the push branches line "
              f"({len(old)} -> {len(new)} lines; first differences: {changed[:3]})")
        bad += 1
    sys.exit(1 if bad else 0)


def as632(base_file, out_file):
    base = open(base_file, encoding="utf-8").read()
    if base.count(BASE_LINE + "\n") != 1:
        print(f"FAIL: the base workflow does not have exactly one line {BASE_LINE.strip()!r}")
        sys.exit(1)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write(base.replace(BASE_LINE + "\n", LINE_632 + "\n"))
    print(f"PASS: the base workflow's push branches line is 633's; judged below with it set back to 632's")


def _owner(line):
    fields = line.split("\t")
    return fields[3] if line.startswith("fail\t") and len(fields) >= 4 else None


def w3edit(old_file, new_file):
    """Against the list at 8b37c970: each of the 7 W3 (635) lines is deleted (DELETED) or kept in place (KEPT) with
    fields 1-4 unchanged and the note extended by ' | after W3: ...' naming the suggested owner; every other line
    byte-identical and in order."""
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")
    bad, expected = [], []   # expected: the new file line by line, as a line or as the base fields of a kept one
    old_w3 = [line.split("\t")[1] for line in old if _owner(line) == W3]
    if sorted(old_w3) != sorted(DELETED + list(KEPT)):
        bad.append(f"the base's W3 (635) lines are not exactly the {len(DELETED)} deleted and {len(KEPT)} kept "
                   "of the table")
    for line in old:
        if _owner(line) != W3:
            expected.append(line)
        elif line.split("\t")[1] in KEPT:
            expected.append(line.split("\t"))
    if len(new) != len(expected):
        bad.append(f"{len(new)} lines, expected {len(expected)} (lines added or removed beyond the table)")
    for number, (want, have) in enumerate(zip(expected, new), 1):
        if isinstance(want, str):
            if want != have:
                bad.append(f"line {number} differs from the base: {have[:120]!r}")
            continue
        fields = have.split("\t")
        node, base_note = want[1], want[4] if len(want) > 4 else ""
        suggested = f"suggested owner {KEPT[node]}"
        if (len(fields) != 5 or fields[:4] != want[:4] or not fields[4].startswith(base_note + NOTE_JOIN)
                or suggested not in fields[4][len(base_note):]):
            bad.append(f"line {number}: {node} is not kept in place with fields 1-4 unchanged and its note extended "
                       f"by '{NOTE_JOIN.strip()} ...' naming '{suggested}'")
    print(f"expected list: {len(old_w3)} W3 (635) entries at the base: {len(DELETED)} to delete, {len(KEPT)} kept "
          f"with an 'after W3:' note (suggested "
          + ", ".join(f"{task} {list(KEPT.values()).count(task)}" for task in sorted(set(KEPT.values()))) + ")")
    for problem in bad[:20]:
        print("FAIL: " + problem)
    if not bad:
        print("PASS: the W3 (635) lines are deleted or kept with an 'after W3:' note as tabled; every other line is "
              "byte-identical and in order")
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
    print(f"--- the W3 tests (635) in this run: {len(wanted)} expected to pass")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    if passed == len(wanted):
        print(f"NEWTESTS PASS {passed} of {len(wanted)} W3 tests passed")
    else:
        print(f"NEWTESTS FAIL {passed} of {len(wanted)} W3 tests passed")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "w3edit": w3edit, "as632": as632, "newtests": newtests}[command](*rest)
