#!/usr/bin/env python3
"""Run the full test suite in parallel file shards.

Usage::

    python scripts/run_test_shards.py [--shards N] [--log-dir DIR] [-- PYTEST-ARGS...]

Run it with the Python of a venv whose site-packages imports this checkout:
installed in editable mode, or a ``.pth`` file naming its ``src``. Workers run
``python -I``, which ignores ``PYTHONPATH``, so a ``PYTHONPATH`` (absolute or
relative to the repository root, where shards start) serves only the other
subprocesses. Otherwise each shard stops at start with one message naming the
interpreter, what it imports and the fixes. Each shard runs
``<python> -m pytest -p no:cacheprovider -q -rfEs <files>`` from the
repository root. ``tests/test_*.py`` files are split into ``N`` shards
(default 4) by file size, largest first, so shards finish at similar times.

Each shard runs in its own session and must finish within ``--timeout``
seconds (default 1800). A shard past that bound has its whole process group
stopped (SIGTERM, then SIGKILL) and is reported as ``ABNORMAL ... timed out``.
On any exit of this script, including Ctrl-C, SIGTERM or SIGHUP, remaining
shard groups are stopped, so no shard process outlives the run.

Tests also start detached processes (idle budget timers, Workers, fake
Runtimes) in their own sessions, which a shard's group does not hold (454).
The script draws one run id, prints it first as ``test run id: <id>``, and
gives shard ``n`` the environment value ``PYTEST_GRAPHTRAJ_RUN=<id>-<n>``;
children inherit it. Each shard's pytest stops its own value's processes at
session end (``tests/process_reclaim.py``). When a shard ends, and on any exit
of this script, the script stops the processes still carrying that shard's
exact value. It then prints one line::

    leftover processes of run <id>: before=<n> after-shards=<n> stopped=<n> remaining=<n>

counting same-user processes whose ``PYTEST_GRAPHTRAJ_RUN`` starts with the run
id: ``before`` at start (0 unless a value repeats); ``after-shards``, those a
shard left after its own session-end cleanup; ``stopped``, how many of them the
script stopped; ``remaining``, the run's processes still present at the end. A
``remaining`` above 0 is reported as ``ABNORMAL`` and fails the run. The
count can be repeated independently on macOS with
``ps -Eww -o pid,command | grep 'PYTEST_GRAPHTRAJ_RUN=<id>-'`` (``-E`` shows a
same-user process's environment).

Each shard writes ``shard-<n>.log`` under ``--log-dir`` (default: a new
temporary directory). When all shards finish, the script prints the combined
outcome counts and the sorted failing and erroring test IDs, and writes those
IDs to ``failures.txt`` in the same directory, so two runs can be compared with
``diff``. The exit status is non-zero when any test fails or errors, or when a
shard ends abnormally.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

from graftling.member_processes import ancestor_pids, find_marked_processes, stop_marked_processes


ROOT = Path(__file__).resolve().parents[1]
_OUTCOME = re.compile(r"(\d+) (failed|passed|skipped|xfailed|xpassed|errors?|deselected)\b")
_SUMMARY = re.compile(r"^=*\s*\d+ (failed|passed|skipped|xfailed|xpassed|errors?|deselected)\b.* in [\d.]+s\b")
_PROBLEM = re.compile(r"^(FAILED|ERROR) (\S+)")
TEST_RUN_ENV = "PYTEST_GRAPHTRAJ_RUN"


def _run_processes(run_id: str) -> dict[int, str]:
    """Same-user processes carrying any shard value of this run."""
    return find_marked_processes(f"{run_id}-", ancestor_pids(), variable=TEST_RUN_ENV, prefix=True)


def _reclaim_shard(value: str, stopped: set[int]) -> int:
    """Stop processes still carrying exactly this shard's value; return how many were found."""
    report = stop_marked_processes(value, ancestor_pids(), variable=TEST_RUN_ENV)
    stopped.update(item["pid"] for item in report["stopped"])
    return len(report["found"])


def _shards(files: list[Path], count: int) -> list[list[Path]]:
    shards: list[list[Path]] = [[] for _ in range(count)]
    sizes = [0] * count
    for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True):
        smallest = sizes.index(min(sizes))
        shards[smallest].append(path)
        sizes[smallest] += path.stat().st_size
    return [sorted(shard) for shard in shards if shard]


