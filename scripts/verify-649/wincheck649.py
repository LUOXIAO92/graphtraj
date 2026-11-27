"""Task 649 (W11, phase B) step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck649.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF        the workflow at the bundle head is the one at BASE (graftling dev 5715323) with its
                                push branches line gaining exactly agent/649-graftling-windows-dsh and one job,
                                dsh-windows-tests, appended at the end; the windows-tests job is unchanged; the new
                                job's runner, pins, credentials, Node, step names, gating install, gating DSH test
                                files and upload are checked
  as632 WF OUT                  write to OUT the workflow with its push branches line (the base's or the head's) set
                                back to 632's, so 632's wfcheck judges the windows-tests job and the whole file's
                                secret and token rules unchanged; fails unless exactly one such line is there
  dshlines OLD NEW              the DSH-related lines (those naming DSH) of the expected list NEW are OLD's (GraphTraj
                                b5653bac's): this Task changes none (the windows-tests job still has no DSH). Other
                                lines belong to other Tasks; their differences are printed as NOTE and do not fail
  dshjob JOBS                   the dsh-windows-tests job of a saved jobs response: every step with its conclusion;
                                last line DSHJOB PASS|FAIL (each named step must have succeeded: the install and the
                                DSH test files gate)
  install DIR                   the DSH job's install facts (DIR/environment.json, the tail of npm-install.txt);
                                information, no verdict
  newtests DIR LIST             every node id in LIST passed in the merged per-file JUnit files of the artifact
                                DIR (not failed, errored, skipped or absent); last line NEWTESTS PASS|FAIL
Writes nothing, except as632's OUT.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verify-632"))
from wincheck import load, nodeid  # noqa: E402

# graftling dev 5715323's push branches, in the workflow's order; the candidate appends only its own branch.
BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
                 "agent/638-graftling-windows-paths-encoding", "dev", "agent/636-graftling-windows-named-pipe",
                 "agent/637-graftling-windows-process-listing", "agent/639-graftling-windows-codex",
                 "agent/647-graftling-windows-claude", "agent/648-graftling-windows-pi"]
BRANCHES = BASE_BRANCHES + ["agent/649-graftling-windows-dsh"]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
JOB = "dsh-windows-tests"
SETUP = ["Keep symbolic links on this runner", "Check out the commit under test", "Set up Node 24.22.3 x64",
         "Set up Python 3.13.7 x64", "Install graftling and pinned test tools", "Restore the npm download cache"]
INSTALL = "Install DSH with npm"
TESTS = "Run graftling's DSH test files against the installed DSH"
UPLOAD = "Retain the DSH test results"
STEPS = SETUP + [INSTALL, TESTS, UPLOAD]
ARTIFACT = "graftling-dsh-windows-${{ github.sha }}-${{ github.run_attempt }}"
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
CRED_PART = re.compile(r"(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
PROVIDER = re.compile(r"^(ANTHROPIC_|OPENAI_|DEEPSEEK_|CODEX_|CLAUDE_CODE_USE_|GRAFTLING_CONNECTION)|_BASE_URL$")


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
    check(branches == BRANCHES, "push branches are exactly dev's plus agent/649-graftling-windows-dsh",
          f"push branches are {branches}, not {BRANCHES}")
    prefix = base.replace(BASE_LINE + "\n", HEAD_LINE + "\n")
    appended = head[len(prefix):] if head.startswith(prefix) else None
    check(base.count(BASE_LINE + "\n") == 1 and appended is not None,
          "the base workflow is unchanged up to its end apart from the push branches line",
          "the workflow differs from the base before its end, beyond the push branches line")
    jobs = doc.get("jobs") or {}
    base_jobs = yaml.safe_load(base).get("jobs") or {}
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
    cache = next((s for s in items if s.get("name") == SETUP[-1]), {})
    check(str(cache.get("uses", "")).startswith("actions/cache@") and "npm-cache" in str((cache.get("with") or {}).get("path")),
          "the npm download cache is actions/cache over npm's cache directory only",
          "the cache step is not actions/cache over npm's cache directory")
    install = str(next((s.get("run", "") for s in items if s.get("name") == INSTALL), ""))
    check('npm install -g' in install and '"@deepseek-ai/dsh@$env:DSH_VERSION"' in install
          and re.search(r"^\s*exit \$code\s*$", install, re.M) is not None and "exit 0" not in install,
          "the install step runs npm install -g @deepseek-ai/dsh@$DSH_VERSION and exits with npm's code (gating)",
          "the install step does not gate on npm install -g @deepseek-ai/dsh@$DSH_VERSION")
    tests = next((s for s in items if s.get("name") == TESTS), {})
    command = str(tests.get("run", ""))
    check("test_*dsh*.py" in command
          and re.search(r"^\s*python \.github/run_test_files\.py --out test-results/dsh --file-limit \d+ --total-limit \d+ @files\s*$",
                        command, re.M) is not None
          and "run-exit-code.txt" in command and re.search(r"^\s*exit \$code\s*$", command, re.M) is not None
          and "exit 0" not in command and "always()" not in str(tests.get("if", "")),
          "every tests/test_*dsh*.py runs through .github/run_test_files.py, gating, after a successful install",
          "the DSH test step does not run every test_*dsh*.py through run_test_files.py, gating")
    upload = next((s for s in items if s.get("name") == UPLOAD), {})
    w = upload.get("with") or {}
    check(str(upload.get("if", "")).startswith("always()") and "retention-days" in w and w.get("name") == ARTIFACT
          and w.get("path") == "test-results/dsh/" and w.get("if-no-files-found") == "error",
          f"upload always() as {w.get('name')} with retention {w.get('retention-days')} days",
          "the upload is not always(), not named graftling-dsh-windows-<sha>-<attempt> or without retention")
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
        print(f"PASS: the {len(new_dsh)} DSH-related lines of the expected list are unchanged (windows-tests has no DSH)")
        sys.exit(0)
    for line in sorted(set(old_dsh) ^ set(new_dsh)):
        print(f"FAIL: DSH-related line {'added' if line in new_dsh else 'removed'}: {line[:160]!r}")
    if set(old_dsh) == set(new_dsh):
        print("FAIL: the DSH-related lines are reordered")
    sys.exit(1)


def dshjob(jobs_file):
    found = load(jobs_file).get("jobs", [])
    job = next((j for j in found if j.get("name") == JOB), None)
    problems = []
    if job is None:
        problems.append(f"no {JOB} job")
    else:
        print("DSH JOB", job.get("name"), "|", job.get("status"), "|", job.get("conclusion"), "|", job.get("html_url"))
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
    print("DSHJOB", "FAIL" if problems else "PASS",
          "; ".join(problems) or f"{len(STEPS)} steps succeeded (DSH installed; every DSH test file passed or skipped)")


def install(directory):
    path = os.path.join(directory, "environment.json")
    try:
        facts = load(path) if os.path.exists(path) else None
    except ValueError:
        facts = None
    if facts is None:
        try:  # PowerShell's Set-Content -Encoding utf8 may write a byte order mark
            facts = json.loads(open(path, encoding="utf-8-sig").read())
        except (OSError, ValueError):
            facts = None
    print("--- DSH install on the runner (information)")
    if facts is None:
        print("  environment.json missing or unreadable")
    else:
        for key in ("dsh_requested", "npm_exit", "install_seconds", "npm_cache_hit", "node", "npm", "dsh_version",
                    "dsh", "npm_prefix", "npm_cache", "codepage", "image", "image_version", "arch"):
            print(f"  {key}: {facts.get(key)}")
    log = os.path.join(directory, "npm-install.txt")
    if os.path.exists(log):
        tail = [line for line in open(log, encoding="utf-8", errors="replace").read().splitlines() if line.strip()][-3:]
        for line in tail:
            print(f"  npm | {line[:200]}")


def newtests(directory, list_file):
    wanted = [line.strip() for line in open(list_file, encoding="utf-8") if line.strip() and not line.startswith("#")]
    outcome = {}
    files = os.path.join(directory, "files.json")
    for record in (load(files).get("files", []) if os.path.exists(files) else []):
        if not record.get("junit"):
            continue
        path = os.path.join(directory, record["junit"].replace("\\", "/"))
        if not os.path.exists(path):
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            tags = {child.tag for child in case}
            outcome[nodeid(case)] = ("failed" if tags & {"failure", "error"} else
                                     "skipped" if "skipped" in tags else "passed")
    passed = 0
    print(f"--- the DSH tests that must pass on Windows (649): {len(wanted)}")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    verdict = "PASS" if passed == len(wanted) else "FAIL"
    print(f"NEWTESTS {verdict} {passed} of {len(wanted)} DSH tests passed")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "as632": as632, "dshlines": dshlines, "dshjob": dshjob, "install": install,
     "newtests": newtests}[command](*rest)
