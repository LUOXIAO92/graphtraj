"""Task 621 rehearsal stand-in for gh: canned REST JSON shaped like GitHub's responses. Never contacts GitHub.

Called as: python -I fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case:
success (the dispatched run appears on the 2nd listing, completes with success on the 2nd query), failure (it
completes with failure), timeout (the dispatched run never appears). <state-dir>/remote is the bare remote whose
branch head becomes the dispatched run's head_sha; <state-dir>/wf-main.yml is the default branch's workflow text.
"""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graphtraj"
WF = "desktop-macos-adoption.yml"
BRANCH = "agent/621-macos-adoption-script-d-ui"
FAILED = "45546698537"
ARTIFACT = "graphtraj-macos-adoption-evidence"
NEW_ID = 46100000002
OLD = {"id": 46100000001, "head_sha": "0" * 40, "status": "completed", "conclusion": "failure", "event": "workflow_dispatch",
       "html_url": f"https://github.com/{REPO}/actions/runs/46100000001"}


def count(name):
    file = state / name
    n = int(file.read_text()) + 1 if file.exists() else 1
    file.write_text(str(n))
    return n


def head():
    return subprocess.run(["git", "--git-dir", (state / "remote").read_text().strip(), "rev-parse", f"refs/heads/{BRANCH}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def new_run(status, conclusion):
    return {"id": NEW_ID, "head_sha": head(), "status": status, "conclusion": conclusion, "event": "workflow_dispatch",
            "head_branch": BRANCH, "html_url": f"https://github.com/{REPO}/actions/runs/{NEW_ID}"}


PUSH = [(".github/workflows/desktop-macos-adoption.yml", "desktop-macos-adoption", "Installed macOS artifact and adoption"),
        (".github/workflows/desktop-linux-adoption.yml", "Linux installed desktop adoption", "installed-desktop")]
PUSH_BASE = 46200000000


def push_run(i, sha, status, conclusion):
    path, name, _ = PUSH[i]
    rid = PUSH_BASE + i
    return {"id": rid, "name": name, "path": path, "head_sha": sha, "event": "push", "status": status,
            "conclusion": conclusion, "run_attempt": 1, "head_branch": BRANCH,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def push_runs(sha):
    """push-success: both appear on the 2nd poll, complete on the 3rd; push-fail: Linux fails;
    push-timeout: only the macOS run ever appears."""
    n = count("push-polls")
    if scenario == "push-timeout":
        return [push_run(0, sha, "queued", None)]
    if n == 1:
        return []
    done = n >= 3
    runs = [push_run(i, sha, "completed" if done else "in_progress",
                     (("failure" if scenario == "push-fail" and i == 1 else "success") if done else None)) for i in range(2)]
    if scenario == "push-fail":
        runs.append({"id": 46200000009, "name": "other", "path": ".github/workflows/other.yml", "head_sha": sha,
                     "event": "push", "status": "completed", "conclusion": "success",
                     "html_url": f"https://github.com/{REPO}/actions/runs/46200000009"})
    return runs


def api(endpoint):
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)&per_page=100", endpoint)
    if m:
        runs = push_runs(m.group(1))
        return {"total_count": len(runs), "workflow_runs": runs}
    j = re.fullmatch(rf"repos/{REPO}/actions/runs/(46200000000|46200000001)/jobs\?per_page=100", endpoint)
    if j:
        i = int(j.group(1)) - PUSH_BASE
        bad = scenario == "push-fail" and i == 1
        steps = [{"number": 1, "name": "Set up job", "status": "completed", "conclusion": "success"},
                 {"number": 9, "name": "Exercise the installed desktop under Xvfb" if i else "Installed app adoption, optionality and security",
                  "status": "completed", "conclusion": "failure" if bad else "success"}]
        return {"total_count": 1, "jobs": [{"id": 2, "name": PUSH[i][2], "status": "completed",
                                            "conclusion": "failure" if bad else "success", "steps": steps,
                                            "html_url": f"https://github.com/{REPO}/actions/runs/{j.group(1)}/job/2"}]}
    if endpoint == f"repos/{REPO}":
        return {"full_name": REPO, "default_branch": "main"}
    if endpoint == f"repos/{REPO}/contents/.github/workflows/{WF}?ref=main":
        return {"name": WF, "encoding": "base64", "content": base64.b64encode((state / "wf-main.yml").read_bytes()).decode()}
    if endpoint == f"repos/{REPO}/actions/workflows/{WF}":
        return {"id": 1, "name": "desktop-macos-adoption", "path": f".github/workflows/{WF}", "state": "active"}
    if endpoint == f"repos/{REPO}/actions/runs/{FAILED}/artifacts":
        return {"total_count": 2, "artifacts": [
            {"id": 1, "name": ARTIFACT, "size_in_bytes": 812345, "expired": False, "expires_at": "2027-02-23T00:00:00Z"},
            {"id": 2, "name": "graphtraj-macos-app", "size_in_bytes": 123456789, "expired": False, "expires_at": "2026-12-02T00:00:00Z"}]}
    if endpoint == f"repos/{REPO}/actions/workflows/{WF}/runs?branch={BRANCH}&event=workflow_dispatch&per_page=30":
        runs = [OLD]
        if (state / "dispatched").exists() and scenario != "timeout" and count("listings") >= 2:
            runs.insert(0, new_run("queued", None))
        return {"total_count": len(runs), "workflow_runs": runs}
    if endpoint == f"repos/{REPO}/actions/runs/{NEW_ID}":
        if count("queries") < 2:
            return new_run("in_progress", None)
        return new_run("completed", "failure" if scenario == "failure" else "success")
    if endpoint == f"repos/{REPO}/actions/runs/{NEW_ID}/jobs?per_page=100":
        bad = scenario == "failure"
        steps = [{"number": 1, "name": "Set up job", "status": "completed", "conclusion": "success"},
                 {"number": 18, "name": "Installed app adoption, optionality and security", "status": "completed",
                  "conclusion": "failure" if bad else "success"},
                 {"number": 21, "name": "Installed focused activity adoption", "status": "completed", "conclusion": "skipped"}]
        return {"total_count": 1, "jobs": [{"id": 1, "name": "Installed macOS artifact and adoption", "status": "completed",
                                            "conclusion": "failure" if bad else "success", "steps": steps,
                                            "html_url": f"https://github.com/{REPO}/actions/runs/{NEW_ID}/job/1"}]}
    return None


def download(run_id, dest, name=ARTIFACT):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    if name.startswith("linux-desktop-"):
        passed = scenario != "push-fail"
        ui = {"uiPassed": passed, "stage": "controlled Dashboard", "steps": ["stand-in linux step 1", "stand-in linux step 2"]}
        if not passed:
            ui["failure"] = "Error: stand-in Linux failure\n    at adoption-linux.mjs"
        (out / "evidence").mkdir(exist_ok=True)
        (out / "evidence" / "ui-result.json").write_text(json.dumps(ui, indent=2) + "\n")
        (out / "evidence" / "result.json").write_text(json.dumps({"passed": passed, "steps": []}, indent=2) + "\n")
        return
    (out / "screens").mkdir(exist_ok=True)
    passed = not (run_id == FAILED or scenario == "failure")
    facts = {"passed": passed, "steps": [f"stand-in step {i}" for i in range(1, 9)],
             "screenshots": ["screens/00-start.png"] + ([] if passed else ["screens/failure.png"])}
    if not passed:
        facts["failure"] = "TimeoutError: locator.waitFor: Timeout 30000ms exceeded.\n  waiting for getByRole('button', { name: 'Add project' })"
    (out / "evidence.json").write_text(json.dumps(facts, indent=2) + "\n")
    for name in facts["screenshots"]:
        (out / name).write_bytes(b"\x89PNG stand-in")
    (out / "environment.txt").write_text("stand-in environment\n")


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify621-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-621 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    doc = api(args[1])
    if doc is None:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(doc))
elif args[:2] == ["workflow", "run"]:
    expected = [WF, "--repo", REPO, "--ref", BRANCH, "-f", "mode=standard"]
    if args[2:] != expected:
        print("fake gh: unexpected workflow run arguments " + " ".join(args[2:]), file=sys.stderr)
        sys.exit(2)
    (state / "dispatched").write_text("1")
    print(f"✓ Created workflow_dispatch event for {WF} at {BRANCH}")
elif args[:2] == ["run", "download"]:
    m = re.fullmatch(r"(\d+) --repo " + re.escape(REPO) + r" -n (graphtraj-macos-adoption-evidence|linux-desktop-[0-9a-f]{40}) -D (\S+)",
                     " ".join(args[2:]))
    if not m:
        print("fake gh: unexpected run download arguments " + " ".join(args[2:]), file=sys.stderr)
        sys.exit(2)
    download(m.group(1), m.group(3), m.group(2))
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print(f"Installed macOS artifact and adoption\tInstalled app adoption, optionality and security\t"
          f"2026-11-25T00:00:00Z TimeoutError: stand-in failed log for run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
