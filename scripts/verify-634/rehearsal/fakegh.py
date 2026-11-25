"""Task 634 rehearsal stand-in for gh: canned REST JSON shaped like GitHub's actions responses, and the artifact of
.github/run_test_files.py. Adapted from scripts/verify-632/rehearsal/fakegh.py; never contacts GitHub.

Called as: python fakegh.py <state-dir> <gh arguments...>. <state-dir> holds:
  scenario   the case (below);   junit   a JUnit file (xunit1) of the candidate's macOS run with simulated Windows skips;
  fails      node ids the artifact reports as failing (the `fail` entries of the edited windows-expected.txt);
  removed    node ids of the W2 (634) entries this Task removed from the list;
  polls / attempt   counters this stand-in keeps.
Tests skipped on macOS with a 'Windows-only: ' reason (tests/test_locks_durable_634.py) run on Windows: the artifact
shows them passed.
Scenarios:
  matched     the push run appears on the 2nd poll and completes on the 3rd; the suite step fails (tests failed), every
              other step succeeds; the artifact's failures are exactly `fails`. Expected verdict PASS.
  residual    as matched, but the first removed W2 test still fails, now at a point another Task owns
              (src\\graftling\\connection.py:68), and the first listed failure passes. FAIL, naming both; the observed
              list carries the residual with its new origin and a suggested Task.
  rerun       attempt 1 as residual; after `run rerun --failed` attempt 2 appears on the next poll and is as matched.
  timeout     only another workflow ever runs for the SHA.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verify-632"))
from wincheck import nodeid  # noqa: E402

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graftling"
PATH = ".github/workflows/windows.yml"
BRANCH = "agent/634-graftling-windows-durable-writes"
RUN_ID, JOB_ID = 51000000634, 52000000634
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


def kind() -> str:
    """What the current attempt shows."""
    if scenario == "rerun":
        return "matched" if attempt() >= 2 else "residual"
    return scenario


def run(sha: str, run_id: int, status: str, conclusion, event: str = "push") -> dict:
    return {"id": run_id, "name": "Windows tests", "path": PATH, "head_branch": BRANCH, "head_sha": sha, "event": event,
            "status": status, "conclusion": conclusion, "run_attempt": attempt(),
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
    if event:
        items = [item for item in items if item["event"] == event]
    return {"total_count": len(items), "workflow_runs": items}


def one_run(run_id: int) -> dict:
    if scenario == "rerun" and attempt() >= 2 and counter("polls_after_rerun", 1) < 2:
        return run(sha_of(), run_id, "in_progress", None)
    return run(sha_of(), run_id, "completed", "failure")


def steps() -> list:
    names = ["Set up job", *SETUP[:4], *SETUP[4:], SUITE, UPLOAD, "Post Set up Python 3.13.7 x64",
             "Post Set up Node 22.18.0 x64", "Post Check out the commit under test", "Complete job"]
    result = []
    for number, name in enumerate(names, 1):
        conclusion = "failure" if name == SUITE else "skipped" if name.startswith("Post Set up") else "success"
        result.append({"name": name, "status": "completed", "conclusion": conclusion, "number": number})
    return result


def fail(case: ET.Element, message: str, frame: str) -> None:
    for child in list(case):
        case.remove(child)
    failure = ET.SubElement(case, "failure", {"message": message})
    failure.text = (f"{case.get('file').replace('/', chr(92))}:{int(case.get('line')) + 3}: in {case.get('name')}\n"
                    f"{frame}\nE   {message}")


def artifact(directory: Path) -> None:
    """Write the run's artifact files into directory, as `gh run download -D` does."""
    shown = kind()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "environment.json").write_text(json.dumps({
        "commit": sha_of(), "os": "Microsoft Windows NT 10.0.26100.0", "image": "win25", "image_version": "20261123.1",
        "arch": "AMD64", "python": "Python 3.13.7", "pytest": "pytest 8.3.5", "node": "v22.18.0", "codepage": 1252}))
    tree = ET.parse(state / "junit")
    fails = [line for line in (state / "fails").read_text().splitlines() if line]
    removed = [line for line in (state / "removed").read_text().splitlines() if line]
    cases = {nodeid(case): case for case in tree.getroot().iter("testcase")}
    for case in cases.values():   # the macOS run's own outcomes do not count, except POSIX-only and environment skips
        for child in [c for c in case if c.tag in ("failure", "error")
                      or (c.tag == "skipped" and (c.get("message") or "").startswith("Windows-only: "))]:
            case.remove(child)
    failing = set(fails)
    if shown == "residual":   # the first listed failure passes (a simulated POSIX-only skip inside it is cleared)
        failing.discard(fails[0])
        for child in list(cases[fails[0]]):
            cases[fails[0]].remove(child)
    for node in failing:
        fail(cases[node], "PermissionError: [WinError 5] Access is denied",
             "src\\graftling\\sessions\\archive.py:104: in _replace\n    os.fsync(directory)")
    if shown == "residual":
        fail(cases[removed[0]], "graftling.tool.AgentsError: Windows does not support the authenticated local control pipe.",
             "src\\graftling\\connection.py:68: in agents_connection\n    raise AgentsError('authority-denied', ...)")
    by_file: dict[str, list] = {}
    for case in cases.values():
        by_file.setdefault(case.get("file"), []).append(case)
    for part in ("junit", "logs"):
        (directory / part).mkdir(exist_ok=True)
    records = []
    for test_file in sorted(by_file):
        stem = Path(test_file).stem
        members = by_file[test_file]
        code = 1 if any(case.find("failure") is not None for case in members) else 0
        suite = ET.Element("testsuite", {"name": "pytest", "tests": str(len(members))})
        suite.extend(members)
        for case in members:   # as the Windows runner writes them (run 45608819873): tests\test_x.py
            case.set("file", case.get("file").replace("/", "\\"))
        out = ET.ElementTree(ET.Element("testsuites"))
        out.getroot().append(suite)
        out.write(directory / "junit" / f"{stem}.xml", encoding="utf-8", xml_declaration=True)
        lines = [f"{nodeid(case)} {'FAILED' if case.find('failure') is not None else 'PASSED'}" for case in members]
        (directory / "logs" / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        records.append({"file": test_file, "log": f"logs\\{stem}.txt", "outcome": "ended", "pipe_closed": True,
                        "elapsed_s": 2.5, "junit": f"junit\\{stem}.xml", "exit_code": code})
    (directory / "files.json").write_text(json.dumps({"file_limit_s": 360.0, "total_limit_s": 4200.0, "files": records}))
    (directory / "run-exit-code.txt").write_text("1\n")


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify634-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-634 fake)\n"
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
        job = {"id": JOB_ID, "name": "windows-tests", "status": "completed", "conclusion": "failure",
               "html_url": f"https://github.com/{REPO}/actions/runs/{m.group(1)}/job/{JOB_ID}", "steps": steps()}
        print(json.dumps({"total_count": 1, "jobs": [job]}))
    elif re.fullmatch(rf"repos/{REPO}/actions/jobs/\d+/logs", endpoint):
        if not escapes:
            print("the response contains terminal escape sequences; pass --allow-escape-sequences", file=sys.stderr)
            sys.exit(1)
        print("2026-11-25T00:00:00Z \x1b[36;1mRun the graftling test suite\x1b[0m")
        print("2026-11-25T00:10:00Z ===== 138 failed, 600 passed, 250 skipped in 600.00s (0:10:00) =====")
        print("2026-11-25T00:10:00Z run_test_files exit code: 1")
    else:
        print(f"gh: Not Found (HTTP 404) {endpoint}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "download"]:
    name, target = args[args.index("-n") + 1], Path(args[args.index("-D") + 1])
    want = f"graftling-windows-junit-{sha_of()}-{attempt()}"
    if name != want:
        print(f"no artifact matches any of the names or patterns provided ({name}; have {want})", file=sys.stderr)
        sys.exit(1)
    artifact(target)
elif args[:2] == ["run", "rerun"] and "--failed" in args:
    counter("attempt", 1 if counter("attempt") else 2)
    print(f"✓ Requested rerun (failed jobs) of run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
