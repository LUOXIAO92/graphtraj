"""Task 540 C: read-only collection after the USER's interactive Codex run (BEFORE or AFTER).

usage: python -I c540.py <project> <codex sessions dir> <child name> <V start epoch> <copy dir>

Reads, never writes, the project and the Codex sessions; copies into <copy dir> only:
  continuity.jsonl             the project's runner/main-sessions/continuity.jsonl
  <agent>.json                 the child's agents control record (the record whose name is <child name>)
  summary.json                 what is printed below
Observables:
  1. continuity: every claim (entry, session, previous); CHECK no claim names the child's session.
  2. the child control record: per execution outcome, notification, notification_error; CHECK no notification_error.
  3. the Main (the record's creator.session): its rollout under <codex sessions dir> (session_meta id), and whether
     it holds a pushed notice (response_item function_call_output named graftling or send_message_to_thread)
     naming the child; CHECK at least one.
Verdict line: 'REPRODUCED' (child claimed Main and Main got no notice: the defect), 'FIXED' (all three CHECKs
PASS), else 'OTHER'. Exit 0 always when the files were readable (the verdict is judged by Main and the Leader).
"""
import json
import shutil
import sys
from pathlib import Path


def records(project: Path, name: str) -> list[Path]:
    """agents control records (agent-*.json holding executions) whose name is ``name``."""
    found = []
    for path in (project / '.graphtraj').rglob('agent-*.json'):
        if '.agent-worktrees' in path.parts:
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get('name') == name and 'executions' in document:
            found.append(path)
    return found


def rollout(sessions: Path, session: str) -> Path | None:
    for path in sorted(sessions.rglob('rollout-*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with path.open(encoding='utf-8') as handle:
                first = json.loads(handle.readline())
        except (OSError, ValueError):
            continue
        if (first.get('payload') or {}).get('id') == session:
            return path
    return None


def main(project: Path, sessions: Path, child: str, since: float, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {'project': str(project), 'child': child, 'since': since}
    continuity = next((p for p in (project / '.graphtraj/core/runner/main-sessions/continuity.jsonl',
                                   project / '.graphtraj/runner/main-sessions/continuity.jsonl') if p.is_file()), None)
    claims = []
    if continuity is None:
        print('continuity.jsonl: absent')
    else:
        shutil.copy2(continuity, out / 'continuity.jsonl')
        claims = [json.loads(line) for line in continuity.read_text(encoding='utf-8').splitlines() if line.strip()]
        print(f'continuity {continuity} ({len(claims)} claims; copied):')
        for claim in claims:
            mark = 'after start' if float(claim.get('at', 0)) >= since else 'before start'
            print(f'  {claim.get("entry")} session {claim.get("session")} previous '
                  f'{(claim.get("previous") or {}).get("session")} ({mark})')
    summary['claims'] = [{k: c.get(k) for k in ('at', 'entry', 'session', 'previous')} for c in claims]

    found = records(project, child)
    if not found:
        print(f'FAIL: no agents control record named {child} under {project}/.graphtraj')
        summary['verdict'] = 'OTHER'
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        return 1
    path = max(found, key=lambda p: p.stat().st_mtime)
    shutil.copy2(path, out / path.name)
    record = json.loads(path.read_text(encoding='utf-8'))
    main_session = (record.get('creator') or {}).get('session')
    child_session = record.get('session')
    print(f'child control record {path} (copied): agent {record.get("agent")}, runtime {record.get("runtime")}, '
          f'model {(record.get("selection") or {}).get("model")}, session {child_session}, creator session {main_session}')
    errors = []
    for execution in record.get('executions', []):
        print(f'  execution {execution.get("id")}: outcome {execution.get("outcome")}, notification '
              f'{execution.get("notification")}, notification_error {execution.get("notification_error")}')
        if execution.get('notification_error'):
            errors.append(execution['notification_error'])
    summary.update(agent=record.get('agent'), main_session=main_session, child_session=child_session,
                   executions=[{k: e.get(k) for k in ('id', 'outcome', 'notification', 'notification_error')}
                               for e in record.get('executions', [])])

    child_claims = [c for c in claims if c.get('session') == child_session]
    notices = []
    main_rollout = rollout(sessions, main_session) if main_session else None
    if main_rollout is None:
        print(f'Main rollout for session {main_session}: not found under {sessions}')
    else:
        print(f'Main rollout: {main_rollout}')
        for number, line in enumerate(main_rollout.read_text(encoding='utf-8').splitlines(), 1):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            payload = item.get('payload') or {}
            if (item.get('type') == 'response_item' and payload.get('type') == 'function_call_output'
                    and payload.get('name') in ('graftling', 'send_message_to_thread')):
                text = payload.get('output')
                text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
                if child in text or str(record.get('agent')) in text:
                    notices.append({'line': number, 'name': payload.get('name'), 'text': text[:600]})
        for notice in notices:
            print(f'  notice at line {notice["line"]} ({notice["name"]}): {notice["text"][:300]!r}')
    checks = [('continuity holds no claim by the child session', not child_claims),
              ('child control record has no notification_error', not errors),
              ('Main rollout holds the child completion notice', bool(notices))]
    for label, passed in checks:
        print(f'CHECK 540 {label}: {"PASS" if passed else "FAIL"}')
    verdict = ('FIXED' if all(passed for _, passed in checks)
               else 'REPRODUCED' if child_claims and not notices else 'OTHER')
    print(f'VERDICT 540: {verdict}')
    summary.update(main_rollout=str(main_rollout) if main_rollout else None, child_claims=child_claims,
                   notices=notices, checks={label: passed for label, passed in checks}, verdict=verdict)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(f'copied to {out}: {sorted(p.name for p in out.iterdir())}')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 6:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), Path(sys.argv[5])))
