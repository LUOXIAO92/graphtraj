"""518 helper next to verify-501's probe.py (which still dispatches the member and samples its Worker).

Usage (a scratch venv's Python, -I):
  python -I probe518.py census HARNESS -       read only: sizes of production's records a Worker may read
                                               (Worldline, Runner Sessions, retained Traces, agents records, archives)
  python -I probe518.py clone PROJECT HARNESS  copy production's Runner Session records into PROJECT's Runner and its
                                               agents records into PROJECT's core data root, sanitized: only
                                               .yml/.json/.jsonl files, no tool-process or descendants records, each
                                               record parsed and rewritten (every Harness and home path moved into
                                               PROJECT, every *pid value 99999, above macOS's largest pid, so no process
                                               has it; every *marker value blanked) and refused when a production path
                                               remains. Production is only read.
  python -I probe518.py phases RESULT PROJECT  Worker CPU in: start, 30 s before the child's creation, 30 s after it,
                                               rest of the child's run, after its end; per phase the busiest functions
                                               (inclusive samples) and the whole-record reads the profiler counted
  python -I probe518.py compare BEFORE AFTER   the two phase tables side by side
Signals nothing; reads no key.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verify-501'))
import probe  # noqa: E402  (verify-501's helper: IDLE, seconds, CHILD)

SAFE_PID = 99999
PREFIX = b'{"archiveVersion":1,"header":'  # how graftling's compact encoding starts an archive's first line
PHASES = ('start', 'pre30', 'post30', 'child', 'after')


def _sanitize(value, replacements: list[tuple[str, str]], key: str = ''):
    """Rewrite one parsed record: paths into the project, every *pid value to SAFE_PID, markers blanked.

    Tool markers live in the tool-process records, which are not copied; any other marker value is blanked too,
    so no copied record names a live production process by pid or marker.
    """
    if isinstance(value, dict):
        return {_sanitize(name, replacements): _sanitize(item, replacements, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, replacements, key) for item in value]
    lowered = key.lower()
    if isinstance(value, int) and not isinstance(value, bool) and 'pid' in lowered:
        return SAFE_PID
    if isinstance(value, str):
        if 'marker' in lowered:
            return 'sanitized518'
        for old, new in replacements:
            value = value.replace(old, new)
    return value


def _named(value, needles: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(_named(item, needles) for item in value.values()) or any(_named(k, needles) for k in value)
    if isinstance(value, list):
        return any(_named(item, needles) for item in value)
    return isinstance(value, str) and any(needle in value for needle in needles)


def _size(paths) -> tuple[int, int]:
    count = total = 0
    for path in paths:
        try:
            total += path.stat().st_size
            count += 1
        except OSError:
            pass
    return count, total


def census(harness: Path, _unused: str) -> int:
    """Count and size what a member's Worker may read in production (stat and line counts only; nothing parsed)."""
    core, swarm = harness / '.graphtraj/core', harness / '.graphtraj/swarm'
    shards = sorted((core / 'state/worldline').glob('*.jsonl'))
    lines = 0
    for shard in shards:
        with shard.open('rb') as stream:
            lines += sum(1 for _ in stream)
    count, total = _size(shards)
    print(f'Worldline: {count} shards, {lines} events, {total / 1e6:.1f} MB')
    sessions = [path for path in (core / 'runner/sessions').iterdir() if path.is_dir()]
    kinds = defaultdict(lambda: [0, 0])
    for path in (core / 'runner/sessions').glob('*/*.yml'):
        kind = re.sub(r'-[0-9a-f]{32}\.yml$', '-<id>.yml', path.name)
        kinds[kind][0] += 1
        kinds[kind][1] += path.stat().st_size
    print(f'Runner Sessions: {len(sessions)} directories, {sum(c for c, _ in kinds.values())} .yml files, '
          f'{sum(b for _, b in kinds.values()) / 1e6:.1f} MB of YAML')
    for kind, (number, size) in sorted(kinds.items(), key=lambda item: -item[1][1])[:8]:
        print(f'   {kind:32s} {number:5d} files {size / 1e6:8.1f} MB')
    retained = [path for path in (core / 'state/tasks').glob('*/teams/*/traces/*/runner') if (path / 'session.yml').is_file()]
    print(f'Tasks: {len(list((core / "state/tasks").glob("*/task.yml")))}; retained Trace Session records: {len(retained)}')
    count, total = _size((swarm / 'control/agents').glob('*.json'))
    print(f'agents records: {count}, {total / 1e6:.1f} MB')
    count, total = _size((swarm / 'sessions').glob('*/session.jsonl'))
    print(f'Session archives: {count}, {total / 1e6:.1f} MB')
    print(f'native directories: {len(list((swarm / "native").glob("*")))}')
    return 0


