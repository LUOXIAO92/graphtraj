"""Task 649 (W11, phase A) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck649.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF        the workflow at the bundle head is the one at BASE (graftling dev eb5ad8e) with its
                                push branches line gaining exactly agent/649-graftling-windows-dsh and one job,
                                dsh-windows-probe, appended at the end; the windows-tests job is unchanged; the new
                                job's runner, pins, credentials, Node, step names, probe command and upload are checked
  as632 WF OUT                  write to OUT the workflow with its push branches line (the base's or the head's) set
                                back to 632's, so 632's wfcheck judges the windows-tests job and the whole file's
                                secret and token rules unchanged; fails unless exactly one such line is there
  dshlines OLD NEW              the DSH-related lines (those naming DSH) of the expected list NEW are OLD's (GraphTraj
                                afaf516d's): phase A changes none. Other lines belong to other Tasks (647, 648 edit the
                                same file in parallel); their differences are printed as NOTE and do not fail
  probejob JOBS                 the dsh-windows-probe job of a saved jobs response: every step with its conclusion;
                                last line PROBEJOB PASS|FAIL (each named step must have succeeded)
  findings DIR                  the downloaded probe artifact: every probe with its exit code and a short excerpt,
                                then the DSH test files' records; last line FINDINGS PASS|FAIL (PASS: the artifact is
                                complete, whatever DSH did; the findings are evidence, not a pass condition)
Writes nothing, except as632's OUT.
"""
import json
import os
import re
import sys
from pathlib import Path

# graftling dev eb5ad8e's push branches, in the workflow's order; the candidate appends only its own branch.
BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
                 "agent/638-graftling-windows-paths-encoding", "dev", "agent/636-graftling-windows-named-pipe",
                 "agent/637-graftling-windows-process-listing", "agent/639-graftling-windows-codex"]
