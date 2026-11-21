"""Task 541 R: session-record check of the user's interactive Codex turn (read only).

usage: python -I rc541.py <codex sessions dir> <project> <U start epoch>

The Main is the session of the last codex:SessionStart claim in
<project>/.graphtraj/runner/main-sessions/continuity.jsonl written at or after the U stamp.
PASS needs all of:
  - the SessionStart hook bound that Main (main-sessions/finalize_<sha256("codex:"+session)>/session.yml
    exists; it is written at SessionStart, not by Stop. That Stop ran is shown by the USER's screenshot),
  - no checker was ever bound for it (no checks/* entry: GraphTraj binds a checker right after the
    native fork and before any model request) and no pending-* fork attempt remains,
  - the project's task graph is still empty (tasks/ has no Task),
  - the Main rollout (session_meta id = that session) has at least one user turn: an event_msg
    item_completed whose item.type is UserMessage (Codex 0.171.0) or an event_msg user_message (older
    Codex). response_item message role user is not counted: it also carries injected context.
Also printed for information: other rollouts of the project since the stamp (a checker fork is ephemeral
and may write none, so the binding records are the proof), and rollout lines naming the completion check.
"""
import hashlib
import json
import sys
from pathlib import Path


def claims(project: Path, since: float) -> list[str]:
    """Sessions of codex:SessionStart claims at or after ``since``, oldest first."""
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    if not path.is_file():
        return []
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return [r['session'] for r in records
            if float(r.get('at', 0)) >= since and str(r.get('entry') or '').startswith('codex:SessionStart')]


def rollouts(sessions: Path, project: Path, since: float) -> list[tuple[Path, dict]]:
    """Rollouts written since ``since`` whose session_meta cwd is the project, with that meta."""
    found = []
    for path in sessions.rglob('rollout-*.jsonl'):
        try:
            if path.stat().st_mtime < since:
                continue
            with path.open(encoding='utf-8') as handle:
                meta = json.loads(handle.readline()).get('payload') or {}
        except (OSError, ValueError):
            continue
        if isinstance(meta.get('cwd'), str) and Path(meta['cwd']).resolve() == project:
            found.append((path, meta))
    return found


def main(sessions: Path, project: Path, since: float) -> int:
    ok = True
    mains = claims(project, since)
    print(f'codex:SessionStart claims since {since}: {mains or "none"}')
    if not mains:
        print('FAIL: no Main claim since the U stamp; the USER part of U comes first')
        return 1
    session = mains[-1]
    directory = (project / '.graphtraj/runner/main-sessions'
                 / ('finalize_' + hashlib.sha256(('codex:' + session).encode()).hexdigest()))
    bound = (directory / 'session.yml').is_file()
    checks = sorted(str(p.relative_to(directory)) for p in directory.glob('checks/*'))
    pending = sorted(p.name for p in directory.glob('pending-*'))
    tasks = project / '.graphtraj/state/tasks'
    task_dirs = sorted(p.name for p in tasks.iterdir()) if tasks.is_dir() else []
    for name, passed, detail in (
        ('SessionStart hook bound the Main', bound, str(directory / 'session.yml')),
        ('no checker bound (no native fork)', not checks, checks or 'checks/: none'),
        ('no pending fork attempt', not pending, pending or 'none'),
        ('task graph still empty', not task_dirs, task_dirs or f'{tasks}: no Task'),
    ):
        ok &= passed
        print(f'CHECK {name}: {"PASS" if passed else "FAIL"} ({detail})')

    found = rollouts(sessions, project, since)
    main_rollouts = [path for path, meta in found if meta.get('id') == session]
    if not main_rollouts:
        print(f'FAIL: no rollout under {sessions} with session_meta id {session}')
        return 1
    path = main_rollouts[0]
    users, named = 0, []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') or {}
        item = payload.get('item') if isinstance(payload.get('item'), dict) else {}
        if record.get('type') == 'event_msg' and (
                payload.get('type') == 'user_message'                                       # older Codex
                or (payload.get('type') == 'item_completed' and item.get('type') == 'UserMessage')):  # 0.171.0
            users += 1
        if any(text in line for text in ('Completion Check', 'Reviewer Usage', 'Hook stopped')):
            named.append(number)
    ok &= users > 0
    print(f'CHECK Main rollout has a user turn: {"PASS" if users else "FAIL"} ({path}, user turns {users})')
    print(f'(info) Main rollout lines naming the completion check: {named or "none"}')
    others = [(str(p), meta.get('source'), meta.get('forked_from_id')) for p, meta in found if meta.get('id') != session]
    print(f'(info) other rollouts of the project since the stamp: {others or "none"}')
    print('CHECK 541 session records:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), float(sys.argv[3])))
