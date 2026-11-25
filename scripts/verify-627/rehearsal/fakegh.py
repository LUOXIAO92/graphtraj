"""Task 627 rehearsal stand-in for gh (copied from verify-623, repair run removed: 627 triggers Windows, macOS
and Linux only): canned REST JSON shaped like GitHub's responses. Never contacts GitHub.

Called as: python -I fakegh.py <state-dir> <gh arguments...>. <state-dir>/scenario names the case:
  push-success  the three push runs appear on the 2nd listing and complete with success on the 3rd
  push-fail     as push-success, but the Windows run fails (plus one OTHER workflow); after `run rerun --failed`
                of the Windows run, attempt 2 appears on the 2nd run query and succeeds on the 3rd
  push-timeout  only the Windows run ever appears
  push-slow     the four runs appear and never complete
  tag-wrong     graftling's v0.10.2 tag resolves to another commit
"""
import json
import re
import sys
from pathlib import Path

state = Path(sys.argv[1])
args = sys.argv[2:]
scenario = (state / "scenario").read_text().strip()
REPO = "LUOXIAO92/graphtraj"
GREPO = "LUOXIAO92/graftling"
BRANCH = "agent/627-desktop-ui-structure-redesign"
GCOMMIT = "57bca73657d3135a4504904fcc3f1898c2419766"
TAGOBJ = "a5ac59d0b04682f56807b8d6a7e3644bd6d2ba4e"
PUSH = [(".github/workflows/desktop-win-adoption.yml", "Windows desktop adoption 266", "windows-adoption",
         "Exercise actual installed window and native dialogs"),
        (".github/workflows/desktop-macos-adoption.yml", "desktop-macos-adoption", "Installed macOS artifact and adoption",
         "Installed app adoption, optionality and security"),
        (".github/workflows/desktop-linux-adoption.yml", "Linux installed desktop adoption", "installed-desktop",
         "Exercise the installed desktop under Xvfb")]
PUSH_BASE = 46300000000
WIN = PUSH_BASE


def count(name):
    file = state / name
    n = int(file.read_text()) + 1 if file.exists() else 1
    file.write_text(str(n))
    return n


def sha_file():
    file = state / "sha"
    return file.read_text().strip() if file.exists() else "0" * 40


def win_rerun():
    """(attempt, status, conclusion) of the Windows run after a re-run was requested."""
    n = count("rerun-queries")
    if n == 1:
        return 1, "completed", "failure"  # the API still shows the old attempt right after the request
    if n == 2:
        return 2, "in_progress", None
    return 2, "completed", "success"


def push_run(i, sha, status, conclusion, attempt=1):
    path, name, _, _ = PUSH[i]
    rid = PUSH_BASE + i
    return {"id": rid, "name": name, "path": path, "head_sha": sha, "event": "push", "status": status,
            "conclusion": conclusion, "run_attempt": attempt, "head_branch": BRANCH,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def push_runs(sha):
    (state / "sha").write_text(sha)
    n = count("push-polls")
    if scenario == "push-timeout":
        return [push_run(0, sha, "queued", None)]
    if n == 1:
        return []
    done = n >= 3 and scenario != "push-slow"
    runs = [push_run(i, sha, "completed" if done else "in_progress",
                     (("failure" if scenario == "push-fail" and i == 0 else "success") if done else None))
            for i in range(len(PUSH))]
    if scenario == "push-fail":
        runs.append({"id": 46300000009, "name": "other", "path": ".github/workflows/other.yml", "head_sha": sha,
                     "event": "push", "status": "completed", "conclusion": "success",
                     "html_url": f"https://github.com/{REPO}/actions/runs/46300000009"})
    return runs


def one_run(i):
    sha = sha_file()
    if scenario == "push-fail" and i == 0:
        if (state / "rerun").exists():
            attempt, status, conclusion = win_rerun()
            return push_run(0, sha, status, conclusion, attempt)
        return push_run(0, sha, "completed", "failure")
    return push_run(i, sha, "completed", "success")


def win_failed():
    if scenario != "push-fail":
        return False
    return not ((state / "rerun").exists() and int((state / "rerun-queries").read_text()) >= 3)


def api(endpoint):
    m = re.fullmatch(rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]+)&per_page=100", endpoint)
    if m:
        runs = push_runs(m.group(1))
        return {"total_count": len(runs), "workflow_runs": runs}
    m = re.fullmatch(rf"repos/{REPO}/actions/runs/({PUSH_BASE}|{PUSH_BASE + 1}|{PUSH_BASE + 2})", endpoint)
    if m:
        return one_run(int(m.group(1)) - PUSH_BASE)
    j = re.fullmatch(rf"repos/{REPO}/actions/runs/(\d+)/jobs\?per_page=100", endpoint)
    if j and PUSH_BASE <= int(j.group(1)) < PUSH_BASE + len(PUSH):
        i = int(j.group(1)) - PUSH_BASE
        bad = i == 0 and win_failed()
        steps = [{"number": 1, "name": "Set up job", "status": "completed", "conclusion": "success"},
                 {"number": 12, "name": PUSH[i][3], "status": "completed", "conclusion": "failure" if bad else "success"}]
        jobs = [{"id": 2, "name": PUSH[i][2], "status": "completed", "conclusion": "failure" if bad else "success",
                 "steps": steps, "html_url": f"https://github.com/{REPO}/actions/runs/{j.group(1)}/job/2"}]
        return {"total_count": len(jobs), "jobs": jobs}
    if endpoint == f"repos/{GREPO}/git/ref/tags/v0.10.2":
        return {"ref": "refs/tags/v0.10.2", "object": {"type": "tag", "sha": TAGOBJ}}
    if endpoint == f"repos/{GREPO}/git/tags/{TAGOBJ}":
        target = "6166718" + "0" * 33 if scenario == "tag-wrong" else GCOMMIT
        return {"tag": "v0.10.2", "sha": TAGOBJ, "object": {"type": "commit", "sha": target}}
    return None


