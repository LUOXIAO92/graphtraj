"""531 helper next to verify-518's probe518.py and verify-501's probe.py (they still clone, seed and dispatch).

Usage (a scratch venv's Python or production's, -I):
  python -I probe531.py census HARNESS -       read only (stat and line counts, nothing parsed): every per-project
                                               store a member's Worker may read, by directory, with files and MB
  python -I probe531.py phases RESULT PROJECT  verify-518's phase table (start/pre30/post30/child/after; reader
                                               threads that only wait are not counted as work), then per phase the
                                               prof531 per-call table: function <- nearest GraphTraj/graftling
                                               callers, calls, own-thread CPU seconds, share of the Worker's CPU in
                                               that phase, characters parsed
  python -I probe531.py compare BEFORE AFTER   phases and per-function CPU of two results side by side
Signals nothing; reads no key.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'verify-518'))
sys.path.insert(0, str(HERE.parent / 'verify-501'))
import probe  # noqa: E402
import probe518  # noqa: E402

# A pipe reader blocked in readline, the stderr drain and the member's wait are waiting, not work (518's filter
# counted them, which hid the real stacks).
probe.IDLE = re.compile(probe.IDLE.pattern + r'|^(execution\.py:(_read|drain_stderr)|calls\.py:pause)\b')
PHASES = probe518.PHASES


def _walk(path: Path) -> tuple[int, int]:
    count = total = 0
    try:
        for item in path.rglob('*'):
            try:
                if item.is_file() and not item.is_symlink():
                    count += 1
                    total += item.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return count, total


def census(harness: Path, _unused: str) -> int:
    """518's census plus every first- and second-level store under .graphtraj/core and .graphtraj/swarm."""
    probe518.census(harness, '-')
    for base in ('.graphtraj/core/runner', '.graphtraj/core/state', '.graphtraj/swarm', '.graphtraj/swarm/control'):
        root = harness / base
        if not root.is_dir():
            print(f'{base}: absent')
            continue
        print(f'-- {base}')
        for child in sorted(root.iterdir()):
            if child.is_symlink() or not child.is_dir() or child.name in ('worktrees',):
                continue
            count, total = _walk(child)
            entries = sum(1 for _ in child.iterdir())
            print(f'   {child.name:24s} {entries:6d} entries {count:7d} files {total / 1e6:9.1f} MB')
    retained = list((harness / '.graphtraj/core/state/tasks').glob('*/teams/*/traces/*/runner'))
    print(f'retained Trace runner directories: {len(retained)}')
    return 0


def _bounds(result: dict, project: Path) -> dict | None:
    rows = [json.loads(line) for line in Path(result['raw']).read_text().splitlines() if line.strip()]
    if len(rows) < 2:
        return None
    created, ended = probe518._child_times(project)
    first, last = rows[0]['at'], rows[-1]['at']
    if created is None:
        created = ended = last
    ended = ended or last
    return {'start': (first - 3600, created - 30), 'pre30': (created - 30, created), 'post30': (created, created + 30),
            'child': (created + 30, ended), 'after': (ended, last + 3600)}


def phases(result_file: Path, project: str) -> int:
    rc = probe518.phases(result_file, project)
    result = json.loads(result_file.read_text())
    prof = Path(result['prof'])
    bounds = _bounds(result, Path(project))
    if bounds is None or not prof.is_file():
        print(f'per-call table: no profile or samples ({prof})')
        return rc or 1
    windows = [json.loads(line) for line in prof.read_text().splitlines() if line.strip()]

    def phase_of(window: dict) -> str:
        middle = window['at'] - window['wall'] / 2
        for name in PHASES:
            if bounds[name][0] <= middle < bounds[name][1]:
                return name
        return 'after'

    cpu = defaultdict(float)
    own = defaultdict(float)
    keyed = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0]))
    for window in windows:
        name = phase_of(window)
        cpu[name] += window['cpu']
        own[name] += window.get('sampler_cpu', 0.0)
        for key, (calls, spent, chars) in (window.get('timed') or {}).items():
            item = keyed[name][key]
            item[0] += calls
            item[1] += spent
            item[2] += chars
    wrapped = windows[-1].get('wrapped', []) if windows else []
    print(f'== {result["label"]} per-call table (prof531; own-thread CPU of the outermost call; nested functions are '
          f'included in their callers, so shares do not add up). Wrapped: {len(wrapped)}: {", ".join(wrapped)}')
    table = {}
    for name in PHASES:
        total = cpu[name]
        functions = defaultdict(lambda: [0, 0.0, 0])
        for key, (calls, spent, chars) in keyed[name].items():
            item = functions[key.split(' <- ')[0]]
            item[0] += calls
            item[1] += spent
            item[2] += chars
        table[name] = {'cpu': round(total, 2), 'functions': {k: [v[0], round(v[1], 3), v[2]] for k, v in functions.items()}}
        print(f'-- {name}: Worker CPU {total:.2f} s by profile windows (sampler own {own[name]:.2f} s)')
        print(f'   {"function":52s} {"calls":>7s} {"CPU s":>7s} {"share":>6s} {"M chars":>8s}')
        for function, (calls, spent, chars) in sorted(functions.items(), key=lambda item: -item[1][1]):
            share = spent / total if total else 0.0
            print(f'   {function:52s} {calls:7d} {spent:7.2f} {share:6.1%} {chars / 1e6:8.1f}')
        print('   by caller (CPU >= 0.05 s):')
        for key, (calls, spent, chars) in sorted(keyed[name].items(), key=lambda item: -item[1][1]):
            if spent >= 0.05:
                print(f'   {spent:7.2f} s {calls:6d}x {key[:300]}')
    result['timed531'] = table
    result_file.write_text(json.dumps(result, indent=2))
    return rc


def compare(before: Path, after: str) -> int:
    probe518.compare(before, after)
    first, second = json.loads(before.read_text()), json.loads(Path(after).read_text())
    for name in ('pre30', 'post30', 'child'):
        a = (first.get('timed531') or {}).get(name) or {'cpu': 0, 'functions': {}}
        b = (second.get('timed531') or {}).get(name) or {'cpu': 0, 'functions': {}}
        print(f'-- {name}: profile-window Worker CPU {a["cpu"]:.2f} s -> {b["cpu"]:.2f} s')
        print(f'   {"function":52s} {"BEFORE calls/CPU s":>20s} {"AFTER calls/CPU s":>20s}')
        names = sorted(set(a['functions']) | set(b['functions']),
                       key=lambda n: -max(a['functions'].get(n, [0, 0])[1], b['functions'].get(n, [0, 0])[1]))
        for function in names:
            x, y = a['functions'].get(function, [0, 0.0, 0]), b['functions'].get(function, [0, 0.0, 0])
            print(f'   {function:52s} {x[0]:9d}/{x[1]:9.2f} {y[0]:9d}/{y[1]:9.2f}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'census': census, 'phases': phases, 'compare': compare}
    print(f'(probe531 {command} at {datetime.now():%H:%M:%S})')
    raise SystemExit(commands[command](target, extra))
