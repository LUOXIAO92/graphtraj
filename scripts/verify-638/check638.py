"""Task 638 step helper, beside scripts/verify-632/wincheck.py (which judges jobs and JUnit results).

Run as: python -I check638.py <command> <args...>. Standard library only. Prints plain lines.
  wfdiff BASE HEAD BRANCH STEP...  HEAD (windows.yml at the bundle head) differs from BASE (at graftling dev 478dfd7f:
                                   632's accepted workflow with W1/W2's push branches) only by BRANCH appended to the push branches and the
                                   non-ASCII temporary directory lines added to the suite step; the step names are
                                   the same and include every STEP. Exit 1 on any FAIL.
  tempdir DIR                      DIR is the run's artifact: temp-directory.txt names the directory Python's tempfile
                                   used for the whole suite, and that name has a non-ASCII character and ends with
                                   graftling-<U+6D4B U+8BD5>-<U+00FC>; the per-file logs that print a path under it are
                                   counted. Last line TEMP PASS|FAIL <reason>.
"""
import difflib
import re
import sys
from pathlib import Path

# The directory windows.yml builds from code points: graftling-测试-ü.
TEMP_NAME = "graftling-测试-ü"
# The lines 638 adds to the suite step of windows.yml, comment lines included (stripped of indentation).
ADDED = [
    "# The temporary directory, so every tmp_path, data root, venv and worktree the tests",
    "# make, sits under a non-ASCII name (638): graftling must handle such paths on Windows.",
    "# The name is built from code points so this file's encoding cannot alter it, and the",
    "# directory Python resolves is kept in temp-directory.txt (UTF-8) for the step script.",
    "$temp = Join-Path $env:RUNNER_TEMP ('graftling-' + [char]0x6D4B + [char]0x8BD5 + '-' + [char]0x00FC)",
    "New-Item -ItemType Directory -Force $temp | Out-Null",
    "$env:TEMP = $temp",
    "$env:TMP = $temp",
    "python -c \"import pathlib, tempfile; pathlib.Path('test-results/windows/temp-directory.txt')"
    ".write_text(tempfile.gettempdir(), encoding='utf-8')\"",
    "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
    "\"temporary directory: $(Get-Content -Raw -Encoding utf8 test-results/windows/temp-directory.txt)\"",
]
BRANCHES = re.compile(r"^(\s*branches: \[)(.*)\]\s*$")


def wfdiff(base_file: str, head_file: str, branch: str, steps: list) -> None:
    """Allow exactly the trigger line and the added suite-step lines; everything else stays as accepted in 632."""
    base = Path(base_file).read_text(encoding="utf-8").splitlines()
    head = Path(head_file).read_text(encoding="utf-8").splitlines()
    bad = []

    def check(ok: bool, good: str, problem: str) -> None:
        print(("PASS: " + good) if ok else ("FAIL: " + problem))
        if not ok:
            bad.append(problem)

    removed, added = [], []
    for line in difflib.unified_diff(base, head, lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        (removed if line.startswith("-") else added).append(line[1:])
    old = [m for m in map(BRANCHES.match, removed) if m]
    new = [m for m in map(BRANCHES.match, added) if m]
    want = old[0].group(1) + old[0].group(2) + ", " + branch + "]" if len(old) == 1 else None
    check(len(removed) == 1 and len(old) == 1, "the only removed line is the push branches line",
          f"removed lines: {removed}")
    check(len(new) == 1 and new[0].group(0).rstrip() == want, f"push branches: base list plus {branch}",
          f"new branches line {[m.group(0) for m in new]}, want {want!r}")
    others = [line.strip() for line in added if not BRANCHES.match(line)]
    check(others == ADDED, "the other added lines are exactly the non-ASCII temporary directory setup",
          "unexpected added lines: " + " | ".join(line for line in others if line not in ADDED)
          + (" (order or count differs)" if sorted(others) != sorted(ADDED) else ""))
    names = lambda lines: [m.group(1).strip() for m in map(re.compile(r"^\s*- name: (.+)$").match, lines) if m]
    check(names(base) == names(head), "step names unchanged: " + " | ".join(names(head)),
          f"step names changed: {names(head)}")
    for step in steps:
        check(step in names(head), f"step named: {step}", f"no step named: {step}")
    suite = "\n".join(head)
    position = {line: suite.find(line) for line in ("$env:TEMP = $temp", ".github/run_test_files.py --out")}
    check(-1 < position["$env:TEMP = $temp"] < position[".github/run_test_files.py --out"],
          "TEMP is set before .github/run_test_files.py runs", "TEMP is not set before the driver runs")
    check("PYTHONUTF8: '1'" in suite, "PYTHONUTF8 stays 1", "PYTHONUTF8 changed")
    sys.exit(1 if bad else 0)


def tempdir(directory: str) -> None:
    """The suite's temporary directory had a non-ASCII name, as the artifact records it."""
    record = Path(directory) / "temp-directory.txt"
    if not record.is_file():
        print(f"TEMP FAIL no temp-directory.txt in the artifact ({directory})")
        return
    text = record.read_text(encoding="utf-8-sig").strip()
    print(f"suite temporary directory (temp-directory.txt): {text}  {ascii(text)}")
    logs = sorted((Path(directory) / "logs").glob("*.txt"))
    mentions = [log.name for log in logs if TEMP_NAME in log.read_text(encoding="utf-8", errors="replace")]
    print(f"per-file logs printing a path under it: {len(mentions)} of {len(logs)}"
          + (f" (e.g. {', '.join(mentions[:3])})" if mentions else ""))
    if not any(ord(char) > 127 for char in text) or not re.search(re.escape(TEMP_NAME) + r"[\\/]?$", text):
        print(f"TEMP FAIL the suite's temporary directory {ascii(text)} does not end with {ascii(TEMP_NAME)}")
        return
    print(f"TEMP PASS the suite ran under {ascii(text)} (non-ASCII)")


if __name__ == "__main__":
    command, args = sys.argv[1], sys.argv[2:]
    if command == "wfdiff":
        wfdiff(args[0], args[1], args[2], args[3:])
    elif command == "tempdir":
        tempdir(args[0])
    else:
        sys.exit(f"unknown command {command}")
