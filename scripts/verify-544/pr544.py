"""Task 544 Pr: read the probe session's rollout (read only) and judge what the model received.

usage: python -I pr544.py <codex sessions dir> <project> <P start epoch>

The rollout = newest rollout-*.jsonl under <sessions> whose session_meta cwd is <project> and whose file changed at or
after <P start epoch> and that holds a send_note call. Printed: the response_item function_call for send_note, its
function_call_output (exactly what the model got) and the assistant messages after it.
PASS iff that output carries PROBE-SC-544 (structuredContent) and NOT PROBE-BODY-544 (the content body).
"""
import json
import sys
from pathlib import Path


def candidates(sessions: Path, project: Path, since: float) -> list[Path]:
    found = []
    for path in sessions.rglob('rollout-*.jsonl'):
        try:
            if path.stat().st_mtime < since:
                continue
            with path.open(encoding='utf-8') as handle:
                cwd = (json.loads(handle.readline()).get('payload') or {}).get('cwd')
        except (OSError, ValueError):
            continue
        if isinstance(cwd, str) and Path(cwd).resolve() == project and 'send_note' in path.read_text(encoding='utf-8'):
            found.append(path)
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def text_of(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def main(sessions: Path, project: Path, since: float) -> int:
    paths = candidates(sessions, project, since)
    if not paths:
        print(f'FAIL: no rollout under {sessions} with cwd {project}, changed after {since}, holding send_note')
        return 1
    path = paths[0]
    print(f'rollout: {path} (of {len(paths)} candidates)')
    calls, outputs, replies = set(), [], []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        try:
            payload = json.loads(line).get('payload') or {}
        except ValueError:
            continue
        kind = payload.get('type')
        if kind in ('function_call', 'custom_tool_call') and 'send_note' in f"{payload.get('namespace') or ''}{payload.get('name') or ''}":
            calls.add(payload.get('call_id'))
            print(f'---- line {number} {kind} name={payload.get("name")} namespace={payload.get("namespace")}')
            print(text_of(payload.get('arguments') or payload.get('input'))[:800])
        elif kind in ('function_call_output', 'custom_tool_call_output') and payload.get('call_id') in calls:
            outputs.append(text_of(payload.get('output')))
            print(f'---- line {number} {kind} (what the model received):')
            print(outputs[-1][:1500])
        elif kind == 'message' and payload.get('role') == 'assistant' and outputs:
            replies.append(''.join(part.get('text', '') for part in payload.get('content') or [] if isinstance(part, dict)))
            print(f'---- line {number} assistant reply:')
            print(replies[-1][:1500])
    if not outputs:
        print('FAIL: no function_call_output for a send_note call')
        return 1
    seen = '\n'.join(outputs)
    sc, body = 'PROBE-SC-544' in seen, 'PROBE-BODY-544' in seen
    print(f'CHECK model input carries PROBE-SC-544 (structuredContent): {"PASS" if sc else "FAIL"}')
    print(f'CHECK model input lacks PROBE-BODY-544 (content body): {"PASS" if not body else "FAIL"}')
    print(f'model reply mentions PROBE-SC-544: {any("PROBE-SC-544" in r for r in replies)} | '
          f'mentions PROBE-BODY-544: {any("PROBE-BODY-544" in r for r in replies)} (information)')
    ok = sc and not body
    print('CHECK 544 probe model input:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]).resolve(), float(sys.argv[3])))
