"""Task 633 (W1) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck633.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF               the workflow at the bundle head is the one at BASE with only its push branches
                                       line changed, and its push branches are exactly BRANCHES (below)
  w1edit OLD NEW                       the expected list NEW differs from OLD (7add0b40) only in its 23 W1 (633)
                                       lines: the 7 of DELETED removed, the 16 of OWNERS kept in place with the owner
                                       Main decided and a note citing run 45620245600; every other line byte-identical
                                       and in order (correction 1)
  confirm DIR                          read only: for each node id of OWNERS, whether the failure text in the
                                       artifact DIR's per-file JUnit holds the cause (frame and message) of its owner;
                                       one line per node id, last line CONFIRM PASS|FAIL
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
# The 23 W1 (633) lines of scripts/verify-632/windows-expected.txt at GraphTraj 7add0b40 (Task 633 correction 1).
# Passed in run 45620245600 and deleted:
DELETED = [
    "tests/test_agent_control.py::test_lost_owner_keeps_process_facts_and_blocks_duplicates",
    "tests/test_dsh_standalone_host.py::test_host_refuses_a_parent_that_is_not_the_native_dsh",
    "tests/test_dsh_standalone_host.py::test_host_start_refusals",
    "tests/test_pi_default_host_572.py::test_an_uncreatable_default_root_is_refused_naming_the_flag",
    "tests/test_unified_data_root_577.py::test_dsh_host_refuses_a_relative_variable",
    "tests/test_unified_data_root_577.py::test_pi_host_refuses_an_uncreatable_variable",
    "tests/test_pi_standalone_host.py::test_host_start_refusals",
]
# Failing in run 45620245600 at the next cause; owner decided by Main 2026-11-25.
W3, W4 = "W3 (635)", "W4 (636)"
OWNERS = {
    "tests/test_agent_control.py::test_direct_parent_confirms_an_ended_execution_whose_processes_are_gone": W3,
    "tests/test_dsh_standalone_host.py::test_host_binds_only_the_supplied_native_session": W4,
    "tests/test_dsh_standalone_host.py::test_host_starts_with_archiving_on": W4,
    "tests/test_dsh_standalone_host.py::test_host_without_configuration_serves_the_project_data_root": W4,
    "tests/test_pi_default_host_572.py::test_the_host_without_config_serves_the_project_default": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_that_is_never_told_ready_keeps_its_notices_held[dsh]": W4,
    "tests/test_pi_dsh_notice_holding.py::test_a_real_host_process_that_is_never_told_ready_keeps_its_notices_held[pi]": W4,
    "tests/test_pi_dsh_notice_holding.py::test_real_extension_and_host_deliver_once_when_pi_writes_the_notice": W4,
    "tests/test_pi_dsh_notice_holding.py::test_real_extension_and_host_do_not_inject_twice_after_a_crash_before_shown": W4,
    "tests/test_pi_dsh_notice_holding.py::test_real_extension_and_host_keep_a_notice_quit_before_pi_wrote_it": W4,
    "tests/test_pi_dsh_notice_holding.py::test_real_extension_waits_for_the_entry_after_message_end": W4,
    "tests/test_pi_standalone_host.py::test_host_starts_from_root_only_and_closes_at_shutdown": W4,
    "tests/test_unified_data_root_577.py::test_dsh_configuration_wins_over_the_variable": W4,
    "tests/test_unified_data_root_577.py::test_dsh_host_uses_the_variable_instead_of_the_project_root": W4,
    "tests/test_unified_data_root_577.py::test_pi_configuration_wins_over_the_variable": W4,
    "tests/test_unified_data_root_577.py::test_pi_host_uses_the_variable_instead_of_the_project_root": W4,
}
# The cause each owner rests on: a frame and the message, both in the testcase's failure text.
CAUSES = {
    W4: ('connection.py", line 68, in worker_connection',
         "Windows does not support the authenticated local control pipe."),
    W3: ("control.py:229: in _group_alive", "module 'os' has no attribute 'killpg'"),
}
NOTE_START = "after W1 (run 45620245600): "
NOTE_END = "; owner decided by Main 2026-11-25"


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


def _owner(line):
    fields = line.split("\t")
    return fields[3] if line.startswith("fail\t") and len(fields) >= 4 else None


def w1edit(old_file, new_file):
    """Against the list at 7add0b40: each of the 23 W1 (633) lines is deleted (DELETED) or kept in place with the
    owner Main decided (OWNERS), its node id and origin unchanged and a note citing the run; every other line
    byte-identical and in order."""
    old = open(old_file, encoding="utf-8").read().split("\n")
    new = open(new_file, encoding="utf-8").read().split("\n")
    bad, expected = [], []   # expected: the new file line by line, as a line or as (node id, origin) for a moved one
    old_w1 = [line.split("\t")[1] for line in old if _owner(line) == W1]
    if sorted(old_w1) != sorted(DELETED + list(OWNERS)):
        bad.append(f"the base's W1 (633) lines are not exactly the {len(DELETED)} deleted and {len(OWNERS)} moved "
                   "of the table")
    for line in old:
        if _owner(line) != W1:
            expected.append(line)
            continue
        fields = line.split("\t")
        if fields[1] in OWNERS:
            expected.append((fields[1], fields[2]))
    if len(new) != len(expected):
        bad.append(f"{len(new)} lines, expected {len(expected)} (lines added or removed beyond the table)")
    for number, (want, have) in enumerate(zip(expected, new), 1):
        if isinstance(want, str):
            if want != have:
                bad.append(f"line {number} differs from the base: {have[:120]!r}")
            continue
        fields = have.split("\t")
        node, origin = want
        if (len(fields) != 5 or fields[:3] != ["fail", node, origin] or fields[3] != OWNERS[node]
                or not fields[4].startswith(NOTE_START) or not fields[4].endswith(NOTE_END)):
            bad.append(f"line {number}: {node} is not kept in place with owner {OWNERS[node]} and a note "
                       f"'{NOTE_START}...{NOTE_END}' (have owner {fields[3] if len(fields) > 3 else '?'})")
    print(f"expected list: {len(old_w1)} W1 (633) entries at the base: {len(DELETED)} to delete, "
          f"{len(OWNERS)} moved to Main's owners ("
          + ", ".join(f"{task} {list(OWNERS.values()).count(task)}" for task in sorted(set(OWNERS.values()))) + ")")
    for problem in bad[:20]:
        print("FAIL: " + problem)
    if not bad:
        print("PASS: the W1 (633) lines are deleted or moved to Main's owners as tabled; every other line is "
              "byte-identical and in order")
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


def confirm(directory):
    """For each moved line, whether this run's failure text carries the cause Main's owner decision rests on."""
    cases, confirmed = _cases(directory), 0
    print(f"--- {len(OWNERS)} W1 lines moved by Main's decision; cause looked for in each testcase's failure text")
    for node, owner in OWNERS.items():
        case = cases.get(node)
        failures = [] if case is None else [child for child in case if child.tag in ("failure", "error")]
        text = "\n".join((child.get("message") or "") + "\n" + (child.text or "") for child in failures)
        frame, message = CAUSES[owner]
        lines = [line.strip().lstrip("E").strip() for line in text.splitlines()]
        hit_frame = next((line for line in lines if frame in line), None)
        hit_message = next((line for line in lines if message in line), None)
        state = ("absent" if case is None else "passed" if not failures else
                 "found" if hit_frame and hit_message else "not found")
        confirmed += state == "found"
        print(f"{node}\t{state}\t{owner}\t{hit_frame or '-'} | {hit_message or '-'}")
    print(f"CONFIRM {'PASS' if confirmed == len(OWNERS) else 'FAIL'} {confirmed} of {len(OWNERS)} found")


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
    {"wfdiff": wfdiff, "w1edit": w1edit, "newtests": newtests, "confirm": confirm}[command](*rest)
