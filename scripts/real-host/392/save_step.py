"""Copy one 392 step's evidence to the Harness, leaving out any file holding the DeepSeek value.

Usage: python -I save_step.py <evidence directory> <destination> <answer file>

The value comes from this process's environment only. The answer file is written last, so its
absence means the copy did not finish. An earlier result at the destination is kept beside the new
one, named with its own start time.
"""
import os
from pathlib import Path
import shutil
import sys


def holding_value(directory: Path, value: bytes) -> list[Path]:
    """Return the files under ``directory`` whose bytes contain ``value``.

    An empty ``value`` means no key was loaded, so no file can hold it.
    """
    if not value:
        return []
    return [path for path in sorted(directory.rglob('*'))
            if path.is_file() and not path.is_symlink() and value in path.read_bytes()]


def keep_earlier(destination: Path) -> None:
    """Move an earlier result aside, so that a rerun never overwrites evidence."""
    if not destination.exists():
        return
    started = 'earlier'
    record = destination / 'run.txt'
    if record.is_file():
        started = record.read_text(errors='replace').split()[-1]
    target = destination.with_name(f'{destination.name}.{started}')
    number = 1
    while target.exists():
        target = destination.with_name(f'{destination.name}.{started}.{number}')
        number += 1
    destination.rename(target)


def main() -> int:
    """Scan, record what was left out in the summary, copy and answer."""
    evidence, destination, answer = (Path(item) for item in sys.argv[1:4])
    value = os.environ.get('DEEPSEEK_API_KEY', '').encode()
    matched = holding_value(evidence, value)
    summary = evidence / 'summary.txt'
    with summary.open('a') as lines:
        if matched:
            lines.write(f'FAIL secret: {len(matched)} files hold the DeepSeek value and were not saved: '
                        f'{[str(path.relative_to(evidence)) for path in matched]}\n')
        else:
            lines.write('PASS secret: no saved file holds the DeepSeek value\n'
                        if value else 'note: no DeepSeek key was loaded in this step\n')
    keep_earlier(destination)
    destination.mkdir(parents=True)
    copied = 0
    for path in sorted(evidence.rglob('*')):
        if not path.is_file() or path.is_symlink() or path in matched:
            continue
        target = destination / path.relative_to(evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    answer.write_text(f'Saved {copied} files to {destination}; left out {len(matched)} holding the DeepSeek value.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
