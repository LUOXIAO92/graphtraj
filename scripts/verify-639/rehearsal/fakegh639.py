"""Task 639 rehearsal stand-in for gh: runs 632's fakegh.py (by reference, unchanged) and renames its branch.

Called as: python -I fakegh639.py <state-dir> <gh arguments...>. Never contacts GitHub. fakegh.py names every run's
head_branch agent/632-graftling-windows-ci; the 639 steps check that a run they re-run is on
agent/639-graftling-windows-codex, so its output is passed on with that one name replaced. Exit code and stderr are
passed on unchanged. Scenarios, state files and artifact layout: see verify-632/rehearsal/fakegh.py.
"""
import subprocess
import sys
from pathlib import Path

FAKEGH = Path(__file__).resolve().parents[2] / "verify-632" / "rehearsal" / "fakegh.py"
done = subprocess.run([sys.executable, "-I", str(FAKEGH), *sys.argv[1:]], capture_output=True, text=True)
sys.stdout.write(done.stdout.replace("agent/632-graftling-windows-ci", "agent/639-graftling-windows-codex"))
sys.stderr.write(done.stderr)
sys.exit(done.returncode)
