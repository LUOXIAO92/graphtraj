"""Task 533: read the isolated Main's Claude transcript after the user's real-host run; print PASS/FAIL observables.

usage: vr533.py <transcript.jsonl> [<child name>]

A pushed notice is a user record whose text holds `[Graftling notice from …]` (graftling.notice_text). The checks:
the notice names sender and event, carries a `Facts:` line with the execution, holds no `permissions` / escaped
JSON, and its content keeps real Markdown lines. The transcript cannot show placed rows (Claude never sees them):
the user's screenshots are the evidence for how they look. Prints each notice's record keys and `origin`-like
fields, so the UserMessage origin shape of a plugin prompt is on record.
"""
import json
import re
import sys

TITLE = re.compile(r'^\[Graftling notice from (.+?) · ([^\]]+?)(?: · execution ([^\]\s]+))?\]$', re.M)


def texts(content):
    if isinstance(content, str):
        return [content]
    return [b.get('text', '') for b in content or [] if isinstance(b, dict) and b.get('type') == 'text']


def main(path, child=None):
    notices, calls = [], []
    for line in open(path, errors='replace'):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get('message') if isinstance(record, dict) else None
        if not isinstance(message, dict):
            continue
        if record.get('type') == 'user':
            for text in texts(message.get('content')):
                if TITLE.search(text):
                    notices.append((record, text))
        if record.get('type') == 'assistant':
            for block in message.get('content') or []:
                if isinstance(block, dict) and block.get('type') == 'tool_use' and 'agents' in str(block.get('name')):
                    data = block.get('input') or {}
                    calls.append(data.get('feature') or data.get('action'))
    print(f'agents calls by Main: {calls}')
    print(f'notice prompts: {len(notices)}')
    results = []

    def check(name, ok):
        results.append(ok)
        print(f'{"PASS" if ok else "FAIL"} {name}')

    for record, text in notices:
        keys = sorted(record)
        hints = {k: record[k] for k in keys if any(w in k.lower() for w in ('origin', 'plugin', 'source', 'meta'))}
        print(f'--- notice record keys: {keys}; origin-like fields: {json.dumps(hints, ensure_ascii=False)[:300]}')
        for title in TITLE.finditer(text):
            print(f'title: sender={title[1]} event={title[2]} execution={title[3]}')
        print('text (first 12 lines):')
        print('\n'.join('  | ' + l for l in text.splitlines()[:12]))
    check('CHECK 533 Main created a child and sent it a message (agents create and send)',
          'create' in calls and 'send' in calls)
    check('CHECK 533 at least one notice was pushed into Main', bool(notices))
    allt = '\n'.join(t for _, t in notices)
    titles = list(TITLE.finditer(allt))
    check('CHECK 533 each notice names sender and event', bool(titles) and all(t[1] and t[2] for t in titles))
    if child:  # information: a Task-free Main's notice may name the agent id rather than the name
        print(f'INFO notice senders: {sorted({t[1] for t in titles})}; child name {child!r} among them: '
              f'{"yes" if any(child in t[1] for t in titles) else "no"}')
    check('CHECK 533 a completed notice names its execution (title or Facts line)',
          any(t[2] == 'completed' and (t[3] or re.search(r'^Facts: .*execution_id `', allt, re.M)) for t in titles))
    check("CHECK 533 no 'permissions' / 'terminal_confirmed' / 'session_id' in notice text",
          bool(notices) and not re.search(r'permissions|terminal_confirmed|session_id', allt))
    check('CHECK 533 no escaped JSON (\\n, \\") in notice text', bool(notices) and '\\n' not in allt and '\\"' not in allt)
    check('CHECK 533 notice content keeps Markdown lines (heading, list or quote at a line start)',
          bool(re.search(r'^(#{1,6} |[-*] |\d+\. |> )', allt, re.M)))
    ok = bool(results) and all(results)
    print(f'Vr533: {"PASS" if ok else "FAIL"} ({sum(results)}/{len(results)})')
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
