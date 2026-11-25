"""Task 632 step helper: reads the graftling Windows workflow, GitHub REST JSON saved by steps.zsh and the
downloaded JUnit evidence; prints plain lines. Modelled on verify-623/ghjson.py.

Run as: python -I wincheck.py <command> <args...>. Standard library only except `wfcheck`, which needs PyYAML.
  wfcheck FILE BRANCH JOB STEP...     the workflow's triggers, permissions, secrets, pins, env and step names
  expected FILE                       the expected list parses; counts of its entries
  get FILE KEY[.KEY...]               value at a key path (empty when absent)
  runs FILE PATH EVENT                newest run of PATH (EVENT or '-' for any event): RUN line, or MISSING; OTHER lines
  newrun FILE PATH EVENT OLD_ID...    newest run of PATH and EVENT whose id is not an OLD_ID: RUN line, or MISSING
  jobs FILE CONFIG                    every step of the job with its conclusion; last line JUDGE PASS|FAIL <reason>
  junit DIR EXPECTED CANDIDATE        judge DIR/junit.xml against EXPECTED; write CANDIDATE (the observed list, for a
                                      correction round); last line JUDGE PASS|FAIL <reason>
Writes only the CANDIDATE file of `junit`.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

PREFIX = "POSIX-only: "
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
# Which Windows Task (629 advice, section 5) a failure's deepest graftling frame most likely belongs to.
ORIGIN_TASK = [
    ("src/graftling/connection.py", "W4"), ("src/graftling/codex/host.py", "W4"),
    ("src/graftling/locks.py", "W2"), ("src/graftling/sessions/", "W2"), ("src/graftling/records", "W2"),
    ("src/graftling/process.py", "W1"), ("src/graftling/control.py", "W1"),
    ("src/graftling/member_processes.py", "W5"), ("src/graftling/tool_descendants.py", "W5"),
    ("src/graftling/claude/execution.py", "W3"), ("src/graftling/pi/execution.py", "W3"),
    ("src/graftling/dsh/", "W3"), ("src/graftling/codex/", "W7"),
    ("src/graftling/claude/host.py", "W8"), ("src/graftling/models.py", "W6"),
]


def load(file):
    with open(file, encoding="utf-8") as handle:
        return json.load(handle)


def get(file, keys):
    value = load(file)
    for key in keys.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    print("" if value is None else value)


# ------------------------------------------------------------------ workflow


def wfcheck(file, branch, job_name, steps):
    import yaml

    text = open(file, encoding="utf-8").read()
    doc = yaml.safe_load(text)
    bad = []

    def check(ok, good, problem):
        print(("PASS: " + good) if ok else ("FAIL: " + problem))
        if not ok:
            bad.append(problem)

    on = doc.get("on", doc.get(True)) or {}
    push = (on.get("push") or {}) if isinstance(on, dict) else {}
    branches = push.get("branches") or []
    check(sorted(branches) == sorted([branch, "dev"]), f"push branches are exactly {branch} and dev",
          f"push branches are {branches}, not [{branch}, dev]")
    check(isinstance(on, dict) and "workflow_dispatch" in on and set(on) <= {"push", "workflow_dispatch"},
          "triggers: push and workflow_dispatch only", f"triggers are {sorted(map(str, on))}")
    check(doc.get("permissions") == {"contents": "read"}, "permissions: contents: read",
          f"permissions are {doc.get('permissions')}")
    check("secrets." not in text and "secrets[" not in text, "no secrets reference", "the workflow references secrets")
    check("GITHUB_TOKEN" not in text and "github.token" not in text, "no token reference", "the workflow names a token")
    job = (doc.get("jobs") or {}).get(job_name) or {}
    check(job.get("runs-on") == "windows-latest", "job runs on windows-latest", f"runs-on is {job.get('runs-on')}")
    check(isinstance(job.get("timeout-minutes"), int), f"job timeout-minutes {job.get('timeout-minutes')}",
          "job has no timeout-minutes")
    check(str((job.get("env") or {}).get("PYTHONUTF8")) == "1", "PYTHONUTF8=1", "PYTHONUTF8 is not 1")
    items = job.get("steps") or []
    uses = [step["uses"] for step in items if "uses" in step]
    check(bool(uses) and all(SHA_PIN.match(item) for item in uses), "every action pinned to a 40-hex SHA: " + ", ".join(uses),
          "unpinned actions: " + ", ".join(item for item in uses if not SHA_PIN.match(item)))
    names = [step.get("name") for step in items]
    checkout = next((i for i, step in enumerate(items) if str(step.get("uses", "")).startswith("actions/checkout@")), None)
    symlinks = next((i for i, step in enumerate(items) if "core.symlinks true" in str(step.get("run", ""))), None)
    check(symlinks is not None and checkout is not None and symlinks < checkout,
          "core.symlinks true is set before the checkout", "core.symlinks true is not set before the checkout")
    check(checkout is not None and (items[checkout].get("with") or {}).get("persist-credentials") is False,
          "checkout has persist-credentials: false", "checkout keeps credentials")
    check(any("LinkType" in str(step.get("run", "")) and "SymbolicLink" in str(step.get("run", "")) for step in items),
          "a step fails unless the linked documents are symbolic links", "no step checks the symbolic links")
    run_text = "\n".join(str(step.get("run", "")) for step in items)
    check(re.search(r"\benv\b\s*(\||$)|Get-ChildItem\s+env:|\bprintenv\b|\bset\s*$", run_text, re.M) is None,
          "no step prints the whole environment", "a step prints the environment")
    for name in steps:
        check(name in names, f"step named: {name}", f"no step named: {name}")
    tests = next((step for step in items if step.get("name") == steps[-2]), {})
    command = str(tests.get("run", ""))
    check("-p no:cacheprovider" in command and "--junitxml=" in command and "-x" not in command.split()
          and "--maxfail" not in command, "the suite step runs pytest -p no:cacheprovider --junitxml, never stopping early",
          "the suite step does not run the whole suite with a JUnit file")
    check(isinstance(tests.get("timeout-minutes"), int), f"suite step timeout-minutes {tests.get('timeout-minutes')}",
          "the suite step has no timeout-minutes")
    upload = next((step for step in items if step.get("name") == steps[-1]), {})
    check(str(upload.get("if", "")).startswith("always()") and "retention-days" in (upload.get("with") or {}),
          f"upload runs always() with retention {(upload.get('with') or {}).get('retention-days')} days",
          "the upload is not always() with a retention")
    sys.exit(1 if bad else 0)


# ------------------------------------------------------------------ expected list


def read_expected(file):
    """Return ({nodeid: (origin, task, note)}, {skip reason: note}); raise ValueError naming the line."""
    fails, skips = {}, {}
    with open(file, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "fail" and len(parts) >= 4 and "::" in parts[1]:
                if parts[1] in fails:
                    raise ValueError(f"{file}:{number}: {parts[1]} listed twice")
                fails[parts[1]] = (parts[2], parts[3], parts[4] if len(parts) > 4 else "")
            elif parts[0] == "skip-allowed" and len(parts) >= 2 and parts[1]:
                if parts[1].startswith(PREFIX):
                    raise ValueError(f"{file}:{number}: POSIX-only skips need no entry")
                skips[parts[1]] = parts[2] if len(parts) > 2 else ""
            else:
                raise ValueError(f"{file}:{number}: not 'fail<TAB>nodeid<TAB>origin<TAB>task[<TAB>note]' "
                                 f"or 'skip-allowed<TAB>reason[<TAB>note]': {line[:120]}")
    return fails, skips


def expected(file):
    try:
        fails, skips = read_expected(file)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        sys.exit(1)
    tasks = Counter(task for _, task, _ in fails.values())
    print(f"PASS: {file} parses: {len(fails)} expected Windows failures "
          f"({', '.join(f'{k} {v}' for k, v in sorted(tasks.items())) or 'none'}), {len(skips)} allowed environment skips")


# ------------------------------------------------------------------ runs and jobs


def run_line(run):
    return "\t".join(str(x) for x in ("RUN", run.get("path"), run["id"], run.get("status"), run.get("conclusion") or "-",
                                       run.get("html_url"), run.get("event"), run.get("run_attempt", 1),
                                       run.get("head_sha"), run.get("name")))


def runs(file, path, event):
    latest = None
    for run in load(file).get("workflow_runs", []):
        if run.get("path", "") == path and event in ("-", run.get("event")):
            if latest is None or run["id"] > latest["id"]:
                latest = run
        else:
            print("OTHER", run.get("path"), run["id"], run.get("event"), run.get("status"), run.get("conclusion"),
                  run.get("html_url"), sep="\t")
    print(run_line(latest) if latest else "MISSING\t" + path)


def newrun(file, path, event, old):
    found = [run for run in load(file).get("workflow_runs", [])
             if run.get("path") == path and run.get("event") == event and str(run["id"]) not in set(old)]
    print(run_line(max(found, key=lambda run: run["id"])) if found else "MISSING\t" + path)


def jobs(file, config):
    cfg = load(config)
    setup, suite, upload = cfg["setup"], cfg["suite"], cfg["upload"]
    found = load(file).get("jobs", [])
    job = next((j for j in found if j.get("name") == cfg["job"]), None)
    problems = []
    for j in found:
        print("JOB", j.get("name"), "|", j.get("status"), "|", j.get("conclusion"), "|", j.get("html_url"))
        if j is not job:
            continue
        for s in j.get("steps", []):
            name, concl = s.get("name"), s.get("conclusion")
            if name in setup:
                mark = "setup: must succeed"
            elif name == suite:
                mark = "suite: success or failure (results judged from JUnit)"
            elif name == upload:
                mark = "upload: must succeed"
            else:
                mark = "other: success or skipped"
                if concl not in ("success", "skipped"):
                    problems.append(f"step {name!r} is {concl}")
            print("  step %2s | %-9s | %s | %s" % (s.get("number"), concl, name, mark))
    if job is None:
        problems.append(f"no {cfg['job']} job")
    else:
        seen = {s.get("name"): s.get("conclusion") for s in job.get("steps", [])}
        for name in setup + [upload]:
            if name not in seen:
                problems.append(f"step {name!r} is missing")
            elif seen[name] != "success":
                problems.append(f"step {name!r} is {seen[name]}")
        if suite not in seen:
            problems.append(f"step {suite!r} is missing")
        elif seen[suite] not in ("success", "failure"):
            problems.append(f"step {suite!r} is {seen[suite]} (did not run the suite to its end)")
    print("JUDGE", "FAIL" if problems else "PASS",
          "; ".join(problems) or f"{len(setup)} setup steps and the upload succeeded; the suite step ran")


# ------------------------------------------------------------------ JUnit


def nodeid(case):
    """pytest's node id from an xunit1 testcase: file, classes below the module, name."""
    file = case.get("file", "").replace("\\", "/")
    module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
    classname = case.get("classname", "")
    inner = classname[len(module) + 1:] if module and classname.startswith(module + ".") else ""
    return "::".join(part for part in (file or classname, *inner.split(".")) if part) + "::" + case.get("name", "")


