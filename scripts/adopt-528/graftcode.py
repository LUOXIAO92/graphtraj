"""528 V: graftling code of the new wheel compared with production's installed graftling, file by file. Read only.

usage: graftcode.py <graftling wheel> <production site-packages> <directory holding the v0.6.2 archive's graftling/>

528 (copied from 525): production is 0.6.1. Expected CODE differences: 526's control.py, locks.py, sessions/archive.py
and 527's dsh/client.mjs, dsh/package.json (527 also shortened its inject list, so it is not version-only); VERSION:
__init__.py, pi/package.json (claude-plugin/ is not in the wheel); DOC: CHANGELOG.md, README.md. Exit 1 when a
class differs from its expected set, or when a file the wheel installs differs from the git archive of the tag (or is
missing there). The text below is 503's.

Every file the wheel installs under graftling/ is compared with the same file in production's site-packages
(871aaaa9's graftling 0.5.0, installed by Task 499); a production graftling/ file the wheel does not install is
listed too. Task 395 says graftling's code is the same and only the version changed. Classes of a difference:
  VERSION   graftling/__init__.py whose only differing lines are `__version__ = "..."`, or a JSON manifest
            (package.json, plugin.json) that is equal once its "version" key is removed: version metadata.
  DOC       a Markdown file (CHANGELOG.md, PUBLIC_API.md, README.md, install/*.md): documentation, never executed;
            its diff is printed for the Leader. 395 records CHANGELOG and PUBLIC_API at 0.5.2.
  CODE      anything else (a code or data file with another difference, a file only in one side): STOP.
dist-info is not compared here (name and version differ by design; proddiff.py checks it after the install).
Exit 0 when no CODE difference; 1 otherwise (the step prints STOP for the Leader).
"""
import difflib
import json
import sys
import zipfile
from pathlib import Path

EXPECTED_CODE = {'graftling/control.py', 'graftling/locks.py', 'graftling/sessions/archive.py',   # 526
                 'graftling/dsh/client.mjs', 'graftling/dsh/package.json'}   # 527 (package.json: inject list too)
# claude-plugin/ is not packaged in the wheel (525's V-graftcode.txt lists the same VERSION files without it), so its
# plugin.json version change never reaches production.
EXPECTED_VERSION = {'graftling/__init__.py', 'graftling/pi/package.json'}
EXPECTED_DOC = {'graftling/CHANGELOG.md', 'graftling/README.md'}

def version_only_py(old: str, new: str) -> bool:
    diff = [l for l in difflib.ndiff(old.splitlines(), new.splitlines()) if l[:2] in ('- ', '+ ')]
    return bool(diff) and all(l[2:].startswith('__version__ = ') for l in diff)


def version_only_json(old: bytes, new: bytes) -> bool:
    try:
        a, b = json.loads(old), json.loads(new)
    except ValueError:
        return False
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    a.pop('version', None); b.pop('version', None)
    return a == b


def main() -> int:
    wheel, site = Path(sys.argv[1]), Path(sys.argv[2])
    archive = zipfile.ZipFile(wheel)
    names = sorted(n for n in archive.namelist() if n.startswith('graftling/') and not n.endswith('/'))
    same, classes = 0, {'VERSION': [], 'DOC': [], 'CODE': []}
    diffs = []
    for name in names:
        new = archive.read(name)
        target = site / name
        if not target.is_file():
            classes['CODE'].append(f'{name} (only in the new wheel)'); continue
        old = target.read_bytes()
        if old == new:
            same += 1; continue
        text_old, text_new = old.decode('utf-8', 'replace'), new.decode('utf-8', 'replace')
        if name == 'graftling/__init__.py' and version_only_py(text_old, text_new):
            kind = 'VERSION'
        elif name.endswith('.json') and version_only_json(old, new):
            kind = 'VERSION'
        elif name.endswith('.md'):
            kind = 'DOC'
        else:
            kind = 'CODE'
        classes[kind].append(name)
        diffs.append((kind, name, list(difflib.unified_diff(text_old.splitlines(), text_new.splitlines(),
                                                              f'production/{name}', f'wheel/{name}', lineterm='', n=1))))
    wheel_set = set(names)
    for path in sorted((site / 'graftling').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            rel = path.relative_to(site).as_posix()
            if rel not in wheel_set:
                classes['CODE'].append(f'{rel} (only in production)')
    print(f'graftling code vs production: wheel files {len(names)} same={same} version-only={len(classes["VERSION"])} '
          f'doc-only={len(classes["DOC"])} code-differences={len(classes["CODE"])}')
    for kind in ('VERSION', 'DOC', 'CODE'):
        for item in classes[kind]:
            print(f'  {kind:7} {item}')
    for kind, name, lines in diffs:
        limit = 12 if kind == 'VERSION' else 80
        print(f'--- diff [{kind}] {name} ({len(lines)} lines{", first " + str(limit) if len(lines) > limit else ""})')
        for line in lines[:limit]:
            print('    ' + line)
    # 528: production is graftling 0.6.1 and the wheel is 0.6.2. Every class must be exactly the expected set: CODE
    # the 526/527 files, VERSION __init__.py and two manifests, DOC CHANGELOG.md and README.md. Anything else is a
    # STOP. The second gate is the wheel against the v0.6.2 archive (bytes).
    code_bad = False
    for kind, expected in (('CODE', EXPECTED_CODE), ('VERSION', EXPECTED_VERSION), ('DOC', EXPECTED_DOC)):
        got = set(classes[kind])
        unexpected, missing = sorted(got - expected), sorted(expected - got)
        ok = not unexpected and not missing
        code_bad |= not ok
        print(f'528 graftling {kind} files 0.6.1 -> 0.6.2: {sorted(got)} | unexpected {len(unexpected)}'
              f'{" " + str(unexpected) if unexpected else ""} | expected but equal {len(missing)}'
              f'{" " + str(missing) if missing else ""}: {"OK" if ok else "STOP"}')
    if len(sys.argv) < 4:
        print('graftling wheel vs archive: NOT CHECKED (no archive directory given)'); return 1
    source = Path(sys.argv[3])
    differ = [n for n in names if not (source / n).is_file() or (source / n).read_bytes() != archive.read(n)]
    for name in differ:
        print(f'  WHEEL-DIFFERS {name} ({"missing in the archive" if not (source / name).is_file() else "bytes differ"})')
    print(f'graftling wheel vs {source}/graftling (git archive): {len(names)} files, differing {len(differ)}: '
          f'{"SAME" if not differ else "STOP"}')
    return 1 if differ or code_bad else 0


if __name__ == '__main__':
    sys.exit(main())
