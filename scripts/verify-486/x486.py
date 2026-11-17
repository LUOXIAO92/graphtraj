"""486 (read only, records only): NAME's latest execution end and its Main notices, by event identity.

    x486.py PROJECT NAME dump                 print the record and every notice naming its execution
    x486.py PROJECT NAME queued SESSION SECS  wait <= SECS for the end recorded 'interrupted' and queued
                                              exactly once, undelivered, for dsh:SESSION
    x486.py PROJECT NAME delivered SESSION    the end's notice id is in dsh:SESSION's queue exactly once,
                                              delivered (cursor past it), and in no other queue

The control record keeps executions[-1] with state/outcome/notification; a notice is
``{"id", "event": {"alias", "event", "execution"}}`` in .graphtraj/runner/main-sessions/inbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path


def record_of(project: Path, name: str) -> tuple[str, dict] | None:
    """Return (agent id, control record) of the Agent named NAME."""
    for path in sorted((project / '.graphtraj/swarm/control/agents').glob('*.json')):
        record = json.loads(path.read_text())
        if record.get('name') == name:
            return path.stem, record
    return None


def alive(pid: object) -> str:
    """Report whether a recorded pid still runs."""
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError):
        return 'no pid'
    except ProcessLookupError:
        return 'ended'
    except PermissionError:
        return 'alive (not ours)'
    return 'alive'


def queues(project: Path) -> dict[str, tuple[list[dict], int]]:
    """Every Main queue by 'runtime:session' (from the claims), with its cursor."""
    runner = project / '.graphtraj/runner/main-sessions'
    found = {}
    path = runner / 'continuity.jsonl'
    for line in path.read_text().splitlines() if path.is_file() else []:
        claim = json.loads(line)
        key = f"{claim['runtime']}:{claim['session']}"
        inbox = runner / 'inbox' / (hashlib.sha256(key.encode()).hexdigest() + '.jsonl')
        lines = [json.loads(x) for x in inbox.read_text().splitlines() if x.strip()] if inbox.is_file() else []
        cursor = inbox.with_suffix('.cursor')
        found[key] = (lines, int(cursor.read_text()) if cursor.is_file() else 0)
    return found


def places(project: Path, execution: str) -> list[tuple[str, str, str, str]]:
    """(queue, notice id, event, delivered|PENDING) for each notice of EXECUTION."""
    return [(key, notice['id'], notice['event'].get('event'), 'delivered' if index < cursor else 'PENDING')
            for key, (lines, cursor) in queues(project).items()
            for index, notice in enumerate(lines) if notice['event'].get('execution') == execution]


def show(project: Path, name: str) -> tuple[str, dict] | None:
    """Print the record's latest execution and its notices."""
    found = record_of(project, name)
    if found is None:
        print(f'{name}: no control record')
        return None
    agent, record = found
    last = record['executions'][-1]
    process = last.get('process') or {}
    print(f"{name} = {agent} | host {record.get('host')} | parent {record.get('parent')} | creator session "
          f"{(record.get('creator') or {}).get('session')}")
    print(f"  executions[-1] {last['id']} {last.get('operation')}: state {last.get('state')} outcome "
          f"{last.get('outcome')} error {(last.get('error') or {}).get('code')} notification {last.get('notification')}"
          f" | worker_pid {process.get('worker_pid')} {alive(process.get('worker_pid'))}"
          f" | runtime_pid {process.get('runtime_pid')} {alive(process.get('runtime_pid'))}")
    for key, identity, event, state in places(project, last['id']):
        print(f'  notice {identity} event {event} in {key}: {state}')
    return found


def main() -> int:
    """Run one of the three reads."""
    project, name, command, *rest = Path(sys.argv[1]), sys.argv[2], sys.argv[3], *sys.argv[4:]
    if command == 'dump':
        show(project, name)
        return 0
    session = rest[0]
    deadline = time.time() + (float(rest[1]) if command == 'queued' else 0)
    while True:
        found = record_of(project, name)
        if found is not None:
            last = found[1]['executions'][-1]
            mine = [p for p in places(project, last['id']) if p[0] == f'dsh:{session}']
            others = [p for p in places(project, last['id']) if p[0] != f'dsh:{session}']
            ids = {p[1] for p in mine}
            ended = last.get('state') == 'ended' and last.get('outcome') == 'interrupted'
            if command == 'queued':
                ok = ended and len(mine) == 1 and mine[0][3] == 'PENDING' and not others
            else:
                ok = ended and len(mine) == 1 and len(ids) == 1 and mine[0][3] == 'delivered' and not others
            if ok or time.time() >= deadline:
                break
        elif time.time() >= deadline:
            break
        time.sleep(3)
    show(project, name)
    if found is None:
        print(f'FAIL 486 {command}: no record of {name}')
        return 1
    what = ('end recorded interrupted and queued exactly once, undelivered, for dsh:' if command == 'queued'
            else 'end delivered exactly once by event id to dsh:')
    print(f"{'PASS' if ok else 'FAIL'} 486 {command}: {name} {what}{session} "
          f"({len(mine)} notice(s) there, ids {sorted(ids)}, {len(others)} elsewhere)")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