def _signal_group(process: subprocess.Popen, sig: int) -> bool:
    """Send ``sig`` to the shard's own group; False when no live member is left.

    macOS answers EPERM, not ESRCH, when every remaining member has exited but
    is not yet reaped (zombies), e.g. a stopped child awaiting launchd (472).
    """
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _stop_group(process: subprocess.Popen) -> None:
    """Stop a shard's whole process group: SIGTERM, then SIGKILL."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _signal_group(process, sig):
            break
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            continue
        if not _signal_group(process, 0):
            break
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not _signal_group(process, 0):
                return
            time.sleep(0.05)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _interrupted(signum: int, frame: object) -> None:
    """Turn a stop request into the cleanup path below."""
    raise KeyboardInterrupt(signal.Signals(signum).name)


def main() -> int:
    # SIGTERM or SIGHUP would otherwise end this script without its cleanup,
    # leaving shards that run in their own sessions; a background job also
    # starts with SIGINT ignored.
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _interrupted)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=1800,
                        help="seconds each shard may run before it is stopped (default 1800)")
    parser.add_argument("--tests-dir", type=Path, default=ROOT / "tests", help=argparse.SUPPRESS)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    extra = options.pytest_args[1:] if options.pytest_args[:1] == ["--"] else options.pytest_args
    log_dir = options.log_dir or Path(tempfile.mkdtemp(prefix="test-shards-"))
    log_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(options.tests_dir.resolve().glob("test_*.py"))
    run_id = uuid.uuid4().hex[:16]
    print(f"test run id: {run_id} (shard n carries {TEST_RUN_ENV}={run_id}-<n>)", flush=True)
    before = len(_run_processes(run_id))
    reclaimed: set[int] = set()
    after_shards = 0
    running = []
    statuses: dict[int, int | str] = {}
    try:
        for number, shard in enumerate(_shards(files, max(1, options.shards))):
            log = log_dir / f"shard-{number}.log"
            command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rfEs",
                       *extra, *(os.path.relpath(path, ROOT) for path in shard)]
            handle = log.open("w")
            environment = {**os.environ, TEST_RUN_ENV: f"{run_id}-{number}"}
            running.append((log, handle, subprocess.Popen(command, cwd=ROOT, stdout=handle,
                                                          stderr=subprocess.STDOUT,
                                                          stdin=subprocess.DEVNULL, env=environment,
                                                          start_new_session=True)))
            print(f"shard {number}: {len(shard)} files -> {log}", flush=True)

        deadline = time.monotonic() + options.timeout
        while len(statuses) < len(running):
            for index, (_, _, process) in enumerate(running):
                if index in statuses:
                    continue
                status = process.poll()
                if status is not None:
                    statuses[index] = status
                    # A finished pytest may leave children in its group.
                    _stop_group(process)
                    after_shards += _reclaim_shard(f"{run_id}-{index}", reclaimed)
                elif time.monotonic() >= deadline:
                    _stop_group(process)
                    statuses[index] = f"timed out after {options.timeout:g} s"
                    after_shards += _reclaim_shard(f"{run_id}-{index}", reclaimed)
            time.sleep(0.2)
    finally:
        for _, handle, process in running:
            _stop_group(process)
            handle.close()
        # Detached processes left the shard's group; their value still names
        # them. A shard reclaimed above finds nothing more unless interrupted.
        for index in range(len(running)):
            after_shards += _reclaim_shard(f"{run_id}-{index}", reclaimed)
        remaining = _run_processes(run_id)
        print(f"leftover processes of run {run_id}: before={before} after-shards={after_shards} "
              f"stopped={len(reclaimed)} remaining={len(remaining)}", flush=True)
        for pid, command in sorted(remaining.items()):
            print(f"  remaining {pid} {command}", flush=True)

    totals: Counter[str] = Counter()
    problems: set[str] = set()
    abnormal = []
    for index, (log, _, process) in enumerate(running):
        status = statuses[index]
        summary = ""
        for line in log.read_text(errors="replace").splitlines():
            problem = _PROBLEM.match(line)
            if problem:
                problems.add(f"{problem.group(1)} {problem.group(2)}")
            if _SUMMARY.match(line):
                summary = line
        for amount, outcome in _OUTCOME.findall(summary):
            totals["errors" if outcome.startswith("error") else outcome] += int(amount)
        if isinstance(status, str):
            abnormal.append(f"{log}: {status}")
        elif status not in (0, 1) or not summary:
            abnormal.append(f"{log}: exit {status}")
    if remaining:
        abnormal.append(f"run {run_id}: {len(remaining)} leftover processes remain")

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
