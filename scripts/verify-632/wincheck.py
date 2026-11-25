"""Task 632 step helper: reads the graftling Windows workflow, GitHub REST JSON saved by steps.zsh and the
downloaded JUnit evidence; prints plain lines. Modelled on verify-623/ghjson.py.

Run as: python -I wincheck.py <command> <args...>. Standard library only except `wfcheck`, which needs PyYAML.
  wfcheck FILE BRANCH JOB STEP...     the workflow's triggers, permissions, secrets, pins, env and step names
  expected FILE                       the expected list parses; counts of its entries
  get FILE KEY[.KEY...]               value at a key path (empty when absent)
  runs FILE PATH EVENT                newest run of PATH (EVENT or '-' for any event): RUN line, or MISSING; OTHER lines
  newrun FILE PATH EVENT OLD_ID...    newest run of PATH and EVENT whose id is not an OLD_ID: RUN line, or MISSING
  jobs FILE CONFIG                    every step of the job with its conclusion; last line JUDGE PASS|FAIL <reason>
  junit DIR EXPECTED CANDIDATE [TESTFILES]
                                      DIR is the artifact of .github/run_test_files.py (files.json, junit/*.xml,
                                      logs/*.txt, run-exit-code.txt): a FILES PASS|FAIL line for the per-file records
                                      (every file in TESTFILES ended or was stopped and recorded as hung), then the
                                      merged JUnit results and hangs against EXPECTED; writes CANDIDATE (the observed
                                      list, for a correction round); last line JUDGE PASS|FAIL <reason>
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
    check(re.search(r"^\s*python \.github/run_test_files\.py --out test-results/windows --file-limit \d+ --total-limit \d+\s*$",
                    command, re.M) is not None and "run-exit-code.txt" in command,
          "the suite step runs every test file through .github/run_test_files.py with file and total limits",
          "the suite step does not run .github/run_test_files.py --out test-results/windows --file-limit N --total-limit N")
    limits = re.search(r"--file-limit (\d+) --total-limit (\d+)", command)
    if limits:
        check(int(limits.group(2)) < 60 * int(tests.get("timeout-minutes") or 0),
              f"total limit {limits.group(2)} s is inside the step's {tests.get('timeout-minutes')} minutes",
              f"total limit {limits.group(2)} s is not inside the step's timeout")
    check(isinstance(tests.get("timeout-minutes"), int), f"suite step timeout-minutes {tests.get('timeout-minutes')}",
          "the suite step has no timeout-minutes")
    upload = next((step for step in items if step.get("name") == steps[-1]), {})
    check(str(upload.get("if", "")).startswith("always()") and "retention-days" in (upload.get("with") or {}),
          f"upload runs always() with retention {(upload.get('with') or {}).get('retention-days')} days",
          "the upload is not always() with a retention")
    sys.exit(1 if bad else 0)


# ------------------------------------------------------------------ expected list


def read_expected(file):
    """Return ({nodeid: (origin, task, note)} for fail, the same for hang, {skip reason: note}).

    Raises ValueError naming the line."""
    fails, hangs, skips = {}, {}, {}
    with open(file, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] in ("fail", "hang") and len(parts) >= 4 and "::" in parts[1]:
                table = fails if parts[0] == "fail" else hangs
                if parts[1] in fails or parts[1] in hangs:
                    raise ValueError(f"{file}:{number}: {parts[1]} listed twice")
                table[parts[1]] = (parts[2], parts[3], parts[4] if len(parts) > 4 else "")
            elif parts[0] == "skip-allowed" and len(parts) >= 2 and parts[1]:
                if parts[1].startswith(PREFIX):
                    raise ValueError(f"{file}:{number}: POSIX-only skips need no entry")
                skips[parts[1]] = parts[2] if len(parts) > 2 else ""
            else:
                raise ValueError(f"{file}:{number}: not 'fail|hang<TAB>nodeid<TAB>origin<TAB>task[<TAB>note]' "
                                 f"or 'skip-allowed<TAB>reason[<TAB>note]': {line[:120]}")
    return fails, hangs, skips


def expected(file):
    try:
        fails, hangs, skips = read_expected(file)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        sys.exit(1)
    tasks = Counter(task for _, task, _ in [*fails.values(), *hangs.values()])
    print(f"PASS: {file} parses: {len(fails)} expected Windows failures and {len(hangs)} expected hangs "
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


# A frame as pytest prints it (`src\graftling\x.py:68: in f`) or as Python does (`File "D:\...\src\graftling\x.py",
# line 68`); Windows writes backslashes (run 45608819873). In order of appearance: outermost first, deepest last.
FRAME = re.compile(r'File "(?P<a>[^"]*?(?:src|tests)[\\/][^"]+?\.py)", line (?P<al>\d+)'
                   r'|(?P<b>(?:src|tests)[\\/][\w\\/.-]+\.py):(?P<bl>\d+)')


def posix_path(path):
    """A path as the expected list writes it: '/' separators, from 'src/graftling/' or 'tests/' on."""
    path = (path or "").replace("\\", "/")
    for root in ("src/graftling/", "tests/"):
        if path.startswith(root):
            return path
        if "/" + root in path:
            return root + path.split("/" + root, 1)[1]
    return path


def frames(text):
    return [(posix_path(m.group("a") or m.group("b")), m.group("al") or m.group("bl")) for m in FRAME.finditer(text or "")]


def origin(text, case, log_section=""):
    """Where a failure comes from, and how that was found.

    The deepest graftling frame of the JUnit text; else the deepest graftling frame of the test's section in the
    file's log (captured output can hold a background thread's traceback); else the deepest test frame, which is a
    test assertion with no graftling frame; else the test's own line."""
    found = frames(text)
    product = [frame for frame in found if frame[0].startswith("src/graftling/")]
    if product:
        return "%s:%s" % product[-1], "junit"
    logged = [frame for frame in frames(log_section) if frame[0].startswith("src/graftling/")]
    if logged:
        return "%s:%s" % logged[-1], "log"
    tests = [frame for frame in found if frame[0].startswith("tests/")]
    if tests:
        return "%s:%s" % tests[-1], "test assertion, no graftling frame"
    line = case.get("line")
    return (f"{posix_path(case.get('file')) or '?'}:{int(line) + 1 if line and line.isdigit() else '?'}",
            "test line, no frame")


