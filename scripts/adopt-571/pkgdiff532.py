"""532: one package's files compared file by file between a wheel, a git archive and installed trees. Read only.

usage: pkgdiff532.py <package> <first: wheel | tree holding <package>/> <second: tree holding <package>/>
                     <check text> <expected differing files, comma separated, or ->

- wheel vs tree: every file the wheel has under <package>/ against the tree's bytes; a file only in one side is a
  difference (__pycache__ ignored). V: graphtraj wheel a7b20447 vs production (expected: the three 531 files);
  graftling wheel v0.6.2 vs production (expected: none).
- tree vs tree: <package>/ and <package>-*.dist-info, except the dist-info files pip rewrites. I/done/R: graftling
  installed vs the backup's copy (expected: none).
- `archive:` before the second path (B): every file the wheel has under <package>/ must equal the git archive's
  bytes; archive files the wheel does not carry are listed for information only.
Exit 0 only when the differing files are exactly the expected ones and the first side is not empty.
"""
import os
import sys
import zipfile
from pathlib import Path

REWRITTEN = {'RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'}


def tree_files(site: Path, package: str, dist_info: bool) -> dict[str, bytes]:
    out = {}
    roots = [site / package] + (sorted(site.glob(f'{package}-*.dist-info')) if dist_info else [])
    for root in roots:
        # 560: follow directory links (graftling 0.6.3's src/graftling/install -> ../../docs/install); rglob does not.
        paths = sorted(Path(base) / name for base, _, names in os.walk(root, followlinks=True) for name in names)
        for path in paths:
            if path.is_file() and '__pycache__' not in path.parts:
                rel = path.relative_to(site).as_posix()
                if '.dist-info/' in rel and rel.rsplit('/', 1)[-1] in REWRITTEN:
                    continue
                out[rel] = path.read_bytes()
    return out


def main() -> int:
    package, first, second, text = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    expected = set() if sys.argv[5] == '-' else set(sys.argv[5].split(','))
    archive = second.startswith('archive:')
    second = Path(second.removeprefix('archive:'))
    if first.is_file():
        wheel = zipfile.ZipFile(first)
        new = {n: wheel.read(n) for n in wheel.namelist() if n.startswith(f'{package}/') and not n.endswith('/')}
        old = tree_files(second, package, False)
    else:
        new, old = tree_files(first, package, True), tree_files(second, package, True)
    differ = sorted(n for n in new if n in old and old[n] != new[n])
    only_first = sorted(set(new) - set(old))
    only_second = sorted(set(old) - set(new))
    for name in differ:
        print(f"  {'expected' if name in expected else 'UNEXPECTED'} {name} (bytes differ)")
    for name in only_first:
        print(f"  {'expected' if name in expected else 'UNEXPECTED'} {name} (only in {first.name})")
    for name in only_second:
        print(f"  {'information' if archive else ('expected' if name in expected else 'UNEXPECTED')} {name} (only in {second})")
    found = set(differ) | set(only_first) | (set() if archive else set(only_second))
    missing = sorted(expected - found)
    ok = bool(new) and found == expected
    print(f'{package} {first.name} vs {second}: files {len(new)} same={len(new) - len(differ) - len(only_first)} '
          f'differing={len(found)} | expected {sorted(expected) or "none"} | expected but equal: {missing or "none"}')
    print(f"CHECK {text}: {'PASS' if ok else 'FAIL (STOP)'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
