"""Task 535 Vr: read the interactive Codex Main's rollout of the isolated project (read only).

usage: python -I vr535.py <codex sessions dir> <project> <child name> <V start epoch>

The Main is the session of the last continuity claim (<project>/.graphtraj/runner/main-sessions/continuity.jsonl)
written at or after the V start stamp whose entry starts with codex:SessionStart; its rollout is the one whose
session_meta id is that session (try 2 picked a child's newer rollout with the same cwd). FAIL if none.

Observables, per pushed notice (response_item function_call_output named 'graftling', the record the model reads;
484 I2 showed it is the toolOutput of graftling's send_host_event):
  - not an escaped JSON document (before 535: json.dumps of the GraphTraj event),
  - no 'permissions', 'session_id' or 'terminal_confirmed' field names,
  - names the child (alias or name) and carries an execution id (the Main still has its ids),
  - its content keeps Markdown lines (a heading, a list item or a quote) as real lines.
Also lists, for information, records that hold the display hook's box ('agents/MCP') or the sent message body,
so the screenshot of the sent message can be matched to the rollout. Exit 0 = every notice PASS (at least one).
"""
import json
import re
import sys
from pathlib import Path

FORBIDDEN = ('permissions', 'session_id', 'terminal_confirmed')
MARKDOWN = re.compile(r'^(#{1,6} |[-*] |\d+\. |> )', re.M)


def rollouts(sessions: Path, project: Path) -> list[Path]:
    """Return rollouts whose session_meta cwd is the project, newest first."""
    found = []
    for path in sessions.rglob('rollout-*.jsonl'):
        try:
            with path.open(encoding='utf-8') as handle:
                first = json.loads(handle.readline())
        except (OSError, ValueError):
            continue
        cwd = (first.get('payload') or {}).get('cwd')
        if isinstance(cwd, str) and Path(cwd).resolve() == project:
            found.append(path)
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def session_id(path: Path) -> str | None:
    """session_meta.payload.id of one rollout."""
    try:
        with path.open(encoding='utf-8') as handle:
            return (json.loads(handle.readline()).get('payload') or {}).get('id')
    except (OSError, ValueError):
        return None


def judge(text: str, child: str) -> list[tuple[str, bool]]:
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return [
        ('not an escaped JSON document', not isinstance(parsed, dict)),
        ('no permissions/session_id/terminal_confirmed', not any(f'"{key}"' in text or f'{key}:' in text for key in FORBIDDEN)),
        (f'names the child ({child} or agent-…)', child in text or 'agent-' in text),
        ('carries an execution id (32 hex)', re.search(r'\b[0-9a-f]{32}\b', text) is not None),
        ('Markdown lines kept as lines', MARKDOWN.search(text) is not None),
    ]


def main_session(project: Path, since: float) -> str | None:
    """The session of the last codex:SessionStart claim written at or after ``since`` (the Main, not the child)."""
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    try:
        claims = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        print(f'continuity unreadable: {path}: {error}')
        return None
    print(f'continuity {path}: {[(c.get("entry"), c.get("session")) for c in claims]}')
    main = [c for c in claims if float(c.get('at', 0)) >= since and str(c.get('entry') or '').startswith('codex:SessionStart')]
    return main[-1]['session'] if main else None


def main(sessions: Path, project: Path, child: str, since: float) -> int:
    session = main_session(project, since)
    if session is None:
        print(f'FAIL: no codex:SessionStart Main claim in continuity at or after {since}; the USER part of Vb/V comes first')
        return 1
    paths = [path for path in rollouts(sessions, project) if session_id(path) == session]
    if not paths:
        print(f'FAIL: no rollout under {sessions} whose session_meta id is the Main session {session}')
        return 1
    path = paths[0]
    print(f'Main session {session}: rollout {path}')
    notices, shown = [], []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') or {}
        kind = f"{record.get('type')}/{payload.get('type')}"
        if kind == 'response_item/function_call_output' and payload.get('name') == 'graftling':
            output = payload.get('output')
            notices.append((number, output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)))
        elif 'agents/MCP' in line or 'Second message' in line:
            shown.append((number, kind))
    print(f'pushed notices (function_call_output name graftling): {len(notices)}')
    ok = bool(notices)
    for number, text in notices:
        print(f'---- notice at line {number} (first 600 chars):')
        print(text[:600])
        for name, passed in judge(text, child):
            ok &= passed
            print(f'  CHECK {name}: {"PASS" if passed else "FAIL"}')
    print(f'records holding the display box or the sent message (information): {shown[:12] or "none"}')
    print('CHECK 535 notices:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3], float(sys.argv[4])))
