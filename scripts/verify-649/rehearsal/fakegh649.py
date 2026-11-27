"""Task 649 rehearsal stand-in for gh: 632's fakegh.py (by reference, unchanged) plus the dsh-windows-tests job.

Called as: python -I fakegh649.py <state-dir> <gh arguments...>. Never contacts GitHub. Everything goes to
verify-632/rehearsal/fakegh.py (scenarios, state files and the windows-tests artifact: see there), with its branch
name agent/632-graftling-windows-ci replaced by agent/649-graftling-windows-dsh, except:
  - the jobs response gains the dsh-windows-tests job, its steps as the workflow names them;
  - `run download -n graftling-dsh-windows-<sha>-<attempt>` writes the DSH job's artifact as the workflow leaves it:
    .github/run_test_files.py's layout (files.json, junit/<stem>.xml, logs/<stem>.txt, run-exit-code.txt) for every
    tests/test_*dsh*.py of `junit` (the candidate's macOS run with simulated Windows skips), plus environment.json
    and npm-install.txt from the install step.
<state-dir>/dsh chooses the DSH case (default pass):
  pass          every DSH test passed or skipped as listed; the install took 1074 s with no cache hit. PASS.
  fail          one must-pass test (the owner-death test) fails; the test step failed. FAIL.
  skip          the installed-DSH tests of test_dsh_windows_649 skip 'Installed DSH and Node are required.' (graftling
                refused or did not find DSH): an unlisted skip, and must-pass tests skipped. FAIL.
  install-fail  npm install failed: the install step failed, the test step was skipped; the artifact holds only
                environment.json and npm-install.txt. FAIL.
  missing       the upload failed and no DSH artifact exists. FAIL.
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FAKEGH = Path(__file__).resolve().parents[2] / "verify-632" / "rehearsal" / "fakegh.py"
state = Path(sys.argv[1])
args = sys.argv[2:]
case = (state / "dsh").read_text().strip() if (state / "dsh").exists() else "pass"
RUN_ID = 51000000000
JOB = "dsh-windows-tests"
STEPS = ["Keep symbolic links on this runner", "Check out the commit under test", "Set up Node 24.22.3 x64",
         "Set up Python 3.13.7 x64", "Install graftling and pinned test tools", "Restore the npm download cache",
         "Install DSH with npm", "Run graftling's DSH test files against the installed DSH",
         "Retain the DSH test results"]
OWNER_DEATH = "test_installed_dsh_service_ends_when_its_owner_dies_without_close"
INSTALLED_649 = ("test_installed_dsh_is_found_through_its_npm_shim",
                 "test_installed_dsh_service_starts_lists_and_leaves_nothing_after_close", OWNER_DEATH)


def attempt(rid: int) -> int:
    path = state / "attempt"
    return max(1, int(path.read_text()) if path.exists() else 0) if rid == RUN_ID else 1


def conclusion(name: str) -> str:
    if case == "install-fail":
        return {"Install DSH with npm": "failure", STEPS[7]: "skipped"}.get(name, "success")
    if case == "fail" and name == STEPS[7]:
        return "failure"
    if case == "missing" and name == STEPS[8]:
        return "failure"
    return "success"


def passthrough() -> None:
    done = subprocess.run([sys.executable, "-I", str(FAKEGH), *sys.argv[1:]], capture_output=True, text=True)
    out = done.stdout.replace("agent/632-graftling-windows-ci", "agent/649-graftling-windows-dsh")
    if done.returncode == 0 and args[:1] == ["api"] and "/jobs?per_page=100" in args[-1]:
        data = json.loads(out)
        rid = int(args[-1].split("/runs/")[1].split("/")[0])
        names = ["Set up job", *STEPS, "Post Restore the npm download cache", "Post Set up Python 3.13.7 x64",
                 "Post Set up Node 24.22.3 x64", "Post Check out the commit under test", "Complete job"]
        steps = [{"name": name, "status": "completed", "number": number,
                  "conclusion": "skipped" if name.startswith("Post Set up") and case != "pass" else conclusion(name)}
                 for number, name in enumerate(names, 1)]
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


def dsh_artifact(directory: Path, sha: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    ok = case != "install-fail"
    (directory / "npm-install.txt").write_text(
        "> node-pty@1.2.0-beta.15 install\n> node scripts/prebuild.js || node-gyp rebuild\n\n"
        + ("added 670 packages in 18m\n" if ok else "npm error code EINTEGRITY\nnpm error rehearsal: install failed\n"),
        encoding="utf-8")
    (directory / "environment.json").write_text("\ufeff" + json.dumps({
        "commit": sha, "os": "Microsoft Windows NT 10.0.26100.0", "image": "win25", "image_version": "20261123.1",
        "arch": "AMD64", "python": "Python 3.13.7", "pytest": "pytest 8.3.5", "node": "v24.22.3", "npm": "11.19.1",
        "codepage": 1252, "dsh_requested": "0.2.2-rc.5", "npm_exit": 0 if ok else 1, "install_seconds": 1074,
        "npm_cache_hit": "", "npm_cache": "C:\\Users\\runneradmin\\AppData\\Local\\npm-cache",
        "npm_prefix": "C:\\npm\\prefix", "dsh": "C:\\npm\\prefix\\dsh.cmd" if ok else None,
        "dsh_version": "0.2.2-rc.5" if ok else "not run: the install failed"}), encoding="utf-8")
    if not ok:
        return
    tree = ET.parse(state / "junit")
    by_file: dict[str, list] = {}
    for item in tree.getroot().iter("testcase"):
        file = item.get("file", "").replace("\\", "/")
        if re.fullmatch(r"tests/test_[^/]*dsh[^/]*\.py", file):
            for child in [c for c in item if c.tag in ("failure", "error")]:
                item.remove(child)
            if case == "fail" and item.get("name") == OWNER_DEATH:
                ET.SubElement(item, "failure", {"message": "AssertionError: assert [4100] == []"}).text = \
                    "tests\\test_dsh_windows_649.py:160: AssertionError: a DSH process outlived its owner"
            if case == "skip" and item.get("name") in INSTALLED_649:
                for child in list(item):
                    item.remove(child)
                ET.SubElement(item, "skipped", {"type": "pytest.skip",
                                                "message": "Installed DSH and Node are required."}).text = "x"
            by_file.setdefault(file, []).append(item)
    for part in ("junit", "logs"):
        (directory / part).mkdir(exist_ok=True)
    records = []
    for file in sorted(by_file):
        stem = Path(file).stem
        members = by_file[file]
        code = 1 if any(m.find("failure") is not None for m in members) else 0
        suite = ET.Element("testsuite", {"name": "pytest", "tests": str(len(members))})
        for m in members:
            m.set("file", file.replace("/", "\\"))   # as the Windows runner writes it
        suite.extend(members)
        out = ET.ElementTree(ET.Element("testsuites"))
        out.getroot().append(suite)
        out.write(directory / "junit" / f"{stem}.xml", encoding="utf-8", xml_declaration=True)
        (directory / "logs" / f"{stem}.txt").write_text(
            "\n".join(f"{file}::{m.get('name')} {'FAILED' if m.find('failure') is not None else 'PASSED'}"
                      for m in members) + "\n", encoding="utf-8")
        records.append({"file": file, "log": f"logs\\{stem}.txt", "outcome": "ended", "pipe_closed": True,
                        "elapsed_s": 3.0, "junit": f"junit\\{stem}.xml", "exit_code": code})
    (directory / "files.json").write_text(json.dumps({"file_limit_s": 300.0, "total_limit_s": 1200.0,
                                                      "files": records}))
    (directory / "run-exit-code.txt").write_text("1\n" if case == "fail" else "0\n")


if args[:2] == ["run", "download"] and args[args.index("-n") + 1].startswith("graftling-dsh-windows-"):
    rid, name, target = int(args[2]), args[args.index("-n") + 1], Path(args[args.index("-D") + 1])
    sha = (state / "sha").read_text().strip() if (state / "sha").exists() else "0" * 40
    want = f"graftling-dsh-windows-{sha}-{attempt(rid)}"
    if case == "missing" or name != want:
        print(f"no artifact matches any of the names or patterns provided ({name}; have "
              f"{'none' if case == 'missing' else want})", file=sys.stderr)
        sys.exit(1)
    dsh_artifact(target, sha)
    sys.exit(0)
passthrough()