BRANCHES = BASE_BRANCHES + ["agent/649-graftling-windows-dsh"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
JOB = "dsh-windows-probe"
SETUP = ["Keep symbolic links on this runner", "Check out the commit under test", "Set up Node 24.22.3 x64",
         "Set up Python 3.13.7 x64", "Install graftling and pinned test tools"]
PROBE = "Probe DSH on this runner"
TESTS = "Run graftling's DSH test files against the installed DSH"
UPLOAD = "Retain the DSH probe results"
STEPS = SETUP + [PROBE, TESTS, UPLOAD]
PROBES = ["runner", "registry", "install", "package", "cli-version", "cli-node", "cli-help", "cli-web-help",
          "preflight", "web-raw", "service", "owner-death"]
DSH_TEST_FILES = ["tests/test_dsh_live.py", "tests/test_dsh_mcp.py", "tests/test_dsh_standalone_child.py",
                  "tests/test_dsh_providers_608.py", "tests/test_pi_dsh_child_tools_551.py",
                  "tests/test_pi_dsh_owner_tools_no_ask_551.py"]
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
CRED_PART = re.compile(r"(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
PROVIDER = re.compile(r"^(ANTHROPIC_|OPENAI_|DEEPSEEK_|CODEX_|CLAUDE_CODE_USE_|GRAFTLING_CONNECTION)|_BASE_URL$")


def load(file):
    with open(file, encoding="utf-8") as handle:
        return json.load(handle)


def wfdiff(base_file, head_file):
    import yaml

    base = open(base_file, encoding="utf-8").read()
    head = open(head_file, encoding="utf-8").read()
    bad = []

    def check(ok, good, problem):
        print(("PASS: " + good) if ok else ("FAIL: " + problem))
        if not ok:
            bad.append(problem)

    doc = yaml.safe_load(head)
    on = doc.get("on", doc.get(True)) or {}
    branches = ((on.get("push") or {}).get("branches") or []) if isinstance(on, dict) else []
    check(branches == BRANCHES, f"push branches are exactly dev's plus agent/649-graftling-windows-dsh",
          f"push branches are {branches}, not {BRANCHES}")
    prefix = base.replace(BASE_LINE + "\n", HEAD_LINE + "\n")
    appended = head[len(prefix):] if head.startswith(prefix) else None
    check(base.count(BASE_LINE + "\n") == 1 and appended is not None,
          "the base workflow is unchanged up to its end apart from the push branches line",
          "the workflow differs from the base before its end, beyond the push branches line")
    jobs = doc.get("jobs") or {}
    base_jobs = (yaml.safe_load(base).get("jobs") or {})
    check(list(jobs) == ["windows-tests", JOB], f"jobs are windows-tests and {JOB}", f"jobs are {list(jobs)}")
    check(jobs.get("windows-tests") == base_jobs.get("windows-tests"), "the windows-tests job is the base one",
          "the windows-tests job changed")
    check(appended is not None and re.match(rf"\n(  #[^\n]*\n)*  {JOB}:\n", appended) is not None,
          f"only the {JOB} job (with its comment) is appended", f"the appended text is not one {JOB} job")
    job = jobs.get(JOB) or {}
    check(job.get("runs-on") == "windows-latest", f"{JOB} runs on windows-latest", f"runs-on is {job.get('runs-on')}")
    check(isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] <= 90,
          f"{JOB} timeout-minutes {job.get('timeout-minutes')}", f"{JOB} has no timeout-minutes up to 90")
    env = job.get("env") or {}
    check(str(env.get("PYTHONUTF8")) == "1", "PYTHONUTF8=1", "PYTHONUTF8 is not 1")
    named = [k for k in env if any(CRED_PART.search(p) for p in k.upper().split("_")) or PROVIDER.search(k.upper())]
    check(not named, f"job env names no credential or provider variable: {sorted(env)}", f"job env names {named}")
    check(env.get("DSH_VERSION") == "0.2.2-rc.5", "DSH_VERSION 0.2.2-rc.5 (graftling README's tested DSH)",
          f"DSH_VERSION is {env.get('DSH_VERSION')}")
    items = job.get("steps") or []
    names = [step.get("name") for step in items]
    check(names == STEPS, "steps: " + " | ".join(STEPS), f"steps are {names}")
    uses = [step["uses"] for step in items if "uses" in step]
    check(bool(uses) and all(SHA_PIN.match(u) for u in uses), "every action pinned to a 40-hex SHA: " + ", ".join(uses),
          "unpinned actions: " + ", ".join(u for u in uses if not SHA_PIN.match(u)))
    checkout = next((i for i, s in enumerate(items) if str(s.get("uses", "")).startswith("actions/checkout@")), None)
    symlinks = next((i for i, s in enumerate(items) if "core.symlinks true" in str(s.get("run", ""))), None)
    check(checkout is not None and symlinks is not None and symlinks < checkout
          and (items[checkout].get("with") or {}).get("persist-credentials") is False,
          "core.symlinks before the checkout; checkout has persist-credentials: false",
          "symlinks or persist-credentials wrong")
    node = next((s.get("with") or {} for s in items if str(s.get("uses", "")).startswith("actions/setup-node@")), {})
    version = tuple(int(x) for x in re.findall(r"\d+", str(node.get("node-version")))[:3])
    check(version >= (24, 9, 0) and node.get("architecture") == "x64",
          f"Node {node.get('node-version')} x64 (DSH 0.2.2-rc.5 needs >=24.9.0)",
          f"Node is {node.get('node-version')} {node.get('architecture')}")
    run_text = "\n".join(str(s.get("run", "")) for s in items)
    check(re.search(r"\benv\b\s*(\||$)|Get-ChildItem\s+env:|\bprintenv\b|\bset\s*$", run_text, re.M) is None,
          "no step prints the whole environment", "a step prints the environment")
    probe = str(next((s.get("run", "") for s in items if s.get("name") == PROBE), ""))
    check(re.search(r"^\s*python \.github/dsh_windows_probe\.py --out test-results/dsh-probe --dsh-version \$env:DSH_VERSION\s*$",
                    probe, re.M) is not None, "the probe step runs .github/dsh_windows_probe.py into test-results/dsh-probe",
          "the probe step does not run .github/dsh_windows_probe.py --out test-results/dsh-probe")
    tests = next((s for s in items if s.get("name") == TESTS), {})
    check(str(tests.get("if", "")).startswith("always()") and "run-exit-code.txt" in str(tests.get("run", ""))
          and all(f in str(tests.get("run", "")) for f in DSH_TEST_FILES)
          and re.search(r"^\s*exit 0\s*$", str(tests.get("run", "")), re.M) is not None,
          "the DSH test files run always(), their exit code is recorded and does not gate",
          "the DSH test files step is not always(), unrecorded or gating")
    upload = next((s for s in items if s.get("name") == UPLOAD), {})
    w = upload.get("with") or {}
    check(str(upload.get("if", "")).startswith("always()") and "retention-days" in w
          and w.get("name") == "graftling-dsh-probe-${{ github.sha }}-${{ github.run_attempt }}"
          and w.get("path") == "test-results/dsh-probe/" and w.get("if-no-files-found") == "error",
          f"upload always() as {w.get('name')} with retention {w.get('retention-days')} days",
          "the upload is not always(), not named graftling-dsh-probe-<sha>-<attempt> or without retention")
    sys.exit(1 if bad else 0)


def as632(file, out_file):
    text = open(file, encoding="utf-8").read()
    found = [line for line in (BASE_LINE, HEAD_LINE) if text.count(line + "\n") == 1]
    if len(found) != 1:
        print(f"FAIL: {file} has neither exactly one {BASE_LINE.strip()!r} nor one {HEAD_LINE.strip()!r}")
        sys.exit(1)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write(text.replace(found[0] + "\n", LINE_632 + "\n"))
    which = "the base's" if found[0] == BASE_LINE else "the head's (with 649)"
    print(f"PASS: push branches line is {which}; judged below with it set back to 632's")


def dsh_line(line):
    return "dsh" in line.lower()


def dshlines(old_file, new_file):
    old = open(old_file, encoding="utf-8").read().splitlines()
    new = open(new_file, encoding="utf-8").read().splitlines()
    old_dsh, new_dsh = [l for l in old if dsh_line(l)], [l for l in new if dsh_line(l)]
    others = sorted(set(l for l in old if not dsh_line(l)) ^ set(l for l in new if not dsh_line(l)))
    for line in others:
        print(f"NOTE: a non-DSH line differs from the base (another Task's): {line[:160]!r}")
    if old_dsh == new_dsh:
        print(f"PASS: the {len(new_dsh)} DSH-related lines of the expected list are unchanged (phase A changes none)")
        sys.exit(0)
    for line in sorted(set(old_dsh) ^ set(new_dsh)):
        print(f"FAIL: DSH-related line {'added' if line in new_dsh else 'removed'}: {line[:160]!r}")
    if set(old_dsh) == set(new_dsh):
        print("FAIL: the DSH-related lines are reordered")
    sys.exit(1)


def probejob(jobs_file):
    found = load(jobs_file).get("jobs", [])
    job = next((j for j in found if j.get("name") == JOB), None)
    problems = []
    if job is None:
        problems.append(f"no {JOB} job")
    else:
        print("PROBE JOB", job.get("name"), "|", job.get("status"), "|", job.get("conclusion"), "|", job.get("html_url"))
        seen = {}
        for s in job.get("steps", []):
            seen[s.get("name")] = s.get("conclusion")
            mark = "must succeed" if s.get("name") in STEPS else "other: success or skipped"
            if s.get("name") not in STEPS and s.get("conclusion") not in ("success", "skipped"):
                problems.append(f"step {s.get('name')!r} is {s.get('conclusion')}")
            print("  step %2s | %-9s | %s | %s" % (s.get("number"), s.get("conclusion"), s.get("name"), mark))
        for name in STEPS:
            if name not in seen:
                problems.append(f"step {name!r} is missing")
            elif seen[name] != "success":
                problems.append(f"step {name!r} is {seen[name]}")
    print("PROBEJOB", "FAIL" if problems else "PASS",
          "; ".join(problems) or f"{len(STEPS)} steps succeeded (the probe recorded every probe; the DSH test files ran)")


def findings(directory):
    problems = []
    path = os.path.join(directory, "findings.json")
    data = load(path) if os.path.exists(path) else None
    if data is None:
        problems.append("no findings.json")
    else:
        records = {r.get("probe"): r for r in data.get("probes", [])}
        print(f"--- DSH probe findings (DSH {data.get('dsh_version')}; evidence, not a pass condition); "
              f"variables removed by name: {data.get('removed_variable_names')}")
        for probe in PROBES:
            r = records.get(probe)
            if r is None:
                print(f"  {probe:<12} ABSENT")
                problems.append(f"probe {probe} not recorded")
                continue
            if "exit" not in r or not os.path.exists(os.path.join(directory, str(r.get("log", "")).replace("\\", "/"))):
                problems.append(f"probe {probe} has no exit code or log")
            print(f"  {probe:<12} exit {r.get('exit')!s:<6}{' (timed out)' if r.get('timed_out') else ''} "
                  f"{r.get('seconds')} s | {r.get('title')}")
            for key, value in (r.get("facts") or {}).items():
                text = json.dumps(value, default=str)
                print(f"      {key}: {text[:300]}{' ...' if len(text) > 300 else ''}")
            for line in (r.get("excerpt") or [])[-3:]:
                print(f"      | {line[:200]}")
        if not data.get("complete"):
            problems.append("findings.json says complete: false")
    tests = os.path.join(directory, "tests")
    files = os.path.join(tests, "files.json")
    print("--- graftling's DSH test files against the installed DSH (recorded, not gating)")
    if not os.path.exists(files):
        problems.append("no tests/files.json")
    else:
        records = {r.get("file"): r for r in load(files).get("files", [])}
        for name in DSH_TEST_FILES:
            r = records.get(name)
            if r is None:
                problems.append(f"no record for {name}")
                print(f"  {name}: ABSENT")
                continue
            summary, skips = "", {}
            log = os.path.join(tests, str(r.get("log", "")).replace("\\", "/"))
            if r.get("log") and os.path.exists(log):
                text = open(log, encoding="utf-8", errors="replace").read()
                found = re.findall(r"=+ (.*(?:passed|failed|error|skipped|no tests ran).*) in [0-9.]+s", text)
                summary = found[-1] if found else ""
                for count, reason in re.findall(r"^SKIPPED \[(\d+)\] [^:]+:\d+: (.*)$", text, re.M):
                    skips[reason] = skips.get(reason, 0) + int(count)
            print(f"  {name}: {r.get('outcome')} exit {r.get('exit_code')} | {summary}")
            for reason, count in skips.items():
                print(f"      skipped {count}: {reason[:160]}")
        code = os.path.join(tests, "run-exit-code.txt")
        print(f"  run_test_files exit code: {open(code).read().strip() if os.path.exists(code) else 'absent'}")
        if not os.path.exists(code):
            problems.append("no tests/run-exit-code.txt")
    print("FINDINGS", "FAIL" if problems else "PASS",
          "; ".join(problems) or f"the probe artifact is complete: {len(PROBES)} probes and {len(DSH_TEST_FILES)} "
                                  "DSH test file records, each with its exit code")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "as632": as632, "dshlines": dshlines, "probejob": probejob, "findings": findings}[command](*rest)
