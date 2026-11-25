"""Task 632 round 2B: apply Main's rules R1-R13 to every failure of run 45608819873 (offline, read only).

Run as: python -I classify.py <artifact dir (evidence/run-45608819873-a1/junit)> <out dir>
Writes <out>/fail-lines.txt (windows-expected.txt `fail` lines) and <out>/classification.txt (every failure with all
rules that matched, and any failure that fits no rule or rules with different owners). Standard library only.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from wincheck import load, log_sections, nodeid, origin, section_for  # noqa: E402

TASK = {"W1": "W1 (633)", "W2": "W2 (634)", "W3": "W3 (635)", "W4": "W4 (636)", "W6": "W6 (638)",
        "W8": "W8 (not registered; outside this round)"}
PIPE = "Windows does not support the authenticated local control pipe"
ARGS = "Exact process arguments are unavailable on this platform"

directory, out = sys.argv[1], sys.argv[2]
records = load(os.path.join(directory, "files.json"))["files"]
failures = []
for record in records:
    if not record.get("junit"):
        continue
    log = os.path.join(directory, record["log"].replace("\\", "/"))
    log_text = open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else ""
    sections = log_sections(log_text)
    for case in ET.parse(os.path.join(directory, record["junit"].replace("\\", "/"))).getroot().iter("testcase"):
        item = case.find("failure") if case.find("failure") is not None else case.find("error")
        if item is None:
            continue
        section = section_for(sections, case)
        where, how = origin(item.text, case)
        if how != "junit":
            found = origin(item.text, case, section)
            where, how = found if found[1] == "log" else (where, how)
        text = (item.get("message") or "") + "\n" + (item.text or "")
        failures.append({"node": nodeid(case), "where": where, "how": how, "text": text, "section": section,
                         "message": ((item.get("message") or "").splitlines() or [""])[0][:160]})


def rules(f):
    """[(rule, owner, note)] for every rule that matches this failure."""
    node, where, text = f["node"], f["where"], f["text"]
    module, name = node.split("::")[0], node.split("::")[-1]
    hits = []
    if PIPE in text:
        hits.append(("R5", "W4", "control-pipe refusal in the failure text"))
    if ARGS in text:
        hits.append(("R3", "W1", "'Exact process arguments are unavailable' in the failure text"))
    if where == "src/graftling/sessions/archive.py:104":
        hits.append(("R1", "W2", "directory fsync after an archive write"))
    if node == "tests/test_agent_control.py::test_repeated_controls_never_run_one_session_twice":
        hits.append(("R2", "W2", "background send PermissionError(13, 'Access is denied'): replace under a concurrent "
                                 "reader, inferred, no frame"))
    if where in ("tests/test_agent_control.py:458", "tests/test_agent_control.py:498"):
        hits.append(("R4", "W1", "control._alive treats every PID as alive (M12)"))
    if where == "src/graftling/connection.py:163":
        hits.append(("R6", "W4", "os.O_DIRECTORY in connection.py"))
    if where in ("tests/test_pi_dsh_notice_holding.py:483", "tests/test_envelope_validation_555.py:205"):
        refusal = next((line.strip() for line in f["section"].splitlines() if PIPE in line), None)
        if refusal:
            hits.append(("R7", "W4", f"R7 -> W4: its log section shows the refusal: {refusal[:140]}"))
        else:
            errors = [line.strip() for line in f["section"].splitlines()
                      if re.match(r"^E\s+[\w.]*(Error|Exception)\b", line)]
            hits.append(("R7", "W3", "R7 -> W3: its log section shows no control-pipe refusal; deciding line: "
                         + (errors[-1][:140] if errors else "none")))
    if where == "src/graftling/discovery.py:150":
        hits.append(("R8", "W6", "os.O_NOFOLLOW in discovery.py"))
    if ("expected an absolute path" in text or "needs an absolute data root" in text
            or where in ("src/graftling/config.py:353", "src/graftling/control.py:1147", "src/graftling/dsh/host.py:102",
                         "src/graftling/pi/host.py:125")
            or (module == "tests/test_agents_connections_presets.py" and "invalid-config" in text)):
        hits.append(("R9", "W6", "test portability: test data with POSIX absolute paths"))
    if ((module == "tests/test_claude_archive_batches_468.py" and "/dev/fd" in text)
            or (module == "tests/test_tool_name_591.py" and "/p/hooks/host_context.mjs" in text)
            or (module == "tests/test_child_server_name_551.py" and "ERR_UNSUPPORTED_ESM_URL_SCHEME" in text)):
        hits.append(("R10", "W6", "test portability: test-side POSIX construct"))
    if where == "tests/test_dsh_plugin_install_python.py:134" or \
            node == "tests/test_dsh_providers_608.py::test_listing_routes_the_provider_like_its_child":
        hits.append(("R11", "W6", "M10 Python lookup"))
    if node == "tests/test_unified_data_root_577.py::test_claude_launcher_logs_into_the_variable":
        hits.append(("R12", "W8", "Claude plugin launcher; no mark"))
    if module == "tests/test_codex_child_interpreter_shutdown_473.py" and "'NoneType'" in text and "start" in text:
        hits.append(("R13", "W3", "provisional; 635 confirms"))
    return hits


lines, report, problems, decided = [], [], [], Counter()
for f in sorted(failures, key=lambda f: f["node"]):
    hits = rules(f)
    text_rules = [h for h in hits if h[0] in ("R3", "R5")]
    other = [h for h in hits if h[0] not in ("R3", "R5")]
    owners_text = {h[1] for h in text_rules}
    if not hits:
        problems.append(f"NO RULE  {f['node']} | origin {f['where']} ({f['how']}) | {f['message']}")
        continue
    if len(owners_text) > 1:
        problems.append(f"CONFLICT {f['node']} | {', '.join(h[0] + '->' + h[1] for h in hits)} | {f['message']}")
        continue
    # A refusal named in the failure text (R3/R5) wins over path rules; otherwise every matching rule must agree.
    chosen = text_rules if text_rules else other
    owners = {h[1] for h in chosen}
    if len(owners) > 1:
        problems.append(f"CONFLICT {f['node']} | {', '.join(h[0] + '->' + h[1] for h in hits)} | {f['message']}")
        continue
    rule, owner, why = chosen[0]
    overridden = [h for h in other if h[1] != owner] if text_rules else []
    note = f"{'+'.join(h[0] for h in chosen)}: {why}"
    if overridden:
        note += f" (text rule wins over {', '.join(h[0] + '->' + h[1] for h in overridden)})"
    note += f" | observed: {f['message'][:120]}" + (f" (origin from {f['how']})" if f["how"] != "junit" else "")
    lines.append(f"fail\t{f['node']}\t{f['where']}\t{TASK[owner]}\t{note}")
    decided[(rule if len(chosen) == 1 else '+'.join(h[0] for h in chosen), TASK[owner])] += 1
    report.append(f"{TASK[owner]:42} {'+'.join(h[0] for h in hits):10} {f['node']} | {f['where']}")

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "fail-lines.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
with open(os.path.join(out, "classification.txt"), "w", encoding="utf-8") as handle:
    handle.write(f"failures: {len(failures)}; decided: {len(lines)}; undecided: {len(problems)}\n")
    handle.write("--- undecided (no rule, or rules with different owners)\n" + "\n".join(problems) + "\n")
    handle.write("--- by rule and Task\n" + "\n".join(f"{n:4d}  {r:8} {t}" for (r, t), n in sorted(decided.items())) + "\n")
    handle.write("--- per Task\n" + "\n".join(f"{n:4d}  {t}" for t, n in Counter(l.split('\t')[3] for l in lines).most_common()) + "\n")
    handle.write("--- every failure: Task, rules that matched, node id, origin\n" + "\n".join(report) + "\n")
print(open(os.path.join(out, "classification.txt"), encoding="utf-8").read().split("--- every failure")[0])
