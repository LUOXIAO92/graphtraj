"""518 benchmark: a native Session lookup over Session archives shaped like production's.

  python -I bench518.py seed ROOT COUNT FIRST_MB   COUNT synthetic Claude archives under ROOT/sessions, each first
                                                   line ~FIRST_MB MB (a ~760-byte header, then observations), as
                                                   production's (M, 22:58: 1490 archives, first lines 5.09 GB,
                                                   headers 1.13 MB). Synthetic content only.
  python -I bench518.py time ROOT LABEL            with this interpreter's graftling: two fresh
                                                   SessionArchive(ROOT).native_header lookups of a missing Session
                                                   (each scans every archive) and two find_session(ROOT, <native ID>)
                                                   (one session_read by native ID), CPU and wall each.
"""
import hashlib
import json
import sys
import time
from pathlib import Path


def seed(root: Path, count: int, first_mb: float) -> None:
    observation = {'id': 'obs', 'kind': 'tool_result', 'final': ['claude', 'native', 'locator'],
                   'text': 'synthetic 518 observation ' + 'y' * 400}
    unit = len(json.dumps(observation, separators=(',', ':'))) + 1
    repeats = max(1, int(first_mb * 1e6 / unit))
    for number in range(count):
        native = f'5180{number:04d}-0000-4000-8000-{number:012d}'
        header = {'version': 5, 'id': 'claude:' + native, 'createdAt': 1794999810000, 'isSeeded': False,
                  'native': {'runtime': 'claude', 'sessionId': native,
                             'locator': '/Users/synthetic/.claude/projects/-synthetic-518-project-worktree/'
                                        + native + '.jsonl'},
                  'cwd': '/synthetic/518/project/.graphtraj/core/worktrees/518-synthetic-task',
                  'extraFields': {'graphtraj': {'harness_root': '/synthetic/518/project',
                                                'agent': '518-synthetic_task-handover0-engineer@engineer'}}}
        metadata = {'archiveVersion': 1, 'header': header, 'revision': 3, 'sources': {'native-hook': 100},
                    'pending': [], 'observations': [observation] * repeats}
        path = root / 'sessions' / hashlib.sha256(header['id'].encode()).hexdigest() / 'session.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'seeded {count} archives under {root}: first line ~{first_mb} MB, header '
          f'{len(json.dumps(header, separators=(",", ":")))} B')


def timed(label: str, call) -> None:
    began, cpu = time.perf_counter(), time.process_time()
    result = call()
    print(f'  {label}: {time.process_time() - cpu:7.2f} s CPU {time.perf_counter() - began:7.2f} s wall -> {result}')


def measure(root: Path, label: str) -> None:
    import graftling
    from graftling.sessions.archive import SessionArchive
    from graftling.sessions.reading import find_session

    paths = sorted((root / 'sessions').glob('*/session.jsonl'))
    first = sum(len(path.open('rb').readline()) for path in paths)
    native = json.loads(paths[0].open('rb').readline())['header']['native']['sessionId']
    print(f'== {label}: graftling {graftling.__file__}; {len(paths)} archives, first lines {first / 1e9:.2f} GB')
    for attempt in (1, 2):
        timed(f'fresh native_header (missing Session), run {attempt}',
              lambda: SessionArchive(root).native_header('claude', 'no-such-session-518'))
    for attempt in (1, 2):
        timed(f'find_session by native ID, run {attempt}', lambda: find_session(root, native).header['id'])


if __name__ == '__main__':
    command, root = sys.argv[1], Path(sys.argv[2])
    if command == 'seed':
        seed(root, int(sys.argv[3]), float(sys.argv[4]))
    else:
        measure(root, sys.argv[3])
