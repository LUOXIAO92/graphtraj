"""Task 621 step helper: reads GitHub REST JSON saved by steps.zsh and downloaded evidence; prints plain lines.

Run as: python -I ghjson.py <command> <args...>. Standard library only; reads files, writes nothing.
  get FILE KEY[.KEY...]          value at a key path (empty when absent)
  dispatch FILE                  contents-API JSON of the workflow: workflow_dispatch with a 'standard' mode option
  artifact FILE NAME             one line for the named artifact of a run (MISSING when absent)
  ids FILE                       ids of every run in a runs listing, space separated
  newrun FILE SHA [OLD_ID...]    newest run for SHA whose id is not an OLD_ID: id, status, conclusion, url
  jobs FILE                      each job's conclusion and every step that did not succeed or skip
  evidence DIR                   files with sizes, then a summary of every evidence.json below DIR
"""
import base64
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
            if name == "evidence.json":
                found.append(full)
    if not found:
        print("no evidence.json below", root)
    for full in found:
        print(f"--- {os.path.relpath(full, root)}")
        try:
            facts = load(full)
        except (OSError, ValueError) as error:
            print("  unreadable:", error)
            continue
        print("  passed:", facts.get("passed"))
        for key in ("failure", "blockedReason", "failureScreenshotError", "cleanupError"):
            if facts.get(key):
                print(f"  {key}:")
                for line in str(facts[key]).splitlines()[:8]:
                    print("    " + line)
        steps = facts.get("steps") or []
        print(f"  steps: {len(steps)} recorded; last {min(len(steps), 6)}:")
        for line in steps[-6:]:
            print("    - " + str(line)[:200])
        print("  screenshots:", ", ".join(str(item) for item in facts.get("screenshots") or []) or "none")


COMMANDS = {"get": lambda a: get(a[0], a[1]), "dispatch": lambda a: dispatch(a[0]), "artifact": lambda a: artifact(a[0], a[1]),
            "ids": lambda a: ids(a[0]), "newrun": lambda a: newrun(a[0], a[1], a[2:]), "jobs": lambda a: jobs(a[0]),
            "evidence": lambda a: evidence(a[0])}

if __name__ == "__main__":
    COMMANDS[sys.argv[1]](sys.argv[2:])
