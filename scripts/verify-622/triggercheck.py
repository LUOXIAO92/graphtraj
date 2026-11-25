"""Task 622: which workflows a push of BRANCH starts, read strictly (duplicate keys fail).

Usage: python -I triggercheck.py BRANCH <workflow file>...   (files may be copies; the name is the base name)
Prints one OK/FAIL line per file and RUNS/NOT for BRANCH, then the expected-trigger check for
desktop-win-adoption.yml: its push branches are exactly the four pre-622 branches plus BRANCH.
Exit 0 only when every file parses, desktop-win-adoption.yml matches that list, and no other workflow runs.
"""
import re
import sys
from pathlib import Path

import yaml

WIN = "desktop-win-adoption.yml"
OLD_WIN = ["agent/266-desktop-win-adoption", "agent/288-desktop-d-integrated-adoption-win",
           "agent/290-desktop-d-direct-port-win", "agent/618-desktop-workflows-graftling-ref"]


class Strict(yaml.SafeLoader):
    pass


def construct_mapping(loader, node, deep=False):
    keys = set()
    for k, _ in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", k.start_mark)
        keys.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)


def glob(pattern):  # GitHub filter pattern: ** any characters, * any but '/', ? one
    out = ""
    for token in re.split(r"(\*\*|\*|\?)", pattern):
        out += {"**": ".*", "*": "[^/]*", "?": "."}.get(token, re.escape(token))
    return re.compile(out + r"\Z")


def runs_on_push(on, branch):
    if isinstance(on, str):
        on = [on]
    if isinstance(on, list):
        return "push" in on
    if not isinstance(on, dict) or "push" not in on:
        return False
    push = on["push"] or {}
    if "branches" in push:
        included = False
        for pattern in push["branches"]:  # later '!' patterns exclude again
            if pattern.startswith("!"):
                included = included and not glob(pattern[1:]).match(branch)
            elif glob(pattern).match(branch):
                included = True
        return included
    if "branches-ignore" in push:
        return not any(glob(p).match(branch) for p in push["branches-ignore"])
    return "tags" not in push and "tags-ignore" not in push


branch, files = sys.argv[1], sys.argv[2:]
bad, running, win_branches = 0, [], None
for file in files:
    name = Path(file).name
    try:
        doc = yaml.load(open(file, encoding="utf-8"), Loader=Strict)
        on = doc.get(True, doc.get("on"))  # YAML 1.1 reads bare 'on' as True
    except Exception as error:
        bad += 1
        print(f"FAIL {name}: {error}".replace("\n", " "))
        continue
    starts = runs_on_push(on, branch)
    print(f"OK   {name}: strict YAML; push of {branch}: {'RUNS' if starts else 'not triggered'}")
    if starts:
        running.append(name)
    if name == WIN:
        win_branches = (on.get("push") or {}).get("branches")
if win_branches == OLD_WIN + [branch]:
    print(f"PASS {WIN} push branches = the four earlier branches + {branch}")
else:
    bad += 1
    print(f"FAIL {WIN} push branches are {win_branches}, expected {OLD_WIN + [branch]}")
if running == [WIN]:
    print(f"PASS only {WIN} runs for a push of {branch}")
else:
    bad += 1
    print(f"FAIL workflows run for a push of {branch}: {running or 'none'} (expected only {WIN})")
sys.exit(1 if bad else 0)
