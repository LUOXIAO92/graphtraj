"""Task 632 rehearsal stand-in for gh: canned REST JSON shaped like GitHub's actions responses, and JUnit artifacts.

Called as: python fakegh.py <state-dir> <gh arguments...>. Never contacts GitHub. <state-dir> holds:
  scenario   the case (below);   junit   a real JUnit file (xunit1) from the macOS run with simulated Windows skips;
  fails      node ids the artifact reports as failing with a Windows-style traceback (one per line);
  polls / attempt / dispatched   counters this stand-in keeps.
Scenarios:
  matched     the push run appears on the 2nd poll and completes on the 3rd; the suite step fails (tests failed), every
              other step succeeds; the artifact's failures are exactly `fails`. Expected verdict PASS.
  mismatch    as matched, but one more test fails, the first listed failure passes, and one test skips with an
              unprefixed reason ('Node is required'). FAIL, naming all three.
  The artifact is laid out as .github/run_test_files.py leaves it: files.json, junit/<stem>.xml and logs/<stem>.txt per
  test file (split from `junit` by each testcase's file), run-exit-code.txt, environment.json.
  setup-fail  'Install graftling and pinned test tools' fails; later steps are skipped; the artifact holds only
              environment.json (no records). FAIL (mechanics).
  exit2       the first test file ends with pytest exit code 2 and a collection error. FAIL (mechanics and results).
  hang        as matched, but tests/test_agent_control.py was stopped after its limit and recorded as hung (no JUnit;
              its log holds -v lines and a faulthandler dump through src/graftling/control.py:2140). With a `hang`
              entry for its last started test: PASS.
  hang-unexpected  the same hang without a `hang` entry: FAIL, naming it with origin control.py:2140.
  missing-record   files.json lacks the first test file: FAIL (mechanics).
  not-run     the last test file is recorded not-run (total limit spent): FAIL (mechanics).
  winpaths    as matched, but written as the Windows runner writes it (run 45608819873): files.json `junit`/`log`
              with backslashes and xunit1 `file` attributes `tests\test_x.py`. PASS (node ids tests/test_x.py::name).
  rerun       attempt 1 as mismatch; after `run rerun --failed` attempt 2 appears on the next poll and is as matched.
  dispatch    as matched; `workflow run` adds a workflow_dispatch run (another id) on the next poll.
  timeout     only another workflow ever runs for the SHA.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wincheck import nodeid  # noqa: E402

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graftling"
PATH = ".github/workflows/windows.yml"
BRANCH = "agent/632-graftling-windows-ci"
RUN_ID, DISPATCH_ID, JOB_ID = 51000000000, 51000000077, 52000000000
SETUP = ["Keep symbolic links on this runner", "Check out the commit under test",
         "Fail unless the linked package documents are symbolic links", "Set up Node 22.18.0 x64",
         "Set up Python 3.13.7 x64", "Install graftling and pinned test tools", "Show runner, Python and pytest versions"]
SUITE, UPLOAD = "Run the graftling test suite", "Retain JUnit results"


def counter(name: str, step: int = 0) -> int:
    path = state / name
    value = int(path.read_text()) if path.exists() else 0
    if step:
        value += step
        path.write_text(str(value))
    return value


def attempt() -> int:
    return max(1, counter("attempt"))


def kind(run_id: int) -> str:
    """What this run (and attempt) shows."""
    if scenario == "rerun":
        return "matched" if attempt() >= 2 else "mismatch"
    if scenario == "dispatch":
        return "matched"
    return scenario


def run(sha: str, run_id: int, status: str, conclusion, event: str = "push") -> dict:
    return {"id": run_id, "name": "Windows tests", "path": PATH, "head_branch": BRANCH, "head_sha": sha, "event": event,
            "status": status, "conclusion": conclusion, "run_attempt": attempt() if run_id == RUN_ID else 1,
            "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"}


def sha_of() -> str:
    return (state / "sha").read_text().strip() if (state / "sha").exists() else "0" * 40


def runs_for(sha: str, event: str | None) -> dict:
    (state / "sha").write_text(sha)
    n = counter("polls", 1)
    other = {**run(sha, RUN_ID + 9, "completed", "success"), "path": ".github/workflows/other.yml", "name": "other"}
    items = []
    if scenario == "timeout":
        items = [other]
    elif n >= 2:
        items = [run(sha, RUN_ID, "completed" if n >= 3 else "in_progress", "failure" if n >= 3 else None)]
    if scenario == "dispatch" and (state / "dispatched").exists():
        items.append(run(sha, DISPATCH_ID, "completed", "failure", "workflow_dispatch"))
    if event:
        items = [item for item in items if item["event"] == event]
    return {"total_count": len(items), "workflow_runs": items}


def one_run(run_id: int) -> dict:
    sha = sha_of()
    if run_id == DISPATCH_ID:
        return run(sha, run_id, "completed", "failure", "workflow_dispatch")
    if scenario == "rerun" and attempt() >= 2 and counter("polls_after_rerun", 1) < 2:
        return run(sha, run_id, "in_progress", None)
    return run(sha, run_id, "completed", "failure")


def steps(run_id: int) -> list:
    shown = kind(run_id)
    names = ["Set up job", *SETUP[:4], "Run actions/setup-node", *SETUP[4:], SUITE, UPLOAD,
             "Post Set up Python 3.13.7 x64", "Post Set up Node 22.18.0 x64", "Post Check out the commit under test",
             "Complete job"]
    result, after = [], False
    for number, name in enumerate(names, 1):
        if shown == "setup-fail" and name == "Install graftling and pinned test tools":
            conclusion, after = "failure", True
        elif name == SUITE and shown != "setup-fail":
            conclusion = "failure"
        elif after and name not in (UPLOAD, "Complete job") and not name.startswith("Post Check out"):
            conclusion = "skipped"
        elif name.startswith("Post Set up") and shown != "setup-fail":
            conclusion = "skipped"   # their post-if is success(); the suite step failed
        else:
            conclusion = "success"
        result.append({"name": name, "status": "completed", "conclusion": conclusion, "number": number})
    return [step for step in result if step["name"] != "Run actions/setup-node"]


def artifact(run_id: int, directory: Path) -> None:
    """Write the run's artifact files into directory, as `gh run download -D` does."""
    shown = kind(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "environment.json").write_text(json.dumps({
        "commit": sha_of(), "os": "Microsoft Windows NT 10.0.26100.0", "image": "win25", "image_version": "20261123.1",
        "arch": "AMD64", "python": "Python 3.13.7", "pytest": "pytest 8.3.5", "node": "v22.18.0", "codepage": 1252}))
    if shown == "setup-fail":
        return
    tree = ET.parse(state / "junit")
    fails = [line for line in (state / "fails").read_text().splitlines() if line]
    cases = {nodeid(case): case for case in tree.getroot().iter("testcase")}
    for case in cases.values():   # the macOS run's own failures, if any, do not count: only the scenario decides
        for child in [c for c in case if c.tag in ("failure", "error")]:
            case.remove(child)
    failing = set(fails)
    if shown == "mismatch":
        failing.discard(fails[0])                      # a listed failure passes
        extra = next(node for node, case in cases.items() if len(case) == 0 and node not in failing)
        failing.add(extra)                             # an unlisted test fails
        skipper = next(node for node, case in cases.items() if len(case) == 0 and node not in failing)
        ET.SubElement(cases[skipper], "skipped", {"type": "pytest.skip", "message": "Node is required"}).text = \
            "tests\\x.py:1: Node is required"
    for node in failing:
        case = cases[node]
        for child in list(case):
            case.remove(child)
        failure = ET.SubElement(case, "failure", {"message": "graftling.tool.AgentsError: Windows does not support "
                                                  "the authenticated local control pipe."})
        failure.text = (f"{case.get('file').replace('/', chr(92))}:{int(case.get('line')) + 3}: in {case.get('name')}\n"
                        "    outcome = agents_connection(address)\n"
                        "src\\graftling\\connection.py:68: in agents_connection\n"
                        "    raise AgentsError('authority-denied', 'Windows does not support ...')\n"
                        "E   graftling.tool.AgentsError: Windows does not support the authenticated local control pipe.")
    # As .github/run_test_files.py leaves it: one JUnit file and log per test file, files.json, run-exit-code.txt.
    by_file: dict[str, list] = {}
    for case in cases.values():
        by_file.setdefault(case.get("file"), []).append(case)
    for part in ("junit", "logs"):
        (directory / part).mkdir(exist_ok=True)
    records = []
    for test_file in sorted(by_file):
        stem = Path(test_file).stem
        record = {"file": test_file, "log": f"logs/{stem}.txt", "outcome": "ended", "pipe_closed": True,
                  "elapsed_s": 2.5, "junit": f"junit/{stem}.xml"}
        members = by_file[test_file]
        lines = [f"{nodeid(case)} {'FAILED' if case.find('failure') is not None else 'PASSED'}" for case in members]
        if shown in ("hang", "hang-unexpected") and test_file == HUNG_FILE:
            started = lines[:3] + [HUNG_TEST + " "]
            (directory / record["log"]).write_text("\n".join(started) + HUNG_DUMP, encoding="utf-8")
            record.update(outcome="hung", exit_code=None, junit=None, elapsed_s=360.2, last_started=HUNG_TEST,
                          last_finished=False, stopped="taskkill /T /F exit 0: SUCCESS: The process with PID 4242 "
                          "(child process of PID 4240) has been terminated.")
            records.append(record)
            continue
        if shown == "not-run" and test_file == sorted(by_file)[-1]:
            records.append({"file": test_file, "outcome": "not-run", "exit_code": None, "elapsed_s": 0, "junit": None,
                            "reason": "--total-limit 4200 s spent"})
            continue
        if shown == "missing-record" and test_file == sorted(by_file)[0]:
            continue
        code = 1 if any(case.find("failure") is not None for case in members) else 0
        suite = ET.Element("testsuite", {"name": "pytest", "tests": str(len(members))})
        suite.extend(members)
        if shown == "exit2" and test_file == sorted(by_file)[0]:
            code = 2
            broken = ET.SubElement(suite, "testcase", {"classname": "", "name": "tests.test_agent_completion",
                                                        "file": test_file})
            ET.SubElement(broken, "error", {"message": "collection failure"}).text = "ImportError: No module named 'fcntl'"
        if shown == "winpaths":   # as the Windows runner writes them (run 45608819873): tests\test_x.py
            for case in members:
                case.set("file", case.get("file").replace("/", "\\"))
        tree_out = ET.ElementTree(ET.Element("testsuites"))
        tree_out.getroot().append(suite)
        tree_out.write(directory / record["junit"], encoding="utf-8", xml_declaration=True)
        (directory / record["log"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
        record["exit_code"] = code
        if shown == "winpaths":   # files.json paths from Path.relative_to on Windows: junit\test_x.xml, logs\test_x.txt
            record.update(junit=record["junit"].replace("/", "\\"), log=record["log"].replace("/", "\\"))
        records.append(record)
    (directory / "files.json").write_text(json.dumps({"file_limit_s": 360.0, "total_limit_s": 4200.0, "files": records}))
    (directory / "run-exit-code.txt").write_text("1\n")


# The hung file of the hang scenarios, shaped like run 45593743762's faulthandler dump (Windows paths).
HUNG_FILE = "tests/test_agent_control.py"
HUNG_TEST = "tests/test_agent_control.py::test_repeated_controls_never_run_one_session_twice"
HUNG_DUMP = r"""Timeout (0:02:00)!
Thread 0x00001a50 (most recent call first):
  File "C:\hostedtoolcache\windows\Python\3.13.7\x64\Lib\concurrent\futures\thread.py", line 90 in _worker
  File "C:\hostedtoolcache\windows\Python\3.13.7\x64\Lib\threading.py", line 994 in run

Thread 0x00000f00 (most recent call first):
  File "D:\a\graftling\graftling\src\graftling\control.py", line 2140 in _reconcile
  File "D:\a\graftling\graftling\src\graftling\control.py", line 1663 in status
  File "D:\a\graftling\graftling\tests\test_agent_control.py", line 216 in test_repeated_controls_never_run_one_session_twice
  File "C:\hostedtoolcache\windows\Python\3.13.7\x64\Lib\site-packages\_pytest\python.py", line 159 in pytest_pyfunc_call
"""


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify632-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-632 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    escapes = "--allow-escape-sequences" in args
    args = [item for item in args if item != "--allow-escape-sequences"]
    endpoint = args[1]
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)(&event=(\w+))?&per_page=100", endpoint)
    if m:
        print(json.dumps(runs_for(m.group(1), m.group(3))))
    elif (m := re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)", endpoint)):
        print(json.dumps(one_run(int(m.group(1)))))
    elif (m := re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)/attempts/(\d+)/jobs\?per_page=100", endpoint)):
        rid = int(m.group(1))
        job = {"id": JOB_ID + rid % 100, "name": "windows-tests", "status": "completed", "conclusion": "failure",
               "html_url": f"https://github.com/{REPO}/actions/runs/{rid}/job/{JOB_ID}", "steps": steps(rid)}
        print(json.dumps({"total_count": 1, "jobs": [job]}))
    elif re.fullmatch(rf"repos/{REPO}/actions/jobs/\d+/logs", endpoint):
        if not escapes:
            print("the response contains terminal escape sequences; pass --allow-escape-sequences", file=sys.stderr)
            sys.exit(1)
        print("2026-11-25T00:00:00Z \x1b[36;1mRun the graftling test suite\x1b[0m")
        print("2026-11-25T00:10:00Z ===== 3 failed, 700 passed, 244 skipped in 600.00s (0:10:00) =====")
        print("2026-11-25T00:10:00Z pytest exit code: 1")
    else:
        print(f"gh: Not Found (HTTP 404) {endpoint}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "download"]:
    rid, name, target = int(args[2]), args[args.index("-n") + 1], Path(args[args.index("-D") + 1])
    want = f"graftling-windows-junit-{sha_of()}-{attempt() if rid == RUN_ID else 1}"
    if name != want:
        print(f"no artifact matches any of the names or patterns provided ({name}; have {want})", file=sys.stderr)
        sys.exit(1)
    artifact(rid, target)
elif args[:2] == ["run", "rerun"] and "--failed" in args:
    counter("attempt", 1 if counter("attempt") else 2)
    print(f"✓ Requested rerun (failed jobs) of run {args[2]}")
elif args[:2] == ["workflow", "run"]:
    (state / "dispatched").write_text("1")
    print(f"✓ Created workflow_dispatch event for windows.yml at {args[args.index('--ref') + 1]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
