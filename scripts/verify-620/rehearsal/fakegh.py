"""Task 620 rehearsal stand-in for gh: canned output shaped like GitHub's actions responses. Never contacts GitHub.

Called as: python fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case:
success (the Linux run appears on the 2nd poll, completes on the 3rd), failure (the Linux run fails; one other
workflow also runs for the SHA), timeout (the Linux run never appears). `run view 45546698887 --log` returns a
log tail shaped like the 618 failure; `run view <id> --log` returns a short log for any other run.
"""
import json
import re
import sys
from pathlib import Path

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graphtraj"
PATH = ".github/workflows/desktop-linux-adoption.yml"
BASE = 46100000000


def run(i, sha, status, conclusion, path=PATH, name="Linux installed desktop adoption"):
    rid = BASE + i
    return {"id": rid, "name": name, "path": path, "head_branch": "agent/620-linux-adoption-codex-fixture",
            "head_sha": sha, "event": "push", "status": status, "conclusion": conclusion, "run_attempt": 1,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def runs(sha):
    counter = state / "polls"
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    if scenario == "success":
        items = [] if n == 1 else [run(0, sha, "in_progress" if n == 2 else "completed", None if n == 2 else "success")]
    elif scenario == "failure":
        items = [run(0, sha, "completed" if n >= 2 else "queued", "failure" if n >= 2 else None),
                 run(9, sha, "completed", "success", ".github/workflows/other.yml", "other")]
    else:  # timeout
        items = []
    return {"total_count": len(items), "workflow_runs": items}


OLD_LOG = """installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:00Z launched member observer
installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:01Z Traceback (most recent call last):
installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:01Z   File "/home/runner/work/graphtraj/graphtraj/tests/linux_adoption_runtime.py", line 50, in main
installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:01Z FileNotFoundError: [Errno 2] No such file or directory: '/home/runner/.codex/sessions/fake/rollout-0000.jsonl'
installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:01Z turn/completed failed: scenario failed
installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T05:01:31Z TimeoutError: timed out (tests/linux_adoption_input.py:88)
"""

if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify620-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-620 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)&per_page=100", args[1])
    j = re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)/jobs\?per_page=100", args[1])
    if m:
        print(json.dumps(runs(m.group(1))))
    elif j:
        i = int(j.group(1)) - BASE
        bad = scenario == "failure" and i == 0
        print(json.dumps({"total_count": 1, "jobs": [{
            "id": 47100000000 + i, "name": "installed-desktop" if i == 0 else "other", "status": "completed",
            "conclusion": "failure" if bad else "success",
            "html_url": f"https://github.com/{REPO}/actions/runs/{j.group(1)}/job/{47100000000 + i}"}]}))
    else:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print(f"installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T00:00:00Z ERROR: stand-in failed log for run {args[2]}")
elif args[:2] == ["run", "view"] and "--log" in args:
    if args[2] == "45546698887":
        print(("installed-desktop\tBuild\t2026-11-25T05:00:00Z filler line\n" * 50) + OLD_LOG, end="")
    else:
        print(f"installed-desktop\tExercise the installed desktop under Xvfb\t2026-11-25T00:00:00Z stand-in full log for run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
