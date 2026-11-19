"""525 V: graphtraj files of the new wheel compared with production's installed graphtraj, file by file. Read only.

usage: gtdiff525.py <graphtraj wheel> <production site-packages>

Production holds 4ad22e90 (515); the wheel is 8267f9e5. `git diff 4ad22e90 8267f9e5 -- src` changes exactly the three
files in EXPECTED (521: runner_results.py and interfaces/tools.py; 523: runner_status.py). Every file the wheel installs
under graphtraj/ is compared with production's bytes; a production graphtraj/ file the wheel does not install is
listed too (__pycache__ ignored). Exit 0 only when the differing files are exactly EXPECTED.
"""
import sys
import zipfile
from pathlib import Path

EXPECTED = {
    'graphtraj/execution/runner_results.py',
    'graphtraj/execution/runner_status.py',
    'graphtraj/interfaces/tools.py',
}


def main() -> int:
    wheel, site = zipfile.ZipFile(sys.argv[1]), Path(sys.argv[2])
    names = sorted(n for n in wheel.namelist() if n.startswith('graphtraj/') and not n.endswith('/'))
    differ, same = [], 0
    for name in names:
        target = site / name
        if not target.is_file():
            differ.append(f'{name} (only in the new wheel)')
        elif target.read_bytes() != wheel.read(name):
            differ.append(name)
        else:
            same += 1
    wheel_set = set(names)
    for path in sorted((site / 'graphtraj').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.relative_to(site).as_posix() not in wheel_set:
            differ.append(f'{path.relative_to(site).as_posix()} (only in production)')
    for item in differ:
        print(f"  {'expected' if item in EXPECTED else 'UNEXPECTED'} {item}")
    missing = sorted(EXPECTED - set(differ))
    ok = set(differ) == EXPECTED
    print(f'graphtraj wheel vs production: wheel files {len(names)} same={same} differing={len(differ)} '
          f'| expected {sorted(EXPECTED)} | expected but equal: {missing or "none"}')
    print(f"CHECK 525 graphtraj differs from production in exactly the 521/523 files: {'PASS' if ok else 'FAIL (STOP)'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
