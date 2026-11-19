"""525 V: graftling code of the new wheel compared with production's installed graftling, file by file. Read only.

usage: graftcode.py <graftling wheel> <production site-packages> <directory holding the v0.6.1 archive's graftling/>

525 (copied from 515): production is 0.6.0; the only CODE difference expected is graftling/sessions/archive.py (518);
VERSION (__init__.py, three manifests) and DOC (CHANGELOG.md) are listed. Exit 1 when another CODE file differs, or
when a file the wheel installs differs from the git archive of the tag (or is missing there). The text below is 503's.

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

EXPECTED_CODE = 'graftling/sessions/archive.py'

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
    # 525: production is graftling 0.6.0 and the wheel is 0.6.1: the only CODE file expected is 518's archive.py.
    # Any other CODE file is a STOP. The second gate is the wheel against the v0.6.1 archive (bytes).
    unexpected = [c for c in classes['CODE'] if c != EXPECTED_CODE]
    print(f'525 graftling CODE files 0.6.0 -> 0.6.1: {classes["CODE"]} | expected [{EXPECTED_CODE!r}] | '
          f'unexpected {len(unexpected)}: {"OK" if not unexpected and classes["CODE"] == [EXPECTED_CODE] else "STOP"}')
    code_bad = bool(unexpected) or classes['CODE'] != [EXPECTED_CODE]
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
