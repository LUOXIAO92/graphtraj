"""Task 652 step helper, beside verify-632/wincheck.py (which steps.zsh also runs, by reference).

Run as: python -I wincheck652.py <command> <args...>. Standard library only except `wfdiff`, which needs PyYAML.
  wfdiff BASE_WF HEAD_WF   the workflow at the bundle head is the one at BASE (graftling dev b179984) with its push
                           branches line gaining exactly agent/652-graftling-windows-claude-host-polish and one job,
                           claude-real-entry, appended at the end; windows-tests and dsh-windows-tests are unchanged;
                           the new job runs only on this branch or by hand, pins every action, names no credential or
                           provider variable, checks the Claude Code binary's SHA-256 against the release manifest,
                           gates on .github/claude_real_entry.py and uploads its evidence always()
  as632 WF OUT             write to OUT the workflow with its push branches line (the base's or the head's) set back
                           to 632's, so 632's wfcheck judges the windows-tests job and the whole file unchanged
  jobstate JOBS NAME       one job of a saved jobs response: every step with its conclusion; last line
                           JOBSTATE PASS|FAIL (every step succeeded or was skipped, and the job succeeded)
  realentry DIR            the claude-real-entry artifact DIR: every item of results.json, the platform and Claude
                           Code version; last line REALENTRY PASS|FAIL (each named item present and PASS)
  newtests DIR LIST        every node id in LIST passed in the merged per-file JUnit files of the artifact DIR (not
                           failed, errored, skipped or absent); last line NEWTESTS PASS|FAIL
  mcompare BASE CAND       the Mac step: the market item of the base run and of the candidate run (results.json of
                           each) both PASS with the same init plugins and server status; last line MCOMPARE PASS|FAIL
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

BRANCH = "agent/652-graftling-windows-claude-host-polish"
# graftling dev b179984's push branches, in the workflow's order; the candidate appends only its own branch.
BASE_BRANCHES = ["agent/632-graftling-windows-ci", "agent/633-graftling-windows-process",
                 "agent/634-graftling-windows-durable-writes", "agent/635-graftling-windows-process-tree",
                 "agent/638-graftling-windows-paths-encoding", "dev", "agent/636-graftling-windows-named-pipe",
                 "agent/637-graftling-windows-process-listing", "agent/639-graftling-windows-codex",
                 "agent/647-graftling-windows-claude", "agent/648-graftling-windows-pi", "agent/649-graftling-windows-dsh"]
BRANCHES = BASE_BRANCHES + [BRANCH]
BASE_LINE = "    branches: [" + ", ".join(BASE_BRANCHES) + "]"
HEAD_LINE = "    branches: [" + ", ".join(BRANCHES) + "]"
LINE_632 = "    branches: [agent/632-graftling-windows-ci, dev]"
JOB = "claude-real-entry"
STEPS = ["Keep symbolic links on this runner", "Check out the commit under test", "Set up Python 3.13.7 x64",
         "Install graftling and pinned test tools", "Fetch Claude Code for win32-x64",
         "Run real Claude Code against graftling", "Retain the real Claude Code evidence"]
ARTIFACT = "graftling-claude-real-entry-${{ github.sha }}-${{ github.run_attempt }}"
# The items .github/claude_real_entry.py judges on Windows, by case and name.
ITEMS = [("market", "plugin installed"),
         ("market", "R2 native Windows: unsupported, configuration --write named"),
         ("untrusted", "R1 refusal names the plugin and folder trust"),
         ("caller", "R3 Bash-tool context step: refused as the same session"),
         ("caller", "trusted folder: the plugin loaded and subagents answered")]
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
CRED_PART = re.compile(r"(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$")
PROVIDER = re.compile(r"^(ANTHROPIC_|OPENAI_|DEEPSEEK_|CODEX_|CLAUDE_CODE_USE_|GRAFTLING_CONNECTION)|_BASE_URL$")


def wfdiff(base_file, head_file):
    """The head workflow is the base one with the branch added and one claude-real-entry job appended."""
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
    check(branches == BRANCHES, f"push branches are exactly dev's plus {BRANCH}", f"push branches are {branches}")
    prefix = base.replace(BASE_LINE + "\n", HEAD_LINE + "\n")
    appended = head[len(prefix):] if head.startswith(prefix) else None
    check(base.count(BASE_LINE + "\n") == 1 and appended is not None,
          "the base workflow is unchanged up to its end apart from the push branches line",
          "the workflow differs from the base before its end, beyond the push branches line")
    jobs = doc.get("jobs") or {}
    base_jobs = yaml.safe_load(base).get("jobs") or {}
    check(list(jobs) == ["windows-tests", "dsh-windows-tests", JOB], f"jobs are windows-tests, dsh-windows-tests, {JOB}",
          f"jobs are {list(jobs)}")
    for name in ("windows-tests", "dsh-windows-tests"):
        check(jobs.get(name) == base_jobs.get(name), f"the {name} job is the base one", f"the {name} job changed")
    check(appended is not None and re.match(rf"\n(  #[^\n]*\n)*  {JOB}:\n", appended) is not None,
          f"only the {JOB} job (with its comment) is appended", f"the appended text is not one {JOB} job")
    job = jobs.get(JOB) or {}
    condition = str(job.get("if", ""))
    check(condition == f"github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/{BRANCH}'",
          f"{JOB} runs only on {BRANCH} or by hand (dev's routine push run downloads nothing new)",
          f"{JOB} condition is {condition!r}")
    check(job.get("runs-on") == "windows-latest", f"{JOB} runs on windows-latest", f"runs-on is {job.get('runs-on')}")
    check(isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] <= 60,
          f"{JOB} timeout-minutes {job.get('timeout-minutes')}", f"{JOB} has no timeout-minutes up to 60")
    env = job.get("env") or {}
    check(str(env.get("PYTHONUTF8")) == "1", "PYTHONUTF8=1", "PYTHONUTF8 is not 1")
    named = [k for k in env if any(CRED_PART.search(p) for p in k.upper().split("_")) or PROVIDER.search(k.upper())]
    check(not named, f"job env names no credential or provider variable: {sorted(env)}", f"job env names {named}")
    check(env.get("CLAUDE_VERSION") == "2.1.314", "CLAUDE_VERSION 2.1.314 (650's Claude Code)",
          f"CLAUDE_VERSION is {env.get('CLAUDE_VERSION')}")
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
    run_text = "\n".join(str(s.get("run", "")) for s in items)
    check(re.search(r"\benv\b\s*(\||$)|Get-ChildItem\s+env:|\bprintenv\b|\bset\s*$", run_text, re.M) is None,
          "no step prints the whole environment", "a step prints the environment")
    fetch = str(next((s.get("run", "") for s in items if s.get("name") == STEPS[4]), ""))
    check("downloads.claude.ai/claude-code-releases/$env:CLAUDE_VERSION" in fetch and "Get-FileHash -Algorithm SHA256" in fetch
          and "throw" in fetch and ".platforms.'win32-x64'.checksum" in fetch,
          "Claude Code comes from its release source, its SHA-256 checked against the release manifest",
          "the fetch step does not check the binary against the release manifest")
    entry = next((s for s in items if s.get("name") == STEPS[5]), {})
    command = str(entry.get("run", ""))
    check("python .github/claude_real_entry.py --claude $env:CLAUDE_EXE --python $python" in command
          and re.search(r"^\s*exit \$code\s*$", command, re.M) is not None and "exit 0" not in command
          and "always()" not in str(entry.get("if", "")),
          "the real-entry step runs .github/claude_real_entry.py and exits with its code (gating)",
          "the real-entry step does not gate on .github/claude_real_entry.py")
    upload = next((s for s in items if s.get("name") == STEPS[6]), {})
    w = upload.get("with") or {}
    check(str(upload.get("if", "")).startswith("always()") and "retention-days" in w and w.get("name") == ARTIFACT
          and w.get("path") == "test-results/claude-real-entry/" and w.get("if-no-files-found") == "error",
          f"upload always() as {w.get('name')} with retention {w.get('retention-days')} days",
          "the upload is not always(), not named graftling-claude-real-entry-<sha>-<attempt> or without retention")
    sys.exit(1 if bad else 0)


def as632(file, out_file):
    """Write the workflow with its push branches line set back to 632's."""
    text = open(file, encoding="utf-8").read()
    found = [line for line in (BASE_LINE, HEAD_LINE) if text.count(line + "\n") == 1]
    if len(found) != 1:
        print(f"FAIL: {file} has neither exactly one {BASE_LINE.strip()!r} nor one {HEAD_LINE.strip()!r}")
        sys.exit(1)
    with open(out_file, "w", encoding="utf-8") as out:
        out.write(text.replace(found[0] + "\n", LINE_632 + "\n"))
    which = "the base's" if found[0] == BASE_LINE else "the head's (with 652)"
    print(f"PASS: push branches line is {which}; judged below with it set back to 632's")


