"""Task 649 rehearsal stand-in for gh: 632's fakegh.py (by reference, unchanged) plus the dsh-windows-probe job.

Called as: python -I fakegh649.py <state-dir> <gh arguments...>. Never contacts GitHub. Everything goes to
verify-632/rehearsal/fakegh.py (scenarios, state files and the windows-tests artifact: see there), with its branch
name agent/632-graftling-windows-ci replaced by agent/649-graftling-windows-dsh, except:
  - the jobs response gains the dsh-windows-probe job, its steps as the workflow names them;
  - `run download -n graftling-dsh-probe-<sha>-<attempt>` writes a fabricated probe artifact (findings.json,
    findings.txt, logs/<probe>.txt, tests/files.json with logs, tests/run-exit-code.txt).
<state-dir>/probe chooses the probe case (default complete):
  complete    every probe recorded; DSH installs, starts, serves session/list and ends with its owner. Step PASS.
  negative    every probe recorded; DSH does not run on Windows (install and the CLI fail; the service never starts);
              the DSH test files skip. The findings are evidence only: PASS.
  incomplete  the probe script failed while recording (exit 2): its step failed and owner-death is absent. FAIL.
  missing     the upload failed and no probe artifact exists. FAIL.
"""
import json
import subprocess
import sys
from pathlib import Path

FAKEGH = Path(__file__).resolve().parents[2] / "verify-632" / "rehearsal" / "fakegh.py"
state = Path(sys.argv[1])
args = sys.argv[2:]
case = (state / "probe").read_text().strip() if (state / "probe").exists() else "complete"
RUN_ID = 51000000000
JOB = "dsh-windows-probe"
STEPS = ["Keep symbolic links on this runner", "Check out the commit under test", "Set up Node 24.22.3 x64",
         "Set up Python 3.13.7 x64", "Install graftling and pinned test tools", "Probe DSH on this runner",
         "Run graftling's DSH test files against the installed DSH", "Retain the DSH probe results"]
PROBES = ["runner", "registry", "install", "package", "cli-version", "cli-node", "cli-help", "cli-web-help",
          "preflight", "web-raw", "service", "owner-death"]
TEST_FILES = ["tests/test_dsh_live.py", "tests/test_dsh_mcp.py", "tests/test_dsh_standalone_child.py",
              "tests/test_dsh_providers_608.py", "tests/test_pi_dsh_child_tools_551.py",
              "tests/test_pi_dsh_owner_tools_no_ask_551.py"]


def attempt(rid: int) -> int:
    path = state / "attempt"
    return max(1, int(path.read_text()) if path.exists() else 0) if rid == RUN_ID else 1


def passthrough() -> None:
    done = subprocess.run([sys.executable, "-I", str(FAKEGH), *sys.argv[1:]], capture_output=True, text=True)
    out = done.stdout.replace("agent/632-graftling-windows-ci", "agent/649-graftling-windows-dsh")
    if done.returncode == 0 and args[:1] == ["api"] and "/jobs?per_page=100" in args[-1]:
        data = json.loads(out)
        rid = int(args[-1].split("/runs/")[1].split("/")[0])
        names = ["Set up job", *STEPS, "Post Set up Python 3.13.7 x64", "Post Set up Node 24.22.3 x64",
                 "Post Check out the commit under test", "Complete job"]
        steps = []
        for number, name in enumerate(names, 1):
            conclusion = "success"
            if case == "incomplete" and name == STEPS[5]:
                conclusion = "failure"
            elif case == "missing" and name == STEPS[7]:
                conclusion = "failure"
            elif case in ("incomplete", "missing") and name.startswith("Post Set up"):
                conclusion = "skipped"
            steps.append({"name": name, "status": "completed", "conclusion": conclusion, "number": number})
        failed = any(s["conclusion"] == "failure" for s in steps)
        data["jobs"].append({"id": 53000000000 + rid % 100, "name": JOB, "status": "completed",
                             "conclusion": "failure" if failed else "success",
                             "html_url": f"https://github.com/LUOXIAO92/graftling/actions/runs/{rid}/job/53000000000",
                             "steps": steps})
        data["total_count"] = len(data["jobs"])
        out = json.dumps(data)
    sys.stdout.write(out)
    sys.stderr.write(done.stderr)
    sys.exit(done.returncode)


