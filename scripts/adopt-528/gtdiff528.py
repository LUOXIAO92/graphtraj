"""528: graphtraj files of a wheel compared with an installed graphtraj, file by file. Read only.

usage: gtdiff528.py <graphtraj wheel | site-packages holding graphtraj/> <production site-packages> [<label>]

528 does not reinstall GraphTraj: production holds 8267f9e5 (525), and the candidate's src is the same commit. V
compares the 8267f9e5 wheel B builds (used only for the scratch venv) with production; I and done compare the installed
graphtraj with the backup's copy. Every file of the first tree under graphtraj/ (and graphtraj-*.dist-info except
the files pip rewrites, for two site-packages trees) is compared with the second's bytes; a file only in one side is
listed (__pycache__ ignored). Exit 0 only when nothing differs.
"""
import sys
import zipfile
from pathlib import Path

REWRITTEN = {'RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'}


def tree_files(site: Path, dist_info: bool) -> dict[str, bytes]:
    out = {}
    roots = [site / 'graphtraj'] + (sorted(site.glob('graphtraj-*.dist-info')) if dist_info else [])
    for root in roots:
        for path in sorted(root.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                rel = path.relative_to(site).as_posix()
                if '.dist-info/' in rel and rel.rsplit('/', 1)[-1] in REWRITTEN:
                    continue
                out[rel] = path.read_bytes()
    return out


def main() -> int:
    first, site = Path(sys.argv[1]), Path(sys.argv[2])
    label = sys.argv[3] if len(sys.argv) > 3 else f'{first.name} vs {site}'
    if first.is_file():
        wheel = zipfile.ZipFile(first)
        new = {n: wheel.read(n) for n in wheel.namelist() if n.startswith('graphtraj/') and not n.endswith('/')}
        old = tree_files(site, False)
    else:
        new, old = tree_files(first, True), tree_files(site, True)
    differ = [n for n in sorted(new) if n in old and old[n] != new[n]]
    differ += [f'{n} (only in {first.name})' for n in sorted(set(new) - set(old))]
    differ += [f'{n} (only in {site})' for n in sorted(set(old) - set(new))]
    for item in differ:
        print(f'  UNEXPECTED {item}')
    ok = not differ and bool(new)
    print(f'graphtraj {label}: files {len(new)} same={len(new) - len([d for d in differ if "(only" not in d]) - len(set(new) - set(old))} '
          f'differing={len(differ)}')
    print(f"CHECK 528 graphtraj unchanged ({label}): {'PASS' if ok else 'FAIL (STOP)'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
