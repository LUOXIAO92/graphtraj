"""Task 536 Vr: read an isolated Pi Main Session and judge its GraphTraj notices. Read only.

usage: python -I vr536.py <pi session dir or .jsonl> <child name>

PASS when at least one ``graphtraj:main-notice`` from the child exists and every such notice
- gives the model the shared title with its execution (``[Graftling notice from <sender> · <event> · execution <id>]``),
- has no escaped JSON or ``permissions`` in its content,
- carries display details (``sender``, ``event``, Markdown ``body`` without the title or JSON): the renderer's input.
Exit 0 = PASS.
"""
import json
import re
import sys
from pathlib import Path

TITLE = re.compile(r'^\[Graftling notice from (\S+) · (\S+) · execution (\S+)\]$')


def main(where: Path, child: str) -> int:
    files = sorted(where.rglob('*.jsonl'), key=lambda path: path.stat().st_mtime) if where.is_dir() else [where]
    if not files:
        print(f'Vr536: CANNOT (no Pi Session file under {where}; the USER part comes first)')
        return 2
    session = files[-1]
    print(f'Pi Session file: {session}')
    entries = [json.loads(line) for line in session.read_text(encoding='utf-8').splitlines() if line.strip()]
    notices = [entry for entry in entries if entry.get('type') == 'custom_message'
               and entry.get('customType') == 'graphtraj:main-notice']
    calls = [block.get('arguments', {}) for entry in entries if entry.get('type') == 'message'
             for block in (entry.get('message', {}).get('content') or []) if isinstance(block, dict)
             and block.get('type') == 'toolCall' and 'agents' in str(block.get('name'))]
    print(f'agents calls: {[call.get("feature") or call.get("action") for call in calls]}')
    ok = True
    for entry in notices:
        content = entry.get('content') if isinstance(entry.get('content'), str) else json.dumps(entry.get('content'))
        details = entry.get('details') or {}
        title = TITLE.match(content.splitlines()[0]) if content else None
        checks = {
            'model input has the title with execution id': bool(title),
            'no escaped JSON / permissions in the content': not re.search(r'\\n|\\"|"permissions"|"last_agent_message"', content),
            'display details (sender, event, body)': all(isinstance(details.get(key), str) for key in ('sender', 'event', 'body')),
            'body has no title or JSON': isinstance(details.get('body'), str) and not details['body'].startswith('[')
            and '"last_agent_message"' not in details['body'],
        }
        print(f'- notice {content.splitlines()[0][:100] if content else "(empty)"}')
        for name, passed in checks.items():
            print(f'    {"PASS" if passed else "FAIL"} {name}')
            ok &= passed
    from_child = [entry for entry in notices if child in (entry.get('content') or '')[:200]]
    print(f'notices: {len(notices)}, from {child}: {len(from_child)}')
    ok &= bool(from_child)
    print(f'Vr536: {"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), sys.argv[2]))
