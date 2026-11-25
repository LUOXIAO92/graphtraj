"""Task 619 rehearsal stand-in for gh: canned REST JSON shaped like GitHub's actions responses.

Called as: python fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case and
<state-dir>/gsha holds the candidate graftling SHA the job log names:
  success       the run appears on the 2nd poll and completes on the 3rd; every counted step succeeds,
                the UI step fails (pre-D UI), so the run concludes failure; expected verdict PASS.
  counted-fail  'Build desktop and check Windows native settings' fails, later steps are skipped; FAIL.
  missing       'Install archive to persistent user directory' is absent from the step list; FAIL.
  timeout       only another workflow ever runs for the SHA; appearance timeout, FAIL.
Never contacts GitHub.
"""
import json
import re
import sys
from pathlib import Path

state    = Path(sys.argv[1])
args     = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
gsha     = (state / "gsha").read_text().strip()
REPO     = "LUOXIAO92/graphtraj"
PATH     = ".github/workflows/desktop-win-adoption.yml"
RUN_ID   = 46100000000
JOB_ID   = 47100000000
STEPS    = [
    "Set up job",
    "Run actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "Keep graftling's symbolic links on this runner",
    "Check out graftling at the version GraphTraj declares",
    "Fail unless graftling's linked package documents are real",
    "Run actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
    "Run actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
    "Confirm native desktop session",
    "Install pinned build dependencies",
    "Build desktop and check Windows native settings",
    "Package pinned runtime and application",
    "Install archive to persistent user directory",
    "Exercise actual installed window and native dialogs",
    "Retain installation artifact",
    "Retain exact checks and native UI evidence",
    "Post Run actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
    "Post Run actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "Complete job",
]
UI = "Exercise actual installed window and native dialogs"


def steps() -> list[dict]:
    """Return the job's step list for this scenario."""
    names, failed = list(STEPS), None
    if scenario == "missing":
        names.remove("Install archive to persistent user directory")
    failed = "Build desktop and check Windows native settings" if scenario == "counted-fail" else UI
    result, after = [], False
    for number, name in enumerate(names, 1):
        if name == failed:
            conclusion, after = "failure", True
        elif after and not name.startswith(("Retain", "Post", "Complete")):
            conclusion = "skipped"
        else:
            conclusion = "success"
        result.append({"name": name, "status": "completed", "conclusion": conclusion, "number": number})
    return result


def run(sha: str, status: str, conclusion: str | None) -> dict:
    """One workflow run record."""
    return {"id": RUN_ID, "name": "Windows desktop adoption 266", "path": PATH,
            "head_branch": "agent/619-graftling-windows-import", "head_sha": sha, "event": "push",
            "status": status, "conclusion": conclusion, "run_attempt": 1,
            "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}"}


def runs(sha: str) -> dict:
    """The runs response for this poll; the poll counter lives in the state directory."""
    counter = state / "polls"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    other = {**run(sha, "completed", "success"), "id": RUN_ID + 9, "path": ".github/workflows/other.yml", "name": "other"}
    if scenario == "timeout":
        items = [other]
    elif n == 1:
        items = []
    elif n == 2:
        items = [run(sha, "in_progress", None)]
    else:
        items = [run(sha, "completed", "failure")]
    return {"total_count": len(items), "workflow_runs": items}


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify619-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-619 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)&per_page=100", args[1])
    if m:
        print(json.dumps(runs(m.group(1))))
    elif args[1] == f"repos/{REPO}/actions/runs/{RUN_ID}/jobs?per_page=100":
        job = {"id": JOB_ID, "name": "windows-adoption", "status": "completed", "conclusion": "failure",
               "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}/job/{JOB_ID}", "steps": steps()}
        print(json.dumps({"total_count": 1, "jobs": [job]}))
    elif args[1] == f"repos/{REPO}/actions/jobs/{JOB_ID}/logs":
        print(f"2026-11-25T00:00:00Z [command]\"C:\\Program Files\\Git\\bin\\git.exe\" checkout --progress --force {gsha}")
        print(f"2026-11-25T00:00:01Z HEAD is now at {gsha[:7]} Windows: import graftling")
    else:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print(f"windows-adoption\tstand-in failed step\t2026-11-25T00:00:00Z ERROR: stand-in failed log for run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