FRAME = re.compile(r"((?:src|tests)[\\/][\w\\/.-]+\.py):(\d+)")


def origin(text, case):
    """The deepest graftling frame of a failure, else the deepest test frame, else the test's own line."""
    frames = [(path.replace("\\", "/"), line) for path, line in FRAME.findall(text or "")]
    product = [frame for frame in frames if frame[0].startswith("src/graftling/")]
    if product:
        return "%s:%s" % product[-1]
    if frames:
        return "%s:%s" % frames[-1]
    line = case.get("line")
    return f"{case.get('file', '?')}:{int(line) + 1 if line and line.isdigit() else '?'}"


def suggest(where):
    for prefix, task in ORIGIN_TASK:
        if where.startswith(prefix):
            return task + "?"
    return "?"


def junit(directory, expected_file, candidate):
    problems = []
    path = os.path.join(directory, "junit.xml")
    try:
        code = open(os.path.join(directory, "pytest-exit-code.txt"), encoding="utf-8-sig").read().strip()
    except OSError:
        code = "missing"
    try:
        environment = load(os.path.join(directory, "environment.json"))
        print("runner:", " | ".join(f"{k}={environment.get(k)}" for k in
                                    ("os", "image", "image_version", "arch", "python", "pytest", "node", "codepage")))
    except (OSError, ValueError):
        print("runner: environment.json missing or unreadable")
    print(f"pytest exit code: {code}")
    if code not in ("0", "1"):
        problems.append(f"pytest exit code {code}: the suite did not run to its end (0 or 1 expected)")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        print(f"JUDGE FAIL no readable JUnit file: {error}")
        return
    try:
        fails_expected, skips_allowed = read_expected(expected_file)
    except (OSError, ValueError) as error:
        print(f"JUDGE FAIL expected list: {error}")
        return
    outcome, detail, cases = {}, {}, {}
    for case in root.iter("testcase"):
        node = nodeid(case)
        cases[node] = case
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None or error is not None:
            item = failure if failure is not None else error
            outcome[node] = "fail" if failure is not None else "error"
            detail[node] = ((item.get("message") or "").splitlines() or [""])[0][:200], origin(item.text, case)
        elif skipped is not None:
            outcome[node] = "skip"
            detail[node] = (skipped.get("message") or "", "")
        else:
            outcome[node] = "pass"
    counts = Counter(outcome.values())
    total = len(outcome)
    print(f"collected in JUnit: {total} | passed {counts['pass']} | failed {counts['fail']} | errors {counts['error']} | "
          f"skipped {counts['skip']}")
    if total == 0:
        problems.append("JUnit holds no test")
    collection = [node for node, case in cases.items()
                  if (case.find("error") is not None and case.find("error").get("message") == "collection failure")]
    if collection:
        problems.append(f"{len(collection)} collection errors: " + ", ".join(collection[:5]))

    posix = {node: detail[node][0] for node, o in outcome.items() if o == "skip" and detail[node][0].startswith(PREFIX)}
    environment_skips = {node: detail[node][0] for node, o in outcome.items()
                         if o == "skip" and detail[node][0] in skips_allowed}
    other_skips = {node: detail[node][0] for node, o in outcome.items()
                   if o == "skip" and node not in posix and node not in environment_skips}
    by_module = Counter(node.split("::")[0] for node in posix)
    print(f"--- POSIX-only skips: {len(posix)} in {len(by_module)} modules")
    for module, count in sorted(by_module.items()):
        print(f"  {count:4d}  {module}")
    for reason, count in Counter(posix.values()).most_common():
        print(f"  reason x{count}: {reason[len(PREFIX):][:160]}")
    print(f"--- allowed environment skips (not Windows-specific): {len(environment_skips)}")
    for reason, count in Counter(environment_skips.values()).most_common():
        print(f"  x{count}: {reason}")
    print(f"--- skips without the {PREFIX!r} prefix and not allowed: {len(other_skips)}")
    for node, reason in sorted(other_skips.items()):
        print(f"  {node} | {reason}")

    failing = {node for node, o in outcome.items() if o in ("fail", "error")}
    unexpected = sorted(failing - set(fails_expected))
    passed_now = sorted(node for node in fails_expected if outcome.get(node) == "pass")
    not_seen = sorted(node for node in fails_expected if outcome.get(node) not in ("fail", "error", "pass"))
    print(f"--- expected Windows failures: {len(fails_expected)}; observed failures and errors: {len(failing)} "
          f"({len(failing & set(fails_expected))} as expected)")
    print(f"--- unexpected failures: {len(unexpected)}")
    for node in unexpected:
        print(f"  {outcome[node].upper()} {node} | origin {detail[node][1]} ({suggest(detail[node][1])}) | {detail[node][0]}")
    print(f"--- unexpected passes (listed as failing, passed): {len(passed_now)}")
    for node in passed_now:
        print(f"  PASS {node} | listed origin {fails_expected[node][0]} {fails_expected[node][1]}")
    print(f"--- listed failures that were skipped or not collected: {len(not_seen)}")
    for node in not_seen:
        print(f"  {outcome.get(node, 'absent').upper()} {node} | {detail.get(node, ('', ''))[0][:120]}")
    if other_skips:
        problems.append(f"{len(other_skips)} skips without the POSIX-only prefix")
    if unexpected:
        problems.append(f"{len(unexpected)} unexpected failures")
    if passed_now:
        problems.append(f"{len(passed_now)} unexpected passes")
    if not_seen:
        problems.append(f"{len(not_seen)} listed failures skipped or absent")

    # The observed list, in the expected file's format: listed entries keep their origin and Task.
    with open(candidate, "w", encoding="utf-8") as out:
        out.write("# Observed on the Windows runner; generated by wincheck.py junit for a correction round.\n"
                  "# Entries kept from the expected list keep their origin and Task; new ones carry a suggested Task\n"
                  "# ending in '?' that must be decided before this replaces windows-expected.txt.\n")
        for reason, note in skips_allowed.items():
            out.write(f"skip-allowed\t{reason}\t{note}\n")
        for reason in sorted(set(other_skips.values())):
            out.write(f"skip-allowed\t{reason}\tNEW: decide (environment skip, or a missing POSIX-only mark)\n")
        for node in sorted(failing):
            if node in fails_expected:
                where, task, note = fails_expected[node]
            else:
                where, task, note = detail[node][1], suggest(detail[node][1]), "NEW: " + detail[node][0][:150]
            out.write(f"fail\t{node}\t{where}\t{task}\t{note}\n")
    print(f"observed list written: {candidate}")
    print("JUDGE", "FAIL" if problems else "PASS", "; ".join(problems) or
          f"{total} tests: {counts['pass']} passed, {len(failing)} failed as listed, {len(posix)} POSIX-only skips, "
          f"{len(environment_skips)} environment skips")


if __name__ == "__main__":
    command, args = sys.argv[1], sys.argv[2:]
    if command == "wfcheck":
        wfcheck(args[0], args[1], args[2], args[3:])
    elif command == "expected":
        expected(args[0])
    elif command == "get":
        get(args[0], args[1])
    elif command == "runs":
        runs(args[0], args[1], args[2])
    elif command == "newrun":
        newrun(args[0], args[1], args[2], args[3:])
    elif command == "jobs":
        jobs(args[0], args[1])
    elif command == "junit":
        junit(args[0], args[1], args[2])
    else:
        sys.exit(f"unknown command {command}")
