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
  setup-fail  'Install graftling and pinned test tools' fails; later steps are skipped; the artifact holds only
              environment.json (no JUnit). FAIL (mechanics).
  exit2       the suite step fails with pytest exit code 2 and a collection error. FAIL (mechanics and results).
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
    code = "1"
    if shown == "exit2":
        code = "2"
        broken = ET.SubElement(tree.getroot().find("testsuite"), "testcase",
                               {"classname": "", "name": "tests.test_broken", "file": "tests/test_broken.py"})
        ET.SubElement(broken, "error", {"message": "collection failure"}).text = "ImportError: No module named 'fcntl'"
    tree.write(directory / "junit.xml", encoding="utf-8", xml_declaration=True)
    (directory / "pytest-exit-code.txt").write_text(code + "\n")


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
