#!/usr/bin/env python3
"""Run the full test suite in parallel file shards.

Usage::

    python scripts/run_test_shards.py [--shards N] [--log-dir DIR] [-- PYTEST-ARGS...]

Run it with the Python of the environment under test (for example a dedicated
venv with this checkout installed in editable mode); each shard runs
``<python> -m pytest -p no:cacheprovider -q -rfEs <files>`` from the
repository root. ``tests/test_*.py`` files are split into ``N`` shards
(default 4) by file size, largest first, so shards finish at similar times.

Each shard writes ``shard-<n>.log`` under ``--log-dir`` (default: a new
temporary directory). When all shards finish, the script prints the combined
outcome counts and the sorted failing and erroring test IDs, and writes those
IDs to ``failures.txt`` in the same directory, so two runs can be compared with
``diff``. The exit status is non-zero when any test fails or errors, or when a
shard ends abnormally.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_OUTCOME = re.compile(r"(\d+) (failed|passed|skipped|xfailed|xpassed|errors?|deselected)\b")
_SUMMARY = re.compile(r"^=*\s*\d+ (failed|passed|skipped|xfailed|xpassed|errors?|deselected)\b.* in [\d.]+s\b")
_PROBLEM = re.compile(r"^(FAILED|ERROR) (\S+)")


def _shards(files: list[Path], count: int) -> list[list[Path]]:
    shards: list[list[Path]] = [[] for _ in range(count)]
    sizes = [0] * count
    for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True):
        smallest = sizes.index(min(sizes))
        shards[smallest].append(path)
        sizes[smallest] += path.stat().st_size
    return [sorted(shard) for shard in shards if shard]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    extra = options.pytest_args[1:] if options.pytest_args[:1] == ["--"] else options.pytest_args
    log_dir = options.log_dir or Path(tempfile.mkdtemp(prefix="test-shards-"))
    log_dir.mkdir(parents=True, exist_ok=True)

    files = sorted((ROOT / "tests").glob("test_*.py"))
    running = []
    for number, shard in enumerate(_shards(files, max(1, options.shards))):
        log = log_dir / f"shard-{number}.log"
        command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rfEs",
                   *extra, *(str(path.relative_to(ROOT)) for path in shard)]
        handle = log.open("w")
        running.append((log, handle, subprocess.Popen(command, cwd=ROOT, stdout=handle,
                                                      stderr=subprocess.STDOUT)))
        print(f"shard {number}: {len(shard)} files -> {log}", flush=True)

    totals: Counter[str] = Counter()
    problems: set[str] = set()
    abnormal = []
    for log, handle, process in running:
        status = process.wait()
        handle.close()
        summary = ""
        for line in log.read_text(errors="replace").splitlines():
            problem = _PROBLEM.match(line)
            if problem:
                problems.add(f"{problem.group(1)} {problem.group(2)}")
            if _SUMMARY.match(line):
                summary = line
        for amount, outcome in _OUTCOME.findall(summary):
            totals["errors" if outcome.startswith("error") else outcome] += int(amount)
        if status not in (0, 1) or not summary:
            abnormal.append(f"{log}: exit {status}")

    ordered = sorted(problems, key=lambda item: item.split(" ", 1)[1])
    (log_dir / "failures.txt").write_text("".join(f"{item}\n" for item in ordered))
    for item in ordered:
        print(item)
    for item in abnormal:
        print(f"ABNORMAL {item}")
    print(", ".join(f"{totals[key]} {key}" for key in
                    ("failed", "errors", "passed", "skipped", "xfailed", "xpassed", "deselected")
                    if totals[key]) or "no tests ran")
    print(f"logs: {log_dir}")
    return 1 if ordered or abnormal or not totals else 0


if __name__ == "__main__":
    sys.exit(main())