def clone(project: Path, harness: str) -> int:
    """Sanitized copy of production's Runner Session records into the isolated project's Runner."""
    import yaml
    from graphtraj.configuration.project_configuration import runner_directory

    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    dumper = getattr(yaml, 'CSafeDumper', yaml.SafeDumper)
    source = Path(harness) / '.graphtraj/core/runner/sessions'
    target = runner_directory(project) / 'sessions'
    home = os.path.expanduser('~')
    replacements = [(str(Path(harness)), str(project)), (home, str(project / 'home'))]
    needles = (str(Path(harness)), home + '/')
    directories = files = size = 0
    for directory in sorted(source.iterdir()):
        if (directory.is_symlink() or not directory.is_dir() or (target / directory.name).exists()
                or directory.name.startswith(probe.TASK + '-')):
            continue  # the probe Task's own aliases stay the probe's
        made = False
        for path in sorted(directory.iterdir()):
            if (path.is_symlink() or not path.is_file() or path.suffix not in {'.yml', '.json', '.jsonl'}
                    or path.name.startswith(('tool-processes', 'tool-descendants'))):
                continue
            text = path.read_text(encoding='utf-8', errors='strict')
            try:
                if path.suffix == '.yml':
                    record = _sanitize(yaml.load(text, Loader=loader), replacements)
                    named, text = _named(record, needles), yaml.dump(record, Dumper=dumper, allow_unicode=True,
                                                                     sort_keys=False)
                elif path.suffix == '.json':
                    record = _sanitize(json.loads(text), replacements)
                    named, text = _named(record, needles), json.dumps(record, ensure_ascii=False)
                else:
                    records = [_sanitize(json.loads(line), replacements) for line in text.splitlines() if line.strip()]
                    named = _named(records, needles)
                    text = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in records)
            except (ValueError, yaml.YAMLError) as error:
                print(f'skipped unreadable {path.name} in {directory.name}: {type(error).__name__}')
                continue
            if named:
                print(f'STOP: {path} still names a production path after rewriting; nothing more is copied')
                return 1
            if not made:
                (target / directory.name).mkdir(parents=True)
                made, directories = True, directories + 1
            (target / directory.name / path.name).write_text(text, encoding='utf-8')
            files, size = files + 1, size + len(text)
    print(f'cloned {directories} Runner Session directories, {files} files, {size / 1e6:.1f} MB into {target} '
          f'(paths rewritten into {project}; pids {SAFE_PID})')
    # The agents records the core scans (graftling control/agents), sanitized the same way.
    from graphtraj.interfaces.agents import swarm_root

    source, target = Path(harness) / '.graphtraj/swarm/control/agents', swarm_root(project) / 'control' / 'agents'
    try:
        records = sorted(path for path in source.glob('agent-*.json') if path.is_file() and not path.is_symlink())
    except OSError as error:
        print(f'agents records: not readable here ({type(error).__name__}); none copied')
        return 0
    target.mkdir(parents=True, exist_ok=True)
    copied = size = 0
    for path in records:
        if (target / path.name).exists():
            continue
        try:
            record = _sanitize(json.loads(path.read_text(encoding='utf-8')), replacements)
        except (OSError, ValueError) as error:
            print(f'skipped unreadable {path.name}: {type(error).__name__}')
            continue
        if _named(record, needles):
            print(f'STOP: {path} still names a production path after rewriting; nothing more is copied')
            return 1
        text = json.dumps(record, ensure_ascii=False)
        (target / path.name).write_text(text, encoding='utf-8')
        copied, size = copied + 1, size + len(text)
    print(f'cloned {copied} agents records, {size / 1e6:.1f} MB into {target} (same rewriting)')
    return 0


