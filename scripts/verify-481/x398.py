"""481 X398 (read only, records only): where did g398's end go?

    x398.py PROJECT NAME
Prints the agent's control record(s), Runner session directories naming it (with pid liveness),
every Main notice naming it, and log lines naming it (capped), then two verdict lines.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verify-444'))
from probe import hit, keys_for  # noqa: E402  (verify-444/probe.py, unchanged)

FIELDS = ('state', 'status', 'host', 'creator', 'creator_session', 'parent', 'runtime', 'name',
          'execution', 'executions', 'execution_id', 'last_result', 'notification', 'outcome', 'ended_at')
budget = 120


def out(*parts: object) -> None:
    """Print one line while the ~120-line budget lasts."""
    global budget
    if budget > 0:
        print(*parts)
        budget -= 1


def alive(pid: object) -> str:
    """Report whether a recorded pid is still running."""
    try:
        os.kill(int(pid), 0)
    except (ValueError, TypeError):
        return 'not-a-pid'
    except ProcessLookupError:
        return 'ended'
    except PermissionError:
        return 'alive (not ours)'
    return 'alive'


def pids(value: object, path: str = ''):
    """Yield (path, value) for every key containing 'pid'."""
    if isinstance(value, dict):
        for key, item in value.items():
            if 'pid' in str(key).lower() and isinstance(item, (int, str)):
                yield f'{path}{key}', item
            yield from pids(item, f'{path}{key}.')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from pids(item, f'{path}{index}.')


def main() -> int:
    """Print the records and the two verdicts."""
    project, name = Path(sys.argv[1]), sys.argv[2]
    graphtraj = project / '.graphtraj'
    keys = keys_for(project, name)
    ids = sorted(k for k in keys if k != name)
    out('matching', name, 'as', sorted(keys))

    # Control records.
    ended, outcome = False, 'none'
    for agent in ids:
        path = graphtraj / 'swarm/control/agents' / f'{agent}.json'
        if not path.is_file():
            continue
        record = json.loads(path.read_text())
        out(f'== control {path.relative_to(project)}')
        for key in FIELDS:
            if key in record:
                out(f'  {key}: {json.dumps(record[key], ensure_ascii=False)[:400]}')
        out('  other keys:', sorted(set(record) - set(FIELDS)))
        last = record.get('last_result') or {}
        if isinstance(last, dict) and (last.get('ended_at') or last.get('outcome')):
            ended = True
            outcome = f"{last.get('outcome')}, notification {json.dumps(last.get('notification'))[:160]}"
        for where, pid in pids(record):
            out(f'  pid {where}={pid}: {alive(pid)}')

    # Runner session directories and files naming it.
    sessions = graphtraj / 'runner/sessions'
    for path in sorted(sessions.rglob('*')) if sessions.is_dir() else []:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(errors='replace')
        if not any(agent in text or agent in str(path) for agent in ids):
            continue
        out(f'== runner session file {path.relative_to(project)} ({path.stat().st_size} bytes)')
        try:
            import yaml
            document = yaml.safe_load(text) if path.suffix in {'.yml', '.yaml', '.json'} else None
        except Exception:
            document = None
        if isinstance(document, dict):
            for key in ('state', 'status', 'runtime', 'session', 'alias', 'execution', 'ended_at', 'outcome'):
                if key in document:
                    out(f'  {key}: {json.dumps(document[key], default=str)[:300]}')
            for where, pid in pids(document):
                out(f'  pid {where}={pid}: {alive(pid)}')
        else:
            for line in [line for line in text.splitlines() if any(agent in line for agent in ids)][:5]:
                out('  ', line[:300])

    # Main notice queues.
    queued = 0
    for path in sorted((graphtraj / 'runner/main-sessions/inbox').glob('*.jsonl')):
        cursor_file = path.with_suffix('.cursor')
        cursor = int(cursor_file.read_text()) if cursor_file.is_file() else 0
        for index, line in enumerate(path.read_text().splitlines()):
            if line.strip() and hit(line, keys):
                notice = json.loads(line)
                event = notice.get('event') or {}
                state = 'delivered' if index < cursor else 'PENDING'
                out(f'== notice {path.name}[{index}] {state}: alias {event.get("alias")} event {event.get("event")}'
                    f' id {str(notice.get("id"))[:16]}')
                if event.get('event') in {'completed', 'failed', 'interrupted'}:
                    queued += 1

    # Logs naming it.
    for root in (graphtraj / 'runner', graphtraj / 'swarm'):
        for path in sorted(root.rglob('*.log')) + sorted(root.rglob('*.jsonl')):
            if 'main-sessions/inbox' in str(path) or not path.is_file() or path.stat().st_size > 20_000_000:
                continue
            lines = [line for line in path.read_text(errors='replace').splitlines() if any(a in line for a in ids)]
            if lines:
                out(f'== log {path.relative_to(project)}: {len(lines)} line(s) naming it')
                for line in lines[-4:]:
                    out('  ', line[:300])

    print(f'g398 end recorded: {"YES" if ended else "NO"} ({outcome})')
    print(f'g398 end queued for a Main: {"YES" if queued else "NO"} ({queued} end notice(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())