def record(probe: str, exit, facts: dict, excerpt: list[str]) -> dict:
    return {"probe": probe, "title": f"rehearsal {probe}", "argv": [], "exit": exit, "timed_out": False,
            "seconds": 1.0, "log": f"logs\\{probe}.txt", "excerpt": excerpt, "facts": facts}


def probe_artifact(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "logs").mkdir(exist_ok=True)
    good = case != "negative"
    records = []
    for probe in PROBES:
        if case == "incomplete" and probe == "owner-death":
            break
        if good:
            facts = {"install": {}, "service": {"start": "ok in 6.1 s", "cookie_received": True,
                                                "session_list": "ok: 0 sessions", "close": "ok in 0.2 s",
                                                "alive_15s_after_close": []},
                     "owner-death": {"alive_before_kill": [4100, 4120], "owner_exit_code": 1,
                                     "alive_15s_after_owner_killed": []},
                     "web-raw": {"launch_url_seen": True, "port": "50123", "alive_15s_after_job_handle_closed": []},
                     "preflight": {"derived_exists": False, "refusal_at_derived":
                                   "DSH 0.2.0-rc.2 or later is required (installed unknown)."}}.get(probe, {})
            records.append(record(probe, 0, facts, [f"{probe}: rehearsal output"]))
        else:
            exit = 0 if probe in ("runner", "registry") else (1 if probe in ("install", "cli-version", "cli-node", "cli-help",
                                                                             "cli-web-help", "web-raw", "service",
                                                                             "owner-death") else "FileNotFoundError : x")
            records.append(record(probe, exit, {}, [f"{probe}: rehearsal failure"]))
        (directory / "logs" / f"{probe}.txt").write_text(f"{probe} rehearsal log\n", encoding="utf-8")
    (directory / "findings.json").write_text(json.dumps({
        "dsh_version": "0.2.2-rc.5", "platform": "win32", "removed_variable_names": ["GITHUB_TOKEN"],
        "probes": records, "expected_probes": PROBES, "complete": len(records) == len(PROBES)}), encoding="utf-8")
    (directory / "findings.txt").write_text("rehearsal\n", encoding="utf-8")
    if case == "incomplete":
        return   # the probe step failed; the test files step still ran, but this case shows the probe failure alone
    tests = directory / "tests"
    (tests / "logs").mkdir(parents=True, exist_ok=True)
    files = []
    for name in TEST_FILES:
        stem = Path(name).stem
        reason = "DSH 0.2.0-rc.2 or later is required (installed unknown)." if good else "Installed DSH and Node are required."
        (tests / "logs" / f"{stem}.txt").write_text(
            f"{name}::test_x SKIPPED\n=========================== short test summary info ============================\n"
            f"SKIPPED [2] {name}:10: {reason}\n============================== 2 skipped in 0.50s ==============================\n",
            encoding="utf-8")
        files.append({"file": name, "log": f"logs\\{stem}.txt", "outcome": "ended", "exit_code": 0,
                      "junit": f"junit\\{stem}.xml", "elapsed_s": 1.0})
    (tests / "files.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    (tests / "run-exit-code.txt").write_text("0\n", encoding="ascii")


if args[:2] == ["run", "download"] and args[args.index("-n") + 1].startswith("graftling-dsh-probe-"):
    rid, name, target = int(args[2]), args[args.index("-n") + 1], Path(args[args.index("-D") + 1])
    sha = (state / "sha").read_text().strip() if (state / "sha").exists() else "0" * 40
    want = f"graftling-dsh-probe-{sha}-{attempt(rid)}"
    if case == "missing" or name != want:
        print(f"no artifact matches any of the names or patterns provided ({name}; have "
              f"{'none' if case == 'missing' else want})", file=sys.stderr)
        sys.exit(1)
    probe_artifact(target)
    sys.exit(0)
passthrough()