def archives(harness: Path, _unused: str) -> int:
    """Read only: what one archive-header lookup costs over production's Session archives.

    ``SessionArchive(root).native_header`` (graftling) decodes the whole first line of every archive to take its
    header; the first line also holds the archive's resolved observations. This times exactly that call (a fresh
    instance, as ``find_session`` and Claude collection make), and, for comparison, reading only each header.
    """
    import time

    import graftling
    from graftling.sessions.archive import SessionArchive
    from graftling.sessions.reading import find_session

    print(f'graftling imported from: {graftling.__file__}')
    root = harness / '.graphtraj/swarm'
    paths = sorted((root / 'sessions').glob('*/session.jsonl'))
    first = header = 0
    for path in paths:
        with path.open('rb') as stream:
            line = stream.readline()
        first += len(line)
        if line.startswith(PREFIX):
            header += len(json.dumps(json.JSONDecoder().raw_decode(line.decode(), len(PREFIX))[0]))
    total = sum(path.stat().st_size for path in paths)
    print(f'Session archives: {len(paths)}, {total / 1e9:.2f} GB; first lines {first / 1e9:.2f} GB, '
          f'of which headers {header / 1e6:.2f} MB')
    for attempt in (1, 2):
        began, cpu = time.perf_counter(), time.process_time()
        found = SessionArchive(root).native_header('claude', 'no-such-session-518')
        print(f'fresh SessionArchive(root).native_header (as find_session / Claude collection), run {attempt}: '
              f'{time.process_time() - cpu:.2f} s CPU, {time.perf_counter() - began:.2f} s wall (found {found})')
    began, cpu = time.perf_counter(), time.process_time()
    found = find_session(root, 'no-such-session-518')
    print(f'find_session by a missing native ID (one session_read): {time.process_time() - cpu:.2f} s CPU, '
          f'{time.perf_counter() - began:.2f} s wall (found {found})')
    began, cpu = time.perf_counter(), time.process_time()
    for path in paths:
        with path.open('rb') as stream:
            chunk = stream.read(65536)
        if chunk.startswith(PREFIX):
            try:
                json.JSONDecoder().raw_decode(chunk.decode('utf-8', 'ignore'), len(PREFIX))
            except ValueError:
                pass
    print(f'reading only each header (64 KiB prefix): {time.process_time() - cpu:.2f} s CPU, '
          f'{time.perf_counter() - began:.2f} s wall')
    return 0


