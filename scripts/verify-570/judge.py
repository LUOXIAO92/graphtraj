"""Task 570 verdicts, computed from a Session's output and the agent records on disk (never from canned text).

usage:
  judge.py snap <root>                                      agent ids recorded under <root>, one per line
  judge.py owned <root> <host>                              the ids of those created by <host>
  judge.py tools <output> present|absent                    the agents tool in a Session's TOOLS/RESULT lines
  judge.py create <output> <root> <before> <host> <word>    one new record by <host>, completed with <word>
  judge.py listed <output> <root> <host>                    the ids on the LISTED line are all <host>'s, in <root>
Prints PASS/FAIL lines; exit 0 only when every check passes. A tool error in the output always fails.
"""
import json, re, sys
from pathlib import Path

ID = re.compile(r'agent-[0-9a-f]{32}')
ERRORS = ('invalid-input', 'ERROR:', 'authority-denied', 'unsupported-runtime', 'invalid-config')


def records(root):
    found = {}
    for path in sorted((Path(root) / 'control' / 'agents').glob('*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        found[record.get('agent', path.stem)] = record
    return found


def line(text, prefix):
    return next((item[len(prefix):].strip() for item in text.splitlines() if item.strip().startswith(prefix)), None)


def check(ok, message, results):
    print(('PASS: ' if ok else 'FAIL: ') + message)
    results.append(ok)


def main(argv):
    mode, results = argv[0], []
    if mode == 'snap':
        print('\n'.join(records(argv[1])))
        return 0
    if mode == 'owned':
        print('\n'.join(agent for agent, record in records(argv[1]).items()
                        if (record.get('creator') or {}).get('host') == argv[2]))
        return 0
    text = Path(argv[1]).read_text(errors='replace')
    errors = [word for word in ERRORS if word in text]
    if mode == 'tools':
        tools = line(text, 'TOOLS:') or ''
        if argv[2] == 'present':
            check('mcp__graftling__agents' in tools, f'TOOLS line names mcp__graftling__agents: {tools[:160]!r}', results)
            check(line(text, 'RESULT:') is not None, 'a RESULT: line holds the status call result', results)
            check(not errors, f'no tool error in the output (found: {errors})', results)
        else:
            check('NO AGENTS TOOL' in text and 'mcp__graftling__agents' not in tools,
                  f'no agents tool: TOOLS line {tools[:160]!r}, NO AGENTS TOOL present: {"NO AGENTS TOOL" in text}', results)
    elif mode == 'create':
        root, before, host, word = argv[2], set(Path(argv[3]).read_text().split()), argv[4], argv[5]
        new = {agent: record for agent, record in records(root).items() if agent not in before}
        check(len(new) == 1, f'one new agent record under {root}: {sorted(new)}', results)
        for agent, record in new.items():
            last = (record.get('executions') or [{}])[-1]
            check((record.get('creator') or {}).get('host') == host, f'{agent} created by {host}: {record.get("creator")}', results)
            check(last.get('outcome') == 'completed' and word in (last.get('last_message') or '').lower(),
                  f'{agent} completed with {word!r}: outcome {last.get("outcome")}, '
                  f'last_message {(last.get("last_message") or "")[:80]!r}', results)
            check(agent in text and word in text.lower(), f'the reply names {agent} and {word!r}', results)
        check(not errors, f'no tool error in the output (found: {errors})', results)
    elif mode == 'listed':
        root, host = records(argv[2]), argv[3]
        ids = ID.findall(line(text, 'LISTED:') or '')
        owners = {agent: (root.get(agent, {}).get('creator') or {}).get('host', 'not in this root') for agent in ids}
        check(bool(ids) and all(owner == host for owner in owners.values()), f'LISTED ids all {host}\'s: {owners}', results)
        check(not errors, f'no tool error in the output (found: {errors})', results)
    else:
        print(__doc__)
        return 2
    return 0 if results and all(results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
