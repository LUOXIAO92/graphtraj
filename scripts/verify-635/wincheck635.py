"""Task 635 (W3) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck635.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE (graftling dev d5fb80c7) with only
                                       its push branches line changed, and its push branches are exactly BRANCHES
  w3edit OLD NEW                       the expected list NEW differs from OLD (GraphTraj dev 84bccb27) only in its 7 W3
                                       (635) lines: the one of DELETED removed, the 6 of OWNERS kept in place with node
                                       id and origin unchanged, the owner Main decided and a note citing run
                                       45633403789; no W3 (635) line left; every other line byte-identical and in order
  confirm DIR                          read only: for each line of OWNERS, which parts of its owner's cause, and of the
                                       stand-in's own error, its failure text in the artifact DIR holds ('found' or
                                       'not found'); also the run_native siblings the W4 notes rest on
  as632 BASE_WF OUT                    write to OUT the base workflow with its push branches line (633's, 634's and 638's) set back
                                       to 632's, so 632's wfcheck judges every other property of it unchanged;
                                       fails unless that line is there exactly once
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

BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "dev", "agent/638-graftling-windows-paths-encoding"]
BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
            "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
            "agent/638-graftling-windows-paths-encoding", "dev"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
W3, W4, W5 = "W3 (635)", "W4 (636)", "W5 (637)"
# The 7 W3 (635) lines of scripts/verify-632/windows-expected.txt at GraphTraj dev 84bccb27 (the same 7 since 8b37c970).
# The line-48 test runs its whole confirmation through OwnedTree on Windows and passed in run 45633403789
# (635 correction 1); it is in new-tests.txt. Deleted:
DELETED = [
    "tests/test_agent_control.py::test_direct_parent_confirms_an_ended_execution_whose_processes_are_gone",
]
# Still failing after W3 for a cause outside W3; moved to the owner Main decided on 2026-11-25 (correction 2).
OWNERS = {
    "tests/test_codex_child_interpreter_shutdown_473.py::test_child_ends_completed_after_the_owner_main_thread_returns": W5,
    "tests/test_envelope_validation_555.py::test_agents_mcp_reads_files_inside_the_verified_session_cwd": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_flushes_once_after_ready_and_a_further_restart_"
    "delivers_nothing[dsh]": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_flushes_once_after_ready_and_a_further_restart_"
    "delivers_nothing[pi]": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_refused_notice_stays_held": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_unacknowledged_notice_ends_as_held_at_shutdown_and_is_"
    "replayed": W4,
}
NOTE_START = "after W3 (run 45633403789): "
NOTE_END = "decided by Main 2026-11-25"
# What confirm looks for in each moved line's failure text: the cause its owner rests on.
CAUSES = {
    W5: [("frame", "test_codex_child_interpreter_shutdown_473.py:46"),
         ("message", "'NoneType' object has no attribute 'start'")],
    W4: [("host refusal", "connection.py"), ("host refusal message",
                                             "Windows does not support the authenticated local control pipe.")],
}
# The stand-in's own error, which W4 lines show instead of the host's traceback.
STAND_IN = ["JSONDecodeError", "Errno 22"]
# Siblings with the same run_native start whose text shows the host's refusal.
SIBLINGS = [
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_that_is_never_told_ready_keeps_its_notices_held[dsh]",
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_that_is_never_told_ready_keeps_its_notices_held[pi]",
]


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
    print(f"PASS: the base workflow's push branches line is {BASE_BRANCHES}; judged below with it set back to 632's")


def _owner(line):
    fields = line.split("\t")
    return fields[3] if line.startswith("fail\t") and len(fields) >= 4 else None


def w3edit(old_file, new_file):
    """Against the list at dev 84bccb27: of the 7 W3 (635) lines, the one of DELETED is removed and the 6 of OWNERS
    stay in place with node id and origin unchanged, the owner Main decided, and a note starting NOTE_START and
    ending NOTE_END; no W3 (635) line remains; every other line byte-identical and in order (correction 2)."""
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")
    bad, expected = [], []
    old_w3 = [line.split("\t")[1] for line in old if _owner(line) == W3]
    if sorted(old_w3) != sorted(DELETED + list(OWNERS)):
        bad.append(f"the base's W3 (635) lines are not exactly the {len(DELETED)} deleted and {len(OWNERS)} moved "
                   "of the table")
    for line in old:
        if _owner(line) != W3:
            expected.append(line)
        elif line.split("\t")[1] in OWNERS:
            expected.append(line.split("\t"))
    if len(new) != len(expected):
        bad.append(f"{len(new)} lines, expected {len(expected)} (lines added or removed beyond the table)")
    for number, (want, have) in enumerate(zip(expected, new), 1):
        if isinstance(want, str):
            if want != have:
                bad.append(f"line {number} differs from the base: {have[:120]!r}")
            continue
        fields = have.split("\t")
        node = want[1]
        if (len(fields) != 5 or fields[:3] != want[:3] or fields[3] != OWNERS[node]
                or not fields[4].startswith(NOTE_START) or not fields[4].endswith(NOTE_END)):
            bad.append(f"line {number}: {node} is not kept in place with owner {OWNERS[node]} and a note "
                       f"'{NOTE_START}...{NOTE_END}' (have owner {fields[3] if len(fields) > 3 else '?'})")
    if any(_owner(line) == W3 for line in new):
        bad.append("a W3 (635) line remains")
    print(f"expected list: {len(old_w3)} W3 (635) entries at the base: {len(DELETED)} to delete, {len(OWNERS)} moved "
          "to Main's owners (" + ", ".join(f"{task} {list(OWNERS.values()).count(task)}"
                                          for task in sorted(set(OWNERS.values()))) + ")")
    for problem in bad[:20]:
        print("FAIL: " + problem)
    if not bad:
        print("PASS: the W3 (635) lines are deleted or moved to Main's owners as tabled; no W3 (635) line remains; "
              "every other line is byte-identical and in order")
    sys.exit(1 if bad else 0)


def _cases(directory):
    """{node id: testcase} over the per-file JUnit files of an artifact DIR (files.json records)."""
    found = {}
    for record in load(os.path.join(directory, "files.json")).get("files", []):
        if record.get("junit"):
            path = os.path.join(directory, record["junit"].replace("\\", "/"))
            if os.path.exists(path):
                found.update((nodeid(case), case) for case in ET.parse(path).getroot().iter("testcase"))
    return found


def _text(case):
    failures = [] if case is None else [child for child in case if child.tag in ("failure", "error")]
    return "\n".join((child.get("message") or "") + "\n" + (child.text or "") for child in failures), bool(failures)


def confirm(directory):
    """Read only: for each moved line, which parts of its owner's cause its own failure text holds."""
    cases = _cases(directory)
    print(f"--- {len(OWNERS)} W3 lines moved by Main's decision; looked for in each testcase's own failure text")
    for node, owner in OWNERS.items():
        text, failed = _text(cases.get(node))
        state = "absent" if node not in cases else "failed" if failed else "not failed"
        parts = [f"{label} {needle!r}: {'found' if needle in text else 'not found'}" for label, needle in CAUSES[owner]]
        if owner == W4:
            parts += [f"stand-in error {needle!r}: {'found' if needle in text else 'not found'}" for needle in STAND_IN]
        print(f"{node}\t{state}\t{owner}\t" + "; ".join(parts))
    print("--- siblings with the same run_native start (basis of the W4 notes)")
    for node in SIBLINGS:
        text, failed = _text(cases.get(node))
        state = "absent" if node not in cases else "failed" if failed else "not failed"
        parts = [f"{label} {needle!r}: {'found' if needle in text else 'not found'}" for label, needle in CAUSES[W4]]
        print(f"{node}\t{state}\t" + "; ".join(parts))


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
    {"wfdiff": wfdiff, "w3edit": w3edit, "as632": as632, "newtests": newtests, "confirm": confirm}[command](*rest)
