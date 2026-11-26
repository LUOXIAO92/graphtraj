"""Task 640 rehearsal: the settings drive640.py builds outside the stand-in (real mode): host/child approval policy and
the profile each mode extends. Usage: V640_HOME=<dir with settings.json> python3 -I check_settings640.py <vm dir>."""
import sys, pathlib
sys.path.insert(0, sys.argv[1])
import drive640 as d
w = pathlib.Path("w")
h = d.child_settings(w, ["codex"], "mxc", host=True)["adapter_request"]["session_parameters"]
c = d.child_settings(w, ["codex"], "mxc")["adapter_request"]["session_parameters"]
n = d.child_settings(w, ["codex"], "none")["adapter_request"]["session_parameters"]["config"]["permissions"]["chosen"]["extends"]
u = d.child_settings(w, ["codex"], "unelevated")["adapter_request"]["session_parameters"]["config"]["permissions"]["chosen"]["extends"]
print(f"real-mode settings: host approvalPolicy {h['approvalPolicy']}; child approvalPolicy {c['approvalPolicy']}; none extends {n}; unelevated extends {u}")
