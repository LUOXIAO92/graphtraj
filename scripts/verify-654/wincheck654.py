"""Task 654 step helper, beside verify-632/wincheck.py and verify-652/wincheck652.py (steps.zsh runs both by path).

Run as: python -I wincheck654.py fixed DIR NODEID
  fixed DIR NODEID   NODEID's outcome in the merged per-file JUnit files of the windows-tests artifact DIR
                     (files.json, junit/*.xml); last line FIXED PASS|FAIL (PASS only when it passed: not failed,
                     errored, skipped or absent)
Standard library only. Writes nothing.
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify-632"))
from wincheck import load, nodeid  # noqa: E402


def fixed(directory, wanted):
    """The one test 654 changes: its outcome on the runner, with the failure text when it failed."""
    outcome, text = None, ""
    files = os.path.join(directory, "files.json")
    for record in (load(files).get("files", []) if os.path.exists(files) else []):
        path = os.path.join(directory, (record.get("junit") or "").replace("\\", "/"))
        if not record.get("junit") or not os.path.exists(path):
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            if nodeid(case) != wanted:
                continue
            bad = [child for child in case if child.tag in ("failure", "error")]
            outcome = "failed" if bad else "skipped" if any(c.tag == "skipped" for c in case) else "passed"
            text = (bad[0].get("message") or "")[:240] if bad else ""
    print(f"  {(outcome or 'absent').upper()} {wanted}" + (f" | {text}" if text else ""))
    print(f"FIXED {'PASS' if outcome == 'passed' else 'FAIL'} {wanted} {outcome or 'absent'} in windows-tests' JUnit")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"fixed": fixed}[command](*rest)
