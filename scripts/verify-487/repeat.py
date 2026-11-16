"""Task 487: repeat the scoped intermittent tests under parallel load and count failures per test.

    python -I repeat.py <checkout> <out-dir> [--workers 6] [--fast 5] [--slow 2] [--observe 1] [--limit 900]

Run with the test venv's Python, from anywhere. ``--workers`` processes run at
once (the load: comparable to the 6 suite shards). Each worker runs the FAST
set ``--fast`` times, the SLOW set ``--slow`` times, then OBSERVE ``--observe`` times, one pytest process
per pass (``-p no:cacheprovider -q -rfEs``, a JUnit file each), with
``PYTEST_GRAPHTRAJ_RUN=<run>-<worker>`` as run_test_shards.py gives its shards,
so each pytest reclaims its own detached processes. The whole run is bounded by
``--limit`` seconds: past it every worker's process group is stopped (SIGTERM,
then SIGKILL) and only completed passes are counted. Per-test counts go to
stdout and ``counts.txt``; every failure's raw text to ``failures/``.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

FAST = [
    'tests/test_wait_handover_477.py::test_wait_and_push_racing_deliver_the_reply_exactly_once',
    'tests/test_wait_handover_477.py::test_an_end_right_after_a_wait_timed_out_is_held_for_the_members_next_wait',
    'tests/test_dsh_standalone_child.py::test_claude_host_routes_a_dsh_child_with_its_own_choices',
    'tests/test_dsh_standalone_child.py::test_send_and_resume_continue_the_same_dsh_session',
    'tests/test_agent_runner_cleanup.py::test_native_interrupt_confirms_only_pre_runtime_allocations',
    'tests/test_resume_after_owner_exit.py::test_unconfirmed_termination_keeps_the_session_stopped',
    'tests/test_member_child_end_notice_446.py::test_a_busy_member_input_is_retried_within_the_operation_window',
]
# Observe only (earlier Tasks' intermittent records); heavy, so run last.
OBSERVE = [
    'tests/test_interrupted_resolver_recovery.py',
    'tests/test_host_shutdown_stop.py',
    'tests/test_pi_dsh_notice_holding.py',
]
SLOW = [
    'tests/test_claude_runtime.py::test_claude_later_prompt_hook_is_answered_during_one_slow_collection',
    'tests/test_parent_host_status.py::test_hosted_cli_waits_for_full_parent_observation',
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('checkout', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--fast', type=int, default=5)
    parser.add_argument('--slow', type=int, default=2)
    parser.add_argument('--observe', type=int, default=1)
    parser.add_argument('--limit', type=float, default=900)
    args = parser.parse_args()
    checkout, out = args.checkout.resolve(), args.out.resolve()
    junit, failures = out / 'junit', out / 'failures'
    for directory in (junit, failures):
        directory.mkdir(parents=True, exist_ok=True)
    def exists(node: str) -> bool:
        path, _, name = node.partition('::')
        file = checkout / path
        return file.is_file() and (not name or f'def {name}(' in file.read_text(encoding='utf-8'))

    present = [node for node in FAST + SLOW + OBSERVE if exists(node)]
    print('left out (not in this checkout):', [node for node in FAST + SLOW + OBSERVE if node not in present] or 'none')
    fast = [node for node in FAST if node in present]
    slow = [node for node in SLOW if node in present]
    observe = [node for node in OBSERVE if node in present]
    # A node the checkout lacks (the new 487 test on dev) is left out, not failed.
    run = uuid.uuid4().hex[:16]
    print(f'run id {run}; checkout {checkout}; workers {args.workers}; fast x{args.fast}, slow x{args.slow}, observe x{args.observe}; '
          f'limit {args.limit:.0f} s; TMPDIR {os.environ.get("TMPDIR", "/tmp")}', flush=True)
    script = (
        'import subprocess, sys\n'
        'python, worker, junit = sys.argv[1], sys.argv[2], sys.argv[3]\n'
        'passes = []\n'
        'for kind, count, nodes in zip(("fast", "slow", "observe"), sys.argv[4:7], sys.argv[7:10]):\n'
        '    passes += [(kind, i, nodes.split("\\n")) for i in range(int(count)) if nodes]\n'
        'for kind, i, nodes in passes:\n'
        '    subprocess.run([python, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rfEs",\n'
        '                    f"--junitxml={junit}/w{worker}-{kind}-{i}.xml", *nodes])\n'
    )
    started = time.monotonic()
    workers = []
    for worker in range(args.workers):
        env = {**os.environ, 'PYTEST_GRAPHTRAJ_RUN': f'{run}-{worker}'}
        log = open(out / f'worker-{worker}.log', 'w')
        workers.append((subprocess.Popen(
            [sys.executable, '-I', '-c', script, sys.executable, str(worker), str(junit),
             str(args.fast), str(args.slow), str(args.observe), '\n'.join(fast), '\n'.join(slow), '\n'.join(observe)],
            cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True), log))
    limited = False
    for process, log in workers:
        remaining = args.limit - (time.monotonic() - started)
        try:
            process.wait(timeout=max(0.0, remaining))
        except subprocess.TimeoutExpired:
            limited = True
            break
    if limited:
        print(f'== {args.limit:.0f} s limit reached: stopping workers; only completed passes count', flush=True)
        for process, _ in workers:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        time.sleep(10)
        for process, _ in workers:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    for _, log in workers:
        log.close()
    print(f'== workers done in {time.monotonic() - started:.0f} s', flush=True)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for path in sorted(junit.glob('*.xml')):
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue  # a pass the limit stopped mid-write
        for case in tree.iter('testcase'):
            node = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name')}"
            result = 'passed'
            for kind in ('failure', 'error', 'skipped'):
                element = case.find(kind)
                if element is not None:
                    result = {'failure': 'failed', 'error': 'error', 'skipped': 'skipped'}[kind]
                    if kind != 'skipped':
                        index = counts[node]['failed'] + counts[node]['error']
                        name = node.replace('/', '_').replace('::', '__')[:150]
                        (failures / f'{name}-{index}.txt').write_text(
                            f'{path.name}\n{element.get("message", "")}\n\n{element.text or ""}', encoding='utf-8')
                    break
            counts[node][result] += 1
    lines = [f'{"failed+error":>12} {"passed":>6} {"skipped":>7}  test']
    for node in sorted(counts):
        row = counts[node]
        lines.append(f'{row["failed"] + row["error"]:>12} {row["passed"]:>6} {row["skipped"]:>7}  {node}')
    total_bad = sum(row['failed'] + row['error'] for row in counts.values())
    lines.append(f'TOTAL failed+error {total_bad} over {sum(sum(row.values()) for row in counts.values())} results'
                 f'{" (limit reached)" if limited else ""}')
    (out / 'counts.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    print(f'raw failure texts: {failures} ({len(list(failures.glob("*.txt")))} files); worker logs {out}/worker-*.log')
    return 0


if __name__ == '__main__':
    sys.exit(main())
