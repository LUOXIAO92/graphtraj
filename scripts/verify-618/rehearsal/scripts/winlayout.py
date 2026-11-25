"""618: run tests/conftest.py's _installation_problem against a fake Windows layout without Windows.

Usage (from a GraphTraj checkout root, with a venv where graphtraj is installed editable from that checkout):
  python winlayout.py <scratch dir>
Builds <scratch>/prefix/python.exe (a POSIX wrapper that execs this interpreter, so the metadata probe is real) and
<scratch>/prefix/Scripts/graphtraj-session.exe, points sysconfig's 'scripts' path at <prefix>/Scripts as on a
setup-python Windows runner, and prints the result for the default call and for the real interpreter.
"""
import os, stat, sys, sysconfig
from pathlib import Path

sys.path.insert(0, "tests")
import conftest

prefix = Path(sys.argv[1]) / "prefix"
(prefix / "Scripts").mkdir(parents=True, exist_ok=True)
exe = prefix / "python.exe"
exe.write_text("#!/bin/sh\nexec '{0}' \"$@\"\n".format(sys.executable))
exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
(prefix / "Scripts" / "graphtraj-session.exe").write_bytes(b"")
print("this interpreter, default call:", conftest._installation_problem())
real = sysconfig.get_path
sysconfig.get_path = lambda name, *a, **k: str(prefix / "Scripts") if name == "scripts" else real(name, *a, **k)
print("fake Windows layout {0} with Scripts\\graphtraj-session.exe:".format(exe), conftest._installation_problem(str(exe)))
