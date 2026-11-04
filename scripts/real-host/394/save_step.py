"""Copy one 394 step's evidence to the Harness, leaving out any file holding a key's value.

Usage: python -I save_step.py <evidence directory> <destination> <answer file>

The DeepSeek value comes from this process's environment. The others come from a child shell that
reads ~/.zshrc, plainly and interactively (shell_keys.py): variables named like a credential, with values of 16 characters or more. All of them
stay in this process's memory, on no command line and in no file; a summary line names the variable
and the file, never the value. If that shell cannot answer, nothing can be called clean, so only
run.txt, finished.txt and the failure line are saved, and the evidence stays where it was.

The answer file is written last, so its absence means the copy did not finish. An earlier result at
the destination is kept beside the new one, named with its own start time.
"""
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shell_keys import shell_values  # noqa: E402

ALWAYS_SAVED = ('run.txt', 'finished.txt')


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


def scan(evidence: Path, value: bytes) -> tuple[set[Path], list[str]]:
    """Return the files to leave out and the summary lines saying why, by variable name and file."""
    names = lambda files: [str(path.relative_to(evidence)) for path in files]
    matched = holding_value(evidence, value)
    left_out = set(matched)
    if matched:
        lines = [f'FAIL secret: {len(matched)} files hold the DeepSeek value and were not saved: {names(matched)}']
    elif value:
        lines = ['PASS secret: no file this step saved holds the DeepSeek value']
    else:
        lines = ['note: no DeepSeek key was loaded in this step']
    others, failed = shell_values()
    if others is None:
        left_out |= {path for path in evidence.rglob('*') if path.name not in ALWAYS_SAVED}
        lines.append(f'FAIL secret: these shell forms gave no listing: {failed}, so the other keys could not be looked for; '
                     f'only run.txt, finished.txt and these lines were saved, and the evidence stays in {evidence}')
        return left_out, lines
    clean = []
    for name, other in others:
        if other == value:
            continue
        files = holding_value(evidence, other)
        left_out |= set(files)
        if files:
            lines.append(f'FAIL secret: {len(files)} files hold the value of {name} and were not saved: {names(files)}')
        elif name not in clean:
            clean.append(name)
    lines.append(f'PASS secret: no file this step saved holds the value of these variables from ~/.zshrc, plain and interactive: {clean}')
    return left_out, lines


def main() -> int:
    """Scan, record what was left out in the summary, copy and answer."""
    evidence, destination, answer = (Path(item) for item in sys.argv[1:4])
    left_out, lines = scan(evidence, os.environ.get('DEEPSEEK_API_KEY', '').encode())
    summary = evidence / 'summary.txt'
    with summary.open('a') as stream:
        stream.write(''.join(line + '\n' for line in lines))
    keep_earlier(destination)
    destination.mkdir(parents=True)
    copied = 0
    for path in sorted(evidence.rglob('*')):
        if not path.is_file() or path.is_symlink() or path in left_out:
            continue
        target = destination / path.relative_to(evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    # A summary left out still has to say why. These lines hold names only.
    if summary in left_out:
        (destination / 'summary.txt').write_text(''.join(line + '\n' for line in lines))
    answer.write_text(f"Saved {copied} files to {destination}; left out {len(left_out)} holding a key's value.\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