HEADER = re.compile(r"^_{3,} (.+?) _{3,}\s*$")


def log_sections(text):
    """{title: text} of the failure and error sections of a pytest log (titles as pytest prints them)."""
    sections, title, lines = {}, None, []
    for line in (text or "").splitlines():
        header = HEADER.match(line)
        if header or line.startswith("====="):
            if title is not None:
                sections.setdefault(title, "\n".join(lines))
            title, lines = (header.group(1) if header else None), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        sections.setdefault(title, "\n".join(lines))
    return sections


def section_for(sections, case):
    """The log section of this testcase: pytest titles it 'name', 'Class.name' or 'ERROR at setup of name'."""
    name = case.get("name", "")
    for title, text in sections.items():
        if title == name or title.endswith("." + name) or title.endswith(" of " + name):
            return text
    return ""


def suggest(where):
    for prefix, task in ORIGIN_TASK:
        if where.startswith(prefix):
            return task + "?"
    return "?"


DUMP_FRAME = re.compile(r'File "([^"]+)", line (\d+)')


def dump_origin(log_text, test_file):
    """Deepest graftling frame of the test's thread in the last faulthandler dump, else its deepest test frame."""
    dump = log_text.rsplit("Timeout (", 1)
    if len(dump) < 2:
        return None
    stem = test_file.replace("\\", "/").rsplit("/", 1)[-1]
    for block in re.split(r"\n\s*(?:Thread|Current thread) 0x", dump[1]):
        frames = []   # most recent call first, as faulthandler prints them
        for path, line in DUMP_FRAME.findall(block):
            path = path.replace("\\", "/")
            for root in ("src/graftling/", "tests/"):
                if root in path:
                    frames.append((root + path.split(root, 1)[1], line))
        if any(path.endswith(stem) for path, _ in frames):
            product = [frame for frame in frames if frame[0].startswith("src/graftling/")]
            return "%s:%s" % (product or [frame for frame in frames if frame[0].startswith("tests/")])[0]
    return None


