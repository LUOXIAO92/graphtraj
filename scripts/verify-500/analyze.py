"""Task 500: join the survivors' deaths to the kill log of one instrumented run. Read only.

    python -I analyze.py <kill-log dir> [<repeat result dir with counts.txt> | -] [<label>]

For every survivor the patched host test watched: when it was first found gone, whether the test's own
cleanup kill (sender = the watching pytest process) came before that, and otherwise every logged signal
that could have reached it (os.kill to pid or -pid, os.killpg to pid, kill(-1)), the survivor's own lines
(start, caught signal, normal exit), its last heartbeat (time, ppid) and kill commands run by a shell.
Prints per-run counts: tests watched, survivors, early deaths (gone before the test's cleanup), early
deaths with a matched sender, and the survivor tests' failures from counts.txt.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

SURVIVOR_TESTS = ('test_the_next_host_shows_a_surviving_runtime_as_active',
                  'test_the_next_host_names_a_surviving_runtime_and_records_no_stop')


def lines(path: Path):
    for line in path.read_text(errors='replace').splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def main(logs: Path, results: Path | None, label: str) -> int:
    kills, own, commands = [], collections.defaultdict(list), []
    watched, gone = {}, {}
    for path in sorted(logs.glob('*.jsonl')):
        for record in lines(path):
            if path.name.startswith('survivors-'):
                key = record['pid']
                if record['event'] == 'watch':
                    watched[key] = record
                elif record['event'] == 'gone':
                    gone.setdefault(key, record)
            elif record['kind'] in ('os.kill', 'os.killpg'):
                kills.append(record)
            elif record['kind'].startswith('survivor-'):
                own[record['pid']].append(record)
            else:
                commands.append(record)
    beats = {}
    for path in logs.glob('hb-*'):
        try:
            when, ppid = path.read_text().split()
            beats[int(path.name[3:])] = (float(when), int(ppid))
        except (OSError, ValueError):
            continue

    def reaches(kill: dict, pid: int) -> bool:
        target = kill['target']
        return target == -1 or (kill['kind'] == 'os.kill' and target in (pid, -pid)) or (
            kill['kind'] == 'os.killpg' and target == pid)

    tests = {(record['watcher'], record['test']) for record in watched.values()}
    early, matched_early, senders = [], 0, collections.Counter()
    print(f'== {label}: kill log {logs}')
    for pid, watch in sorted(watched.items(), key=lambda item: item[1]['t']):
        end = gone.get(pid)
        reaching = [kill for kill in kills if reaches(kill, pid) and kill['t'] >= watch['t'] - 130]
        cleanup = [kill for kill in reaching if kill['pid'] == watch['watcher']]
        others = [kill for kill in reaching if kill['pid'] != watch['watcher']]
        first_cleanup = min((kill['t'] for kill in cleanup), default=None)
        if end is None or (first_cleanup is not None and end['t'] >= first_cleanup) and not others:
            continue  # alive until the test's own cleanup (the expected end)
        if first_cleanup is not None and end['t'] >= first_cleanup:
            kind = 'ended at cleanup, but other senders also reached it'
        else:
            kind = 'EARLY: gone before the test cleanup'
            early.append(pid)
            matched_early += bool(others)
        print(f'\n-- survivor {pid} ({kind}); test {watch["test"]}')
        print(f'   watch from {watch["t"]:.3f}; first gone seen {end["t"] if end else None}; '
              f'test cleanup kill {first_cleanup}')
        beat = beats.get(pid)
        print(f'   last heartbeat {beat[0] if beat else None} (ppid then {beat[1] if beat else None}); '
              f'own lines: {[(line["kind"], line.get("sig"), round(line["t"], 3)) for line in own.get(pid, [])]}')
        for kill in others:
            senders[(tuple(kill['argv'][:3]), (kill.get('stack') or ['?'])[-1])] += 1
            print(f'   SENDER pid {kill["pid"]} ppid {kill["ppid"]} {kill["kind"]}({kill["target"]}, {kill["sig"]}) '
                  f'at {kill["t"]:.3f} argv {kill["argv"]} test {kill.get("test")!r}')
            for frame in kill.get('stack') or []:
                print(f'      {frame}')
        if not others:
            print('   no Python sender logged a signal that reaches this pid')
    print(f'\n== {label} summary: tests watched {len(tests)}, survivors {len(watched)}, '
          f'early deaths {len(early)}, early deaths with a matched Python sender {matched_early}')
    for (argv, frame), count in senders.most_common():
        print(f'   sender x{count}: {list(argv)} at {frame}')
    if commands:
        print(f'   kill commands run through a shell/exec: {len(commands)}')
        for record in commands[:20]:
            print(f'      {record["kind"]} {record.get("command")} from pid {record["pid"]} test {record.get("test")!r}')
    if results is not None and (results / 'counts.txt').is_file():
        rows = [row for row in (results / 'counts.txt').read_text().splitlines()
                if any(name in row for name in SURVIVOR_TESTS)]
        print('   survivor tests in counts.txt (failed+error passed skipped test):')
        print('\n'.join(f'      {row.strip()}' for row in rows) or '      none')
        lookups = sum('ProcessLookupError' in path.read_text(errors='replace')
                      for path in (results / 'failures').glob('*surviving*'))
        print(f'   survivor-test failure texts with ProcessLookupError: {lookups}')
        print('   ' + ((results / 'counts.txt').read_text().splitlines() or [''])[-1])
    return 0


if __name__ == '__main__':
    results = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != '-' else None
    sys.exit(main(Path(sys.argv[1]), results, sys.argv[3] if len(sys.argv) > 3 else 'run'))
