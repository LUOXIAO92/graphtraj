"""Compare an installed venv with its wheels, file by file; exit 1 on any difference.

usage: proddiff.py <site-packages> <venv prefix> <wheel directory>

Expected counts come from the wheels. Files pip rewrites or adds in dist-info
(RECORD, INSTALLER, REQUESTED, direct_url.json) are not compared. A leftover is a
file under one of the wheel's top-level packages or data directories that the
wheel does not name, or another dist-info of the same distribution.
"""
import os
import re
import sys
import zipfile

REWRITTEN = {'RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'}


def normal(name: str) -> str:
    return re.sub(r'[-_.]+', '_', name).lower()


def main() -> int:
    site, prefix, wheels = sys.argv[1:4]
    passed = failed = 0
    lines = []
    for wheel in sorted(item for item in os.listdir(wheels) if item.endswith('.whl')):
        archive = zipfile.ZipFile(os.path.join(wheels, wheel))
        same = changed = new = 0
        names, roots, data_roots, info = set(), set(), set(), None
        for name in archive.namelist():
            if name.endswith('/'):
                continue
            top = name.split('/')[0]
            if top.endswith('.dist-info'):
                info = top
                if name.rsplit('/', 1)[-1] in REWRITTEN:
                    continue
                target = os.path.join(site, name)
            elif '.data/data/' in name:
                relative = name.split('.data/data/', 1)[1]
                target = os.path.join(prefix, relative)
                data_roots.add(os.path.join(prefix, *relative.split('/')[:2]))
            elif top.endswith('.data'):
                # .data/scripts and the like are rewritten by pip; only their presence counts.
                continue
            else:
                target = os.path.join(site, name)
                roots.add(top)
            names.add(os.path.realpath(target))
            if not os.path.exists(target):
                new += 1
                lines.append(f'NEW      {wheel} {name}')
            elif open(target, 'rb').read() == archive.read(name):
                same += 1
            else:
                changed += 1
                lines.append(f'CHANGED  {wheel} {name}')
        extra = 0
        walked = [os.path.join(site, root) for root in roots] + sorted(data_roots) + [os.path.join(site, info)]
        for directory in walked:
            for root, _, files in os.walk(directory):
                if '__pycache__' in root:
                    continue
                for item in files:
                    path = os.path.realpath(os.path.join(root, item))
                    if path not in names and not (root == os.path.join(site, info) and item in REWRITTEN):
                        extra += 1
                        lines.append(f'EXTRA-IN-PROD {wheel} {os.path.relpath(path, prefix)}')
        distribution = normal(wheel.split('-')[0])
        for other in sorted(os.listdir(site)):
            if (other.endswith('.dist-info') and other != info
                    and normal(other.rsplit('-', 1)[0]) == distribution):
                extra += 1
                lines.append(f'LEFTOVER-DIST-INFO {wheel} {other}')
        lines.append(f'{wheel}: same={same} changed={changed} new={new} extra={extra}')
        passed += same
        failed += changed + new + extra
    print('\n'.join(lines))
    print(f'PASS {passed} FAIL {failed}')
    return 1 if failed or not passed else 0


sys.exit(main())