def files_check(directory, test_files):
    """Per-file records: every listed test file ended, or was stopped and recorded as hung.

    Returns (problems, observed hangs {nodeid: (origin, record)}, junit paths, files that hung, {file: log path}).
    Paths in files.json are relative to DIR; a Windows runner writes them with backslashes (run 45608819873)."""
    problems, hangs, paths, hung_files, logs = [], {}, [], set(), {}
    try:
        code = open(os.path.join(directory, "run-exit-code.txt"), encoding="utf-8-sig").read().strip()
    except OSError:
        code = "missing"
    print(f"run_test_files exit code: {code}")
    if code not in ("0", "1"):
        problems.append(f"run_test_files exit code {code}: the driver did not finish (0 or 1 expected)")
    try:
        records = load(os.path.join(directory, "files.json"))["files"]
    except (OSError, ValueError, KeyError) as error:
        return problems + [f"no per-file records (files.json): {error}"], hangs, paths, hung_files, logs
    for record in records:
        for key in ("file", "junit", "log"):
            if record.get(key):
                record[key] = record[key].replace("\\", "/")
        if record.get("log"):
            logs[record["file"]] = os.path.join(directory, record["log"])
    seen = {record["file"] for record in records}
    if test_files is not None:
        missing = sorted(set(test_files) - seen)
        if missing:
            problems.append(f"{len(missing)} test files without a record: " + ", ".join(missing[:5]))
        extra = sorted(seen - set(test_files))
        if extra:
            print("NOTE: records for files not in the commit's tests/: " + ", ".join(extra[:5]))
    outcomes = Counter(record["outcome"] for record in records)
    print(f"--- test files: {len(records)} recorded | ended {outcomes['ended']} | hung {outcomes['hung']} | "
          f"not run {outcomes['not-run']}" + (f" | in the commit: {len(test_files)}" if test_files is not None else ""))
    for record in records:
        name = record["file"]
        if record["outcome"] == "ended":
            if record.get("exit_code") not in (0, 1):
                problems.append(f"{name} ended with pytest exit {record.get('exit_code')} (collection or internal error)")
                print(f"  ENDED exit {record.get('exit_code')} {record['elapsed_s']:7.1f} s  {name}")
            if record.get("junit") and os.path.isfile(os.path.join(directory, record["junit"])):
                paths.append(os.path.join(directory, record["junit"]))
            elif record.get("junit"):
                problems.append(f"{name}: its JUnit file {record['junit']} is not in the artifact")
            else:
                problems.append(f"{name} ended without its JUnit file")
            if not record.get("pipe_closed", True):
                print(f"  NOTE {name}: a leftover process held its output pipe open after pytest exited")
        elif record["outcome"] == "hung":
            hung_files.add(name)
            try:
                text = open(os.path.join(directory, record["log"]), encoding="utf-8", errors="replace").read()
            except (OSError, KeyError):
                text = ""
            node = record.get("last_started") or f"{name}::<no test started>"
            where = dump_origin(text, name) or f"{name}:?"
            hangs[node] = (where, record)
            print(f"  HUNG {record['elapsed_s']:7.1f} s  {name} | last started {node} | origin {where} | {record.get('stopped')}")
        else:
            problems.append(f"{name} was not run ({record.get('reason', record['outcome'])})")
            print(f"  NOT RUN {name} | {record.get('reason')}")
    slowest = sorted((r for r in records if r["outcome"] == "ended"), key=lambda r: -r["elapsed_s"])[:5]
    print("  slowest ended files: " + ", ".join(f"{r['file']} {r['elapsed_s']} s" for r in slowest))
    return problems, hangs, paths, hung_files, logs


