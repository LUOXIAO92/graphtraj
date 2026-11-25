"""Task 623 step helper (copied from verify-621): reads GitHub REST JSON saved by steps.zsh and downloaded evidence;
prints plain lines. 623 adds wfcheck and reads the Windows adoption.json fields (phase, captureError).

Run as: python -I ghjson.py <command> <args...>. Standard library only; reads files, writes nothing.
  wfcheck BASE HEAD BRANCH NAME  HEAD's workflow equals BASE with only Task 623's allowed lines changed
  get FILE KEY[.KEY...]          value at a key path (empty when absent)
  dispatch FILE                  contents-API JSON of the workflow: workflow_dispatch with a 'standard' mode option
  artifact FILE NAME             one line for the named artifact of a run (MISSING when absent)
  ids FILE                       ids of every run in a runs listing, space separated
  newrun FILE SHA [OLD_ID...]    newest run for SHA whose id is not an OLD_ID: id, status, conclusion, url
  pushruns FILE PATH...          newest push run per workflow path (RUN/MISSING lines), other workflows (OTHER)
  jobs FILE                      each job's conclusion and every step that did not succeed or skip
  evidence DIR                   files with sizes, then a summary of every evidence.json below DIR
"""
import base64
import difflib
import json
import os
import re
import sys


def load(file):
    with open(file, encoding="utf-8") as handle:
        return json.load(handle)


def get(file, keys):
    value = load(file)
    for key in keys.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    print("" if value is None else value)


def dispatch(file):
    doc = load(file)
    text = base64.b64decode(doc.get("content", "")).decode("utf-8", "replace")
    has_dispatch = re.search(r"^\s*workflow_dispatch:", text, re.M) is not None
    has_standard = re.search(r"^\s*options:\s*\[[^\]]*\bstandard\b", text, re.M) is not None
    print(f"workflow_dispatch: {'yes' if has_dispatch else 'no'}; mode option standard: {'yes' if has_standard else 'no'}")
    sys.exit(0 if has_dispatch and has_standard else 1)


def artifact(file, name):
    for item in load(file).get("artifacts", []):
        if item.get("name") == name:
            print("FOUND", item.get("id"), f"size={item.get('size_in_bytes')}", f"expired={str(item.get('expired')).lower()}",
                  f"expires_at={item.get('expires_at')}", sep="\t")
            return
    print("MISSING")


def ids(file):
    print(" ".join(str(run["id"]) for run in load(file).get("workflow_runs", [])))


def newrun(file, sha, old):
    old = set(old)
    found = [run for run in load(file).get("workflow_runs", []) if run.get("head_sha") == sha and str(run["id"]) not in old]
    if found:
        run = max(found, key=lambda run: run["id"])
        print(run["id"], run.get("status"), run.get("conclusion") or "-", run.get("html_url"), sep="\t")


def pushruns(file, wanted):
    """Newest push run per wanted workflow path (RUN/MISSING), then other workflows (OTHER)."""
    latest = {}
    for run in load(file).get("workflow_runs", []):
        name = run.get("path", "")
        if name in wanted and run.get("event") == "push":
            if name not in latest or (run["id"], run.get("run_attempt", 1)) > (latest[name]["id"], latest[name].get("run_attempt", 1)):
                latest[name] = run
        elif name not in wanted:
            print("OTHER", name, run["id"], run.get("event"), run.get("status"), run.get("conclusion"), run.get("html_url"), sep="\t")
    for name in wanted:
        run = latest.get(name)
        if run:
            print("RUN", name, run["id"], run.get("status"), run.get("conclusion") or "-", run.get("html_url"), sep="\t")
        else:
            print("MISSING", name, sep="\t")


def jobs(file):
    for job in load(file).get("jobs", []):
        print("  job:", job.get("name"), "|", job.get("status"), "|", job.get("conclusion"), "|", job.get("html_url"))
        for item in job.get("steps", []):
            if item.get("conclusion") not in ("success", "skipped"):
                print(f"    step {item.get('number')} {item.get('name')}: {item.get('status')} / {item.get('conclusion')}")