def _epoch(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return None


def _child_times(project: Path) -> tuple[float | None, float | None]:
    for path in (project / '.graphtraj/swarm/control/agents').glob('*.json'):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('name') == probe.CHILD:
            executions = record.get('executions') or [{}]
            created = _epoch(record.get('created_at')) or _epoch(executions[0].get('started_at'))
            return created, _epoch(executions[0].get('ended_at'))
    return None, None


def _cpu_at(rows: list[dict], at: float) -> float:
    """Cumulative Worker CPU at ``at``, linear between the ps samples around it."""
    if at <= rows[0]['at']:
        return rows[0]['cpu']
    for a, b in zip(rows, rows[1:]):
        if a['at'] <= at <= b['at']:
            return a['cpu'] + (b['cpu'] - a['cpu']) * (at - a['at']) / max(b['at'] - a['at'], 1e-9)
    return rows[-1]['cpu']


def phases(result_file: Path, project: str) -> int:
    result = json.loads(result_file.read_text())
    rows = [json.loads(line) for line in Path(result['raw']).read_text().splitlines() if line.strip()]
    if len(rows) < 2:
        print('phases: fewer than two ps samples')
        return 1
    for row in rows:
        row['cpu'] = probe.seconds(row['ps'].split()[3])
    created, ended = _child_times(Path(project))
    first, last = rows[0]['at'], rows[-1]['at']
    if created is None:
        print('phases: no child record; only the whole run is reported')
        created = ended = last
    ended = ended or last
    bounds = {'start': (first, created - 30), 'pre30': (created - 30, created), 'post30': (created, created + 30),
              'child': (created + 30, ended), 'after': (ended, last)}
    table = {}
    print(f"== {result['label']} phases (child created {datetime.fromtimestamp(created):%H:%M:%S}, "
          f"ended {datetime.fromtimestamp(ended):%H:%M:%S}; ps every ~10 s, interpolated)")
    for name in PHASES:
        begin, end = max(bounds[name][0], first), min(bounds[name][1], last)
        if end <= begin:
            table[name] = None
            print(f'phase {name:6s}: n/a')
            continue
        cpu = _cpu_at(rows, end) - _cpu_at(rows, begin)
        table[name] = [round(cpu, 2), round(end - begin, 1)]
        print(f'phase {name:6s}: {cpu:6.1f} CPU-s / {end - begin:6.0f} wall-s = {cpu / (end - begin):.3f}')
    total = rows[-1]['cpu'] - rows[0]['cpu']
    print(f'whole run: {total:.1f} CPU-s / {last - first:.0f} wall-s = {total / (last - first):.3f}')
    result['phases518'] = table
    prof = Path(result['prof'])
    if prof.is_file():
        _hot(prof, bounds)
    else:
        print(f'profile: none at {prof}')
    result_file.write_text(json.dumps(result, indent=2))
    return 0


def _hot(prof: Path, bounds: dict) -> None:
    """Per phase: functions by inclusive working samples, and the counted whole-record reads."""
    windows = [json.loads(line) for line in prof.read_text().splitlines() if line.strip()]

    def phase_of(window: dict) -> str:
        middle = window['at'] - window['wall'] / 2
        for name in PHASES:
            if bounds[name][0] <= middle < bounds[name][1]:
                return name
        return 'after' if middle >= bounds['after'][0] else 'start'

    inclusive, calls, cpu = defaultdict(Counter), defaultdict(lambda: defaultdict(lambda: [0, 0])), defaultdict(float)
    print(f'profile: {len(windows)} windows ({prof}); per window: phase, CPU share, counted reads')
    for window in windows:
        name = phase_of(window)
        cpu[name] += window['cpu']
        for reader, (number, size) in (window.get('calls') or {}).items():
            calls[name][reader][0] += number
            calls[name][reader][1] += size
        for thread, stacks in window['threads'].items():
            for stack, count in stacks.items():
                frames = stack.split(' < ')
                if probe.IDLE.search(frames[0]):
                    continue
                for frame in {f'[{thread.split(" ")[0]}] ' + ':'.join(item.split(':')[:2]) for item in frames}:
                    inclusive[name][frame] += count
        reads = ', '.join(f'{reader.split(".")[-1]} {number}' for reader, (number, _) in
                          sorted((window.get('calls') or {}).items()))
        print(f"  {datetime.fromtimestamp(window['at']):%H:%M:%S} {name:6s} cpu {window['cpu'] / window['wall']:.2f}"
              f" | {reads or '-'}")
    for name in PHASES:
        print(f'-- phase {name}: Worker CPU {cpu[name]:.1f} s; reads: ' + (', '.join(
            f'{reader} {number} calls / {size / 1e6:.1f} M chars' for reader, (number, size) in
            sorted(calls[name].items())) or '-'))
        for frame, count in inclusive[name].most_common(25):
            print(f'   x{count:6d} {frame}')


def compare(before: Path, after: str) -> int:
    first, second = json.loads(before.read_text()), json.loads(Path(after).read_text())
    print(f"{'phase':8s} {first['label']:>22s} {second['label']:>22s}   (CPU-s / wall-s = share)")
    for name in PHASES:
        cells = []
        for item in (first, second):
            value = (item.get('phases518') or {}).get(name)
            cells.append(f'{value[0]:6.1f}/{value[1]:4.0f}={value[0] / value[1]:.3f}' if value else 'n/a')
        print(f'{name:8s} {cells[0]:>22s} {cells[1]:>22s}')
    return 0


if __name__ == '__main__':
    command, target, extra = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    commands = {'census': census, 'archives': archives, 'clone': clone, 'phases': phases, 'compare': compare}
    raise SystemExit(commands[command](target, extra))