def jobstate(jobs_file, name):
    """One job's steps; PASS when the job and every step succeeded or were skipped."""
    found = load(jobs_file).get("jobs", [])
    job = next((j for j in found if j.get("name") == name), None)
    problems = []
    if job is None:
        problems.append(f"no {name} job")
    else:
        print("JOB", job.get("name"), "|", job.get("status"), "|", job.get("conclusion"), "|", job.get("html_url"))
        for step in job.get("steps", []):
            if step.get("conclusion") not in ("success", "skipped"):
                problems.append(f"step {step.get('name')!r} is {step.get('conclusion')}")
            print("  step %2s | %-9s | %s" % (step.get("number"), step.get("conclusion"), step.get("name")))
        if job.get("conclusion") != "success":
            problems.append(f"the job is {job.get('conclusion')}")
    print("JOBSTATE", "FAIL" if problems else "PASS", f"{name}: " + ("; ".join(problems) or "every step succeeded"))


def results(directory):
    path = os.path.join(directory, "results.json")
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None


def realentry(directory):
    """Every item of the real-entry results; PASS when each named item is there and passed on win32."""
    document = results(directory)
    if document is None:
        print("REALENTRY FAIL no readable results.json in the artifact")
        return
    print(f"--- real Claude Code on the runner: claude {document.get('claude')}; graftling {document.get('graftling')}; "
          f"platform {document.get('platform')}")
    seen = {}
    for item in document.get("items", []):
        seen[(item.get("case"), item.get("item"))] = item.get("verdict")
        print(f"  {item.get('verdict')} {item.get('case')} | {item.get('item')} | {item.get('observable')}")
    problems = [f"{case}/{name}: {seen.get((case, name), 'absent')}" for case, name in ITEMS
                if seen.get((case, name)) != "PASS"]
    problems += [f"{case}/{name}: FAIL" for (case, name), verdict in seen.items()
                 if verdict != "PASS" and (case, name) not in ITEMS]
    if document.get("platform") != "win32":
        problems.append(f"platform {document.get('platform')}, not win32")
    print("REALENTRY", "FAIL" if problems else "PASS",
          "; ".join(problems) or f"{len(ITEMS)} items passed with real Claude Code {document.get('claude')}")


