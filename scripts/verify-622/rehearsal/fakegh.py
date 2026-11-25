"""Task 622 rehearsal stand-in for gh: canned responses shaped like GitHub's REST and `gh run view --log`.

Called as: python fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case:
noise (the guarded run's log has the 618 libproc line), clean (summary, no noise), nosummary (no pytest
summary in the step), none (no listed run's commit holds the guard), wait (the guarded run is in_progress
for two polls, then completed and clean); for step P: psuccess (the pushed sha's desktop-win-adoption run
appears on the 2nd head_sha poll, in_progress for two polls, then completed and clean), ptimeout (only another
workflow's run ever appears for the pushed sha), pdiverged (never reached: P stops before pushing). Log lines use the real format: job<TAB>step<TAB>timestamp text,
taken from 618 realhost/main-raw/main-console-P.txt. Never contacts GitHub.
"""
import base64
import json
import re
import sys
from pathlib import Path

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graphtraj"
OLD = "055669d9fc86fab33cc843fd926cdaed340f3038"  # 618's head: no guard
GUARDED = "6220000000000000000000000000000000000622"
OTHER = "aaaa000000000000000000000000000000000001"  # a newer run of another branch: no guard
JOB, STEP = "windows-adoption", "Build desktop and check Windows native settings"
OLD_FILE = "def pytest_sessionfinish(session):\n    report = reclaim_test_run(value)\n"
NEW_FILE = ("def reclaim_supported() -> bool:\n    return True\n\n"
            "def pytest_sessionfinish(session):\n    if not reclaim_supported():\n        return\n")


def run(rid, sha, created, run_state="completed", conclusion="failure"):
    return {"id": rid, "head_sha": sha, "status": run_state, "conclusion": conclusion if run_state == "completed" else None,
            "created_at": created, "path": ".github/workflows/desktop-win-adoption.yml",
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def guarded_state():
    if scenario not in ("wait", "psuccess"):
        return "completed"
    counter = state / "polls"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    return "in_progress" if n <= 2 else "completed"


def runs():
    items = [run(45546698610, OLD, "2026-11-25T04:20:00Z")]
    if scenario != "none":
        items.append(run(45600000622, GUARDED, "2026-11-26T01:00:00Z", "in_progress" if scenario == "wait" else "completed"))
        items.append(run(45600000700, OTHER, "2026-11-26T02:00:00Z"))
    return {"total_count": len(items), "workflow_runs": items}


PUSHED_RUN = 45600000999


def runs_for_sha(sha):
    (state / "pushed_sha").write_text(sha)
    counter = state / "appear_polls"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    items = []
    if scenario == "psuccess" and n >= 2:
        items.append(run(PUSHED_RUN, sha, "2026-11-26T03:00:00Z", "in_progress"))
    if scenario == "ptimeout":
        other = run(45600000998, sha, "2026-11-26T03:00:00Z", "queued")
        other["path"] = ".github/workflows/other.yml"
        items.append(other)
    return {"total_count": len(items), "workflow_runs": items}


def line(text, step=STEP, t="2026-11-26T01:10:26.6337076Z"):
    return f"{JOB}\t{step}\t{t} {text}"


def log():
    rows = [line("Run actions/checkout@v4", "Set up job"),
            line("\x1b[32m✓ built in 7.41s\x1b[39m"),
            line("ERROR: found no collectors for D:\\a\\graphtraj\\graphtraj\\tests\\test_desktop_activity.py")]
    if scenario == "noise":
        rows += [line(""), line("leftover test processes of PYTEST_GRAPHTRAJ_RUN=6c81f68640794b36a9c265b3e6e88184: found=0 "
                                "stopped=0 remaining=0 error=Could not find module 'D:\\usr\\lib\\libproc.dylib' (or one of "
                                "its dependencies). Try using the full path with constructor syntax.")]
    rows += [line("E   ModuleNotFoundError: No module named 'fcntl'"),
             line("=========================== short test summary info ===========================")]
    if scenario != "nosummary":
        rows += [line("ERROR tests/test_desktop_activity.py"), line("1 error in 0.43s")]
    rows += [line("##[error]Process completed with exit code 1."), line("Post job cleanup.", "Complete job")]
    return "\n".join(rows)


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify622-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-622 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    lst = re.fullmatch(rf"repos/{REPO}/actions/workflows/desktop-win-adoption\.yml/runs\?per_page=30", args[1])
    one = re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)", args[1])
    by_sha = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]{{40}})&per_page=100", args[1])
    content = re.fullmatch(rf"repos/{REPO}/contents/tests/process_reclaim\.py\?ref=([0-9a-f]+)", args[1])
    if lst:
        print(json.dumps(runs()))
    elif one and int(one.group(1)) == 45600000622 and scenario != "none":
        print(json.dumps(run(45600000622, GUARDED, "2026-11-26T01:00:00Z", guarded_state())))
    elif by_sha:
        print(json.dumps(runs_for_sha(by_sha.group(1))))
    elif one and int(one.group(1)) == PUSHED_RUN:
        print(json.dumps(run(PUSHED_RUN, (state / "pushed_sha").read_text(), "2026-11-26T03:00:00Z", guarded_state())))
    elif one and int(one.group(1)) == 45546698610:
        print(json.dumps(run(45546698610, OLD, "2026-11-25T04:20:00Z")))
    elif content:
        text = OLD_FILE if content.group(1) in (OLD, OTHER) else NEW_FILE
        print(json.dumps({"path": "tests/process_reclaim.py", "encoding": "base64",
                          "content": base64.encodebytes(text.encode()).decode()}))
    else:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "view"] and "--log" in args:
    print(log())
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
