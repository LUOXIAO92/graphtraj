"""Task 647 rehearsal stand-in for gh: runs 632's fakegh.py (by reference, unchanged) and renames its branch.

Called as: python -I fakegh647.py <state-dir> <gh arguments...>. Never contacts GitHub. fakegh.py names every run's
head_branch agent/632-graftling-windows-ci; the 647 steps check that a run they re-run is on
agent/647-graftling-windows-claude, so its output is passed on with that one name replaced. Exit code and stderr are
passed on unchanged. Scenarios, state files and artifact layout: see verify-632/rehearsal/fakegh.py.

fakegh.py's `mismatch` (and `rerun`'s first attempt) turns the first `fails` entry into a pass. The expected list
this Task leaves has no `fail` entry, so before each call `fails` is written from `fails-base` (the failures the
rehearsal asks for), with the W8 test first only while that attempt is a mismatch: it passes there as it does in
the stand-in artifact, and the mismatch's other two faults (an unlisted failure, an unprefixed skip) remain.
"""
import subprocess
import sys
from pathlib import Path

FAKEGH = Path(__file__).resolve().parents[2] / "verify-632" / "rehearsal" / "fakegh.py"
W8 = "tests/test_unified_data_root_577.py::test_claude_launcher_logs_into_the_variable"

state = Path(sys.argv[1])
scenario = (state / "scenario").read_text().strip()
attempt = max(1, int((state / "attempt").read_text()) if (state / "attempt").exists() else 0)
asked = [line for line in (state / "fails-base").read_text().splitlines() if line] \
    if (state / "fails-base").exists() else []
mismatch = scenario == "mismatch" or (scenario == "rerun" and attempt < 2)
(state / "fails").write_text("\n".join(([W8] if mismatch else []) + asked) + "\n")

done = subprocess.run([sys.executable, "-I", str(FAKEGH), *sys.argv[1:]], capture_output=True, text=True)
sys.stdout.write(done.stdout.replace("agent/632-graftling-windows-ci", "agent/647-graftling-windows-claude"))
sys.stderr.write(done.stderr)
sys.exit(done.returncode)
