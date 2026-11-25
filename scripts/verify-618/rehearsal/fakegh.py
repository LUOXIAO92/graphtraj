"""Task 618 rehearsal stand-in for gh: canned REST JSON shaped like GitHub's actions/runs responses.

Called as: python fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case:
success (runs appear on the 2nd poll, complete on the 3rd), failure (Windows adoption fails; one other
workflow also runs), timeout (only two of the four workflows ever appear). Never contacts GitHub.
"""
import json
import re
import sys
from pathlib import Path

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graphtraj"
PATHS = [".github/workflows/desktop-linux-adoption.yml", ".github/workflows/desktop-macos-adoption.yml",
         ".github/workflows/desktop-repair-package.yml", ".github/workflows/desktop-win-adoption.yml"]
NAMES = ["Linux installed desktop adoption", "desktop-macos-adoption", "Package direct-save desktop 295",
         "Windows desktop adoption 266"]
JOBS = [["installed-desktop"], ["Installed macOS artifact and adoption"], ["windows-package", "linux-package"],
        ["windows-adoption"]]


def run(i, sha, status, conclusion, path=None, name=None):
    rid = 46000000000 + i
    return {"id": rid, "name": name or NAMES[i], "path": path or PATHS[i], "head_branch": "agent/618-desktop-workflows-graftling-ref",
            "head_sha": sha, "event": "push", "status": status, "conclusion": conclusion, "run_attempt": 1,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def runs(sha):
    counter = state / "polls"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    if scenario == "success":
        if n == 1:
            items = []
        elif n == 2:
            items = [run(i, sha, "in_progress", None) for i in range(4)]
        else:
            items = [run(i, sha, "completed", "success") for i in range(4)]
    elif scenario == "failure":
        done = n >= 2
        items = [run(i, sha, "completed" if done else "queued",
                     ("failure" if i == 3 else "success") if done else None) for i in range(4)]
        items.append(run(9, sha, "completed", "success", ".github/workflows/other.yml", "other"))
    else:  # timeout
        items = [run(i, sha, "queued", None) for i in range(2)]
    return {"total_count": len(items), "workflow_runs": items}


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify618-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-618 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)&per_page=100", args[1])
    j = re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)/jobs\?per_page=100", args[1])
    if m:
        print(json.dumps(runs(m.group(1))))
    elif j:
        i = int(j.group(1)) - 46000000000
        bad = scenario == "failure" and i == 3
        jobs = [{"id": 47000000000 + i * 10 + k, "name": name, "status": "completed",
                 "conclusion": "failure" if bad else "success",
                 "html_url": f"https://github.com/{REPO}/actions/runs/{j.group(1)}/job/{47000000000 + i * 10 + k}"}
                for k, name in enumerate(JOBS[i] if i < 4 else ["other"])]
        print(json.dumps({"total_count": len(jobs), "jobs": jobs}))
    else:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print(f"windows-adoption\tBuild desktop and check Windows native settings\t2026-11-25T00:00:00Z ERROR: stand-in failed log for run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