def download(run_id, dest, name):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    i = int(run_id) - PUSH_BASE
    if name.startswith("GraphTraj-windows-evidence-"):
        passed = not win_failed()
        facts = {"passed": passed, "phase": "finished", "steps": [f"stand-in windows step {k}" for k in range(1, 8)]}
        if not passed:
            facts["error"] = ("TimeoutError: locator.waitFor: Timeout 20000ms exceeded.\n"
                              "    at pick (adoption-win.mjs:260)")
        (out / "adoption.json").write_text(json.dumps(facts, indent=2) + "\n")
        (out / "environment.json").write_text("{}\n")
        (out / "native-1-pick.png").write_bytes(b"\x89PNG stand-in")
    elif name == "graphtraj-macos-adoption-evidence":
        (out / "evidence.json").write_text(json.dumps({"passed": True, "steps": ["stand-in mac step"]}, indent=2) + "\n")
    elif name.startswith("linux-desktop-"):
        (out / "evidence").mkdir(exist_ok=True)
        (out / "evidence" / "ui-result.json").write_text(json.dumps({"uiPassed": True, "steps": ["stand-in linux"]}) + "\n")
    elif name.startswith("GraphTraj-windows-x64-"):
        (out / "GraphTraj-windows-x64.zip").write_bytes(b"PK stand-in")
        (out / "GraphTraj-windows-x64.zip.sha256").write_text("0" * 64 + "\n")
    elif name.startswith("GraphTraj-linux-amd64-"):
        (out / "graphtraj_0.0.0_amd64.deb").write_bytes(b"!<arch> stand-in")
    else:
        print(f"fake gh: no artifact {name} in run {run_id} (workflow index {i})", file=sys.stderr)
        sys.exit(1)


if args[:1] == ["--version"]:
    print("gh version 0.0.0-verify627-stand-in")
elif args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in to github.com account stand-in-user (verify-627 fake)\n"
          "  - Active account: true\n  - Token: gho_************************************\n  - Token scopes: 'repo'")
elif args[:1] == ["api"]:
    doc = api(args[1])
    if doc is None:
        print(f"gh: Not Found (HTTP 404) {args[1]}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(doc))
elif args[:2] == ["run", "rerun"]:
    if args[2:] != [str(WIN), "--repo", REPO, "--failed"] or scenario != "push-fail":
        print("fake gh: unexpected run rerun " + " ".join(args[2:]), file=sys.stderr)
        sys.exit(2)
    (state / "rerun").write_text("1")
    print(f"✓ Requested rerun (failed jobs) of run {WIN}")
elif args[:2] == ["run", "download"]:
    m = re.fullmatch(r"(\d+) --repo " + re.escape(REPO) + r" -n (\S+) -D (\S+)", " ".join(args[2:]))
    if not m:
        print("fake gh: unexpected run download arguments " + " ".join(args[2:]), file=sys.stderr)
        sys.exit(2)
    download(m.group(1), m.group(3), m.group(2))
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print(f"windows-adoption\tExercise actual installed window and native dialogs\t"
          f"2026-11-25T00:00:00Z TimeoutError: stand-in failed log for run {args[2]}")
else:
    print("fake gh: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(2)