def junit(directory, expected_file, candidate, test_files_list=None):
    problems = []
    try:
        environment = load(os.path.join(directory, "environment.json"))
        print("runner:", " | ".join(f"{k}={environment.get(k)}" for k in
                                    ("os", "image", "image_version", "arch", "python", "pytest", "node", "codepage")))
    except (OSError, ValueError):
        print("runner: environment.json missing or unreadable")
    test_files = None
    if test_files_list:
        test_files = [line.strip() for line in open(test_files_list, encoding="utf-8") if line.strip()]
    mechanics, hangs, paths, hung_files, logs = files_check(directory, test_files)
    sections = {}   # test file -> its log's failure sections, read when first needed

    def log_section(case):
        file = posix_path(case.get("file"))
        if file not in sections:
            try:
                sections[file] = log_sections(open(logs[file], encoding="utf-8", errors="replace").read())
            except (KeyError, OSError):
                sections[file] = {}
        return section_for(sections[file], case)
    print("FILES", "FAIL" if mechanics else "PASS", "; ".join(mechanics) or
          "every test file ended or was stopped and recorded as hung")
    try:
        fails_expected, hangs_expected, skips_allowed = read_expected(expected_file)
    except (OSError, ValueError) as error:
        print(f"JUDGE FAIL expected list: {error}")
        return
    cases_all = []
    for path in paths:
        try:
            cases_all.extend(ET.parse(path).getroot().iter("testcase"))
        except (OSError, ET.ParseError) as error:
            problems.append(f"unreadable JUnit file {path}: {error}")
    print(f"merged JUnit files: {len(paths)}")
    outcome, detail, cases = {}, {}, {}
    for case in cases_all:
        node = nodeid(case)
        cases[node] = case
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None or error is not None:
            item = failure if failure is not None else error
            outcome[node] = "fail" if failure is not None else "error"
            where, how = origin(item.text, case)
            if how != "junit":
                found = origin(item.text, case, log_section(case))
                where, how = found if found[1] == "log" else (where, how)
            detail[node] = (((item.get("message") or "").splitlines() or [""])[0][:200], where, how)
        elif skipped is not None:
            outcome[node] = "skip"
            detail[node] = (skipped.get("message") or "", "", "")
        else:
            outcome[node] = "pass"
    counts = Counter(outcome.values())
    total = len(outcome)
    print(f"collected in JUnit: {total} | passed {counts['pass']} | failed {counts['fail']} | errors {counts['error']} | "
          f"skipped {counts['skip']}")
    if total == 0 and not hangs:
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
    print(f"--- skips without the {PREFIX!r} prefix and not allowed: {len(other_skips)}, by reason:")
    for reason, count in Counter(other_skips.values()).most_common():
        print(f"  x{count}: {reason}")
    print("  by test:")
    for node, reason in sorted(other_skips.items()):
        print(f"  {node} | {reason}")

    # Hangs: the last started test of each stopped file, against the `hang` entries.
    unexpected_hangs = sorted(set(hangs) - set(hangs_expected))
    ended_now = sorted(node for node in hangs_expected if node not in hangs)
    print(f"--- expected hangs: {len(hangs_expected)}; observed hangs: {len(hangs)} "
          f"({len(set(hangs) & set(hangs_expected))} as expected)")
    print(f"--- unexpected hangs: {len(unexpected_hangs)}")
    for node in unexpected_hangs:
        print(f"  HANG {node} | origin {hangs[node][0]} ({suggest(hangs[node][0])}) | stopped after "
              f"{hangs[node][1]['elapsed_s']} s")
    print(f"--- listed hangs that did not hang: {len(ended_now)}")
    for node in ended_now:
        print(f"  {outcome.get(node, 'absent').upper()} {node} | listed origin {hangs_expected[node][0]} {hangs_expected[node][1]}")

    def in_hung_file(node):
        return node.split("::")[0] in hung_files

    failing = {node for node, o in outcome.items() if o in ("fail", "error")}
    unexpected = sorted(failing - set(fails_expected))
    passed_now = sorted(node for node in fails_expected if outcome.get(node) == "pass")
    unjudged = sorted(node for node in fails_expected if node not in outcome and in_hung_file(node))
    not_seen = sorted(node for node in fails_expected if outcome.get(node) not in ("fail", "error", "pass")
                      and node not in unjudged)
    print(f"--- expected Windows failures: {len(fails_expected)}; observed failures and errors: {len(failing)} "
          f"({len(failing & set(fails_expected))} as expected)")
    print(f"--- unexpected failures: {len(unexpected)}")
    for node in unexpected:
        print(f"  {outcome[node].upper()} {node} | origin {detail[node][1]} ({suggest(detail[node][1])}; from "
              f"{detail[node][2]}) | {detail[node][0]}")
    print("    origins of the unexpected failures: " + ", ".join(
        f"{how} {count}" for how, count in Counter(detail[node][2] for node in unexpected).most_common()))
    print(f"--- unexpected passes (listed as failing, passed): {len(passed_now)}")
    for node in passed_now:
        print(f"  PASS {node} | listed origin {fails_expected[node][0]} {fails_expected[node][1]}")
    print(f"--- listed failures that were skipped or not collected: {len(not_seen)}")
    for node in not_seen:
        print(f"  {outcome.get(node, 'absent').upper()} {node} | {detail.get(node, ('', ''))[0][:120]}")
    if unjudged:
        print(f"--- listed failures not judged because their file hung (no JUnit for it): {len(unjudged)}")
        for node in unjudged:
            print(f"  {node}")
    if unexpected_hangs:
        problems.append(f"{len(unexpected_hangs)} unexpected hangs")
    if ended_now:
        problems.append(f"{len(ended_now)} listed hangs did not hang")
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
                note += f" | observed: {detail[node][0][:150]} (at {detail[node][1]}, from {detail[node][2]})"
            else:
                tag = "" if detail[node][2] == "junit" else f" [origin from {detail[node][2]}]"
                where, task, note = detail[node][1], suggest(detail[node][1]), "NEW: " + detail[node][0][:150] + tag
            out.write(f"fail\t{node}\t{where}\t{task}\t{note}\n")
        for node in unjudged:
            where, task, note = fails_expected[node]
            out.write(f"fail\t{node}\t{where}\t{task}\t{note} (not judged: its file hung)\n")
        for node in sorted(hangs):
            if node in hangs_expected:
                where, task, note = hangs_expected[node]
            else:
                where, task = hangs[node][0], suggest(hangs[node][0])
                note = f"NEW: file stopped after {hangs[node][1]['elapsed_s']} s"
            out.write(f"hang\t{node}\t{where}\t{task}\t{note}\n")
    print(f"observed list written: {candidate}")
    print("JUDGE", "FAIL" if problems else "PASS", "; ".join(problems) or
          f"{total} tests: {counts['pass']} passed, {len(failing)} failed as listed, {len(hangs)} hangs as listed, "
          f"{len(posix)} POSIX-only skips, {len(environment_skips)} environment skips")


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
        junit(args[0], args[1], args[2], args[3] if len(args) > 3 else None)
    else:
        sys.exit(f"unknown command {command}")
