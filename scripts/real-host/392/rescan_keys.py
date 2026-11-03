"""Read-only rescan of saved 392 evidence for the user's real key values.

Usage: python -I rescan_keys.py <skip directory> <directory> ...

The values come from shell_keys.py (~/.zshrc, plainly and interactively) and DEEPSEEK_API_KEY in this
environment. They stay in memory. Each finding is printed as `FAIL secret: <variable> in <file>`; a value
is never printed, and nothing is changed. The skip directory is the step's own output.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shell_keys import shell_values  # noqa: E402


def main() -> int:
    """Scan every regular file once for every value; print names and files only."""
    skip, *roots = (Path(item).resolve() for item in sys.argv[1:])
    found, failed = shell_values()
    if found is None:
        print(f'FAIL secret: these shell forms gave no listing: {failed}; nothing could be looked for')
        return 1
    values = {}
    for name, value in found:
        values.setdefault(value, set()).add(name)
    own = os.environ.get('DEEPSEEK_API_KEY', '').encode()
    if own:
        values.setdefault(own, set()).add('DEEPSEEK_API_KEY')
    files = hits = 0
    for root in roots:
        if not root.is_dir():
            print(f'note: {root} does not exist')
            continue
        for path in root.rglob('*'):
            if path.is_symlink() or not path.is_file() or skip in path.parents:
                continue
            try:
                data = path.read_bytes()
            except OSError as error:
                print(f'CANNOT secret: {path} could not be read: {error.strerror}')
                continue
            files += 1
            for value, names in values.items():
                if value in data:
                    hits += 1
                    print(f'FAIL secret: {",".join(sorted(names))} in {path}')
    variables = sorted({name for names in values.values() for name in names})
    print(f'{"PASS" if not hits else "note"} rescan: {files} files read, {hits} findings, '
          f'{len(variables)} variables looked for: {variables}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