def evidence(root):
    found = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            print(f"  {os.path.getsize(full):>10}  {os.path.relpath(full, root)}")
            # macOS evidence.json; Linux ui-result.json and result.json; Windows adoption.json.
            if name in ("evidence.json", "ui-result.json", "result.json", "adoption.json"):
                found.append(full)
    if not found:
        print("no evidence.json, ui-result.json, result.json or adoption.json below", root)
    for full in found:
        print(f"--- {os.path.relpath(full, root)}")
        try:
            facts = load(full)
        except (OSError, ValueError) as error:
            print("  unreadable:", error)
            continue
        if not isinstance(facts, dict):
            print("  not a JSON object")
            continue
        print("  passed:", facts.get("passed", facts.get("uiPassed")), "| stage:", facts.get("stage", facts.get("phase", "-")))
        for key in ("failure", "error", "blockedReason", "failureScreenshotError", "cleanupError", "cleanupFailure",
                    "captureError", "cleanupKillError"):
            if facts.get(key):
                print(f"  {key}:")
                for line in str(facts[key]).splitlines()[:8]:
                    print("    " + line)
        steps = facts.get("steps") or []
        print(f"  steps: {len(steps)} recorded; last {min(len(steps), 6)}:")
        for line in steps[-6:]:
            print("    - " + str(line)[:200])
        print("  screenshots:", ", ".join(str(item) for item in facts.get("screenshots") or []) or "none")


# Task 623's only Windows-workflow edits besides the two common ones: the 619-only comment and ref expression go.
WIN_COMMENT = [
    "      # Task 619 only: its branch checks out the unreleased graftling Windows fix at this",
    "      # exact commit (pushed as graftling's agent/619-graftling-windows-import); the app",
    "      # is packaged from this same checkout (GRAFTLING_SOURCE). Other branches: GRAFTLING_REF.",
]
WIN_REF_OLD = ("          ref: ${{ github.ref_name == 'agent/619-graftling-windows-import' && "
               "'616671870fb2dd9679ea18fdfdbd2f094b1ae0a9' || env.GRAFTLING_REF }}")
WIN_REF_NEW = "          ref: ${{ env.GRAFTLING_REF }}"


def wfcheck(base, head, branch, name):
    """Apply the allowed edits to BASE and require HEAD to equal the result exactly."""
    with open(base, encoding="utf-8") as handle:
        old = handle.read().split("\n")
    with open(head, encoding="utf-8") as handle:
        new = handle.read().split("\n")
    win = name.endswith("desktop-win-adoption.yml")
    done = {"push branches + " + branch: 0, "GRAFTLING_REF v0.10.1 -> v0.10.2": 0}
    if win:
        done.update({"619-only comment (3 lines) removed": 0, "619-only ref expression -> env.GRAFTLING_REF": 0})
    keys = list(done)
    out, i = [], 0
    while i < len(old):
        line = old[i]
        m = re.fullmatch(r"(\s*branches: \[)(.*)\]", line)
        if m and i > 0 and old[i - 1].strip() == "push:" and not done[keys[0]]:
            out.append(f"{m.group(1)}{m.group(2)}, {branch}]")
            done[keys[0]] += 1
        elif re.fullmatch(r"\s*GRAFTLING_REF: v0\.10\.1", line):
            out.append(line.replace("v0.10.1", "v0.10.2"))
            done[keys[1]] += 1
        elif win and old[i:i + 3] == WIN_COMMENT:
            done[keys[2]] += 1
            i += 3
            continue
        elif win and line == WIN_REF_OLD:
            out.append(WIN_REF_NEW)
            done[keys[3]] += 1
        else:
            out.append(line)
        i += 1
    unexpected = [f"{key}: applied {count} times at the base" for key, count in done.items() if count != 1]
    if unexpected:
        print("base does not have the expected lines: " + "; ".join(unexpected))
        sys.exit(1)
    if out == new:
        print("only the allowed lines changed: " + "; ".join(keys))
        return
    print("changes other than the allowed lines (expected vs HEAD):")
    for line in list(difflib.unified_diff(out, new, "expected", "HEAD", lineterm="", n=0))[:24]:
        print("    " + line[:200])
    sys.exit(1)


COMMANDS = {"get": lambda a: get(a[0], a[1]), "dispatch": lambda a: dispatch(a[0]), "artifact": lambda a: artifact(a[0], a[1]),
            "ids": lambda a: ids(a[0]), "newrun": lambda a: newrun(a[0], a[1], a[2:]), "jobs": lambda a: jobs(a[0]),
            "pushruns": lambda a: pushruns(a[0], a[1:]),
            "evidence": lambda a: evidence(a[0]), "wfcheck": lambda a: wfcheck(a[0], a[1], a[2], a[3])}

if __name__ == "__main__":
    COMMANDS[sys.argv[1]](sys.argv[2:])