def newtests(directory, list_file):
    """Every node id of LIST passed in the artifact DIR's per-file JUnit files."""
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
    print(f"--- the 652 tests that must pass on Windows: {len(wanted)}")
    for node in wanted:
        state = outcome.get(node, "absent")
        passed += state == "passed"
        print(f"  {state.upper()} {node}")
    print(f"NEWTESTS {'PASS' if passed == len(wanted) else 'FAIL'} {passed} of {len(wanted)} 652 tests passed")


def market(document):
    item = next((i for i in (document or {}).get("items", []) if i.get("case") == "market" and i.get("item", "").startswith("R2")), None)
    if item is None:
        return None, None
    observable = item.get("observable", "")
    facts = re.search(r"init plugins (\[.*?\]); mcp_servers (\{.*?\})", observable)
    return item.get("verdict"), facts.groups() if facts else None


def mcompare(base_dir, candidate_dir):
    """Base and candidate: the marketplace plugin on the Mac passes with the same plugins and server status."""
    base, candidate = market(results(base_dir)), market(results(candidate_dir))
    print(f"  base      market: {base[0]} {base[1]}")
    print(f"  candidate market: {candidate[0]} {candidate[1]}")
    ok = base[0] == candidate[0] == "PASS" and base[1] is not None and base[1] == candidate[1]
    print("MCOMPARE", "PASS" if ok else "FAIL",
          "the marketplace plugin connects on macOS with the same init plugins and server status at base and candidate"
          if ok else "the base and candidate market items differ or did not pass")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"wfdiff": wfdiff, "as632": as632, "jobstate": jobstate, "realentry": realentry, "newtests": newtests,
     "mcompare": mcompare}[command](*rest)
