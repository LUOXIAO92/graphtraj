"""Task 570 verdicts, computed from a Session's output and the agent records on disk (never from canned text).

usage:
  judge.py snap <root>                                      agent ids recorded under <root>, one per line
  judge.py owned <root> <host>                              the ids of those created by <host>
  judge.py tools <output> present|absent                    the agents tool in a Session's TOOLS/RESULT lines
  judge.py create <output> <root> <before> <host> <word>    association + child outcome (exit 0 when both pass)
  judge.py pair <output> <root> <before> <host> <word>      association, child outcome and visibility, each
                                                            labelled; exit code bits: 1 association, 2 child
                                                            outcome, 4 visibility failed
  judge.py listed <output> <root> <host>                    visibility: the LISTED ids are all <host>'s
  judge.py archives <root> <before> <agent>...              archives under <root>/sessions (PUBLIC_API 1.5): sha256
                                                            directory = sha256(header id); one per Session; the
                                                            given agents' native Sessions among them
Prints PASS/FAIL lines.
"""
import hashlib, json, re, sys
from pathlib import Path

ID = re.compile(r'agent-[0-9a-f]{32}')
DENIED = 'authority-denied'
ERRORS = ('invalid-input', 'unsupported-runtime', 'invalid-config')


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
    """The last line starting with ``prefix``: DSH prints the model's reasoning first, the answer last."""
    found = [item.strip()[len(prefix):].strip() for item in text.splitlines() if item.strip().startswith(prefix)]
    return found[-1] if found else None


def tool_errors(text):
    """Error codes in the output, and answer lines starting with ERROR: (the prompt's own word is not one)."""
    return [word for word in ERRORS if word in text] + (['ERROR: line'] if line(text, 'ERROR:') is not None else [])


def check(ok, message, results, group=''):
    print(('PASS: ' if ok else 'FAIL: ') + (f'{group}: ' if group else '') + message)
    results.append(ok)
    return ok


def association(text, root, before, host):
    """One new record by ``host`` and no authority-denied: the call reached the host as this Main."""
    results = []
    new = {agent: record for agent, record in records(root).items() if agent not in before}
    mine = {agent: record for agent, record in new.items() if (record.get('creator') or {}).get('host') == host}
    check(DENIED not in text, 'no authority-denied in the output', results, 'association')
    check(len(mine) == 1 and len(new) == 1, f'one new record under {root}, by {host}: '
          f'{ {a: (r.get("creator") or {}).get("host") for a, r in new.items()} }', results, 'association')
    return all(results), mine


def outcome(text, mine, word):
    results = []
    for agent, record in mine.items():
        last = (record.get('executions') or [{}])[-1]
        check(last.get('outcome') == 'completed' and word in (last.get('last_message') or '').lower(),
              f'{agent} completed with {word!r}: outcome {last.get("outcome")}, error '
              f'{(last.get("error") or {}).get("code")}, last_message {(last.get("last_message") or "")[:80]!r}',
              results, 'child outcome')
        check(agent in text and word in text.lower(), f'the reply names {agent} and {word!r}', results, 'child outcome')
    if not mine:
        check(False, 'no child to judge (association failed)', results, 'child outcome')
    errors = tool_errors(text)
    check(not errors, f'no tool error in the output (found: {errors})', results, 'child outcome')
    return all(results)


def visibility(text, root, host):
    results, found = [], records(root)
    ids = ID.findall(line(text, 'LISTED:') or '')
    owners = {agent: (found.get(agent, {}).get('creator') or {}).get('host', 'not in this root') for agent in ids}
    check(bool(ids) and all(owner == host for owner in owners.values()), f'LISTED ids all {host}\'s: {owners}',
          results, 'visibility')
    return all(results)


def archives(root, before, agents):
    results, found = [], records(root)
    sessions, natives = {}, {}
    for path in sorted((Path(root) / 'sessions').glob('*/session.jsonl')):
        try:
            header = json.loads(path.read_text().splitlines()[0])['header']
        except (OSError, ValueError, IndexError, KeyError) as error:
            check(False, f'{path}: unreadable header ({error})', results, 'archives')
            continue
        identity, native = header.get('id'), header.get('native') or {}
        digest = path.parent.name
        new = '' if digest in before else ' (new)'
        print(f'  archive {digest}{new}: id {identity!r}, native runtime {native.get("runtime")!r}, '
              f'sessionId {native.get("sessionId")!r}')
        check(isinstance(identity, str) and hashlib.sha256(identity.encode()).hexdigest() == digest,
              f'{digest[:12]}... is sha256 of its Session id {identity!r}', results, 'archives')
        sessions.setdefault(identity, []).append(digest)
        natives[identity] = native.get('sessionId')
    check(bool(sessions) and all(len(v) == 1 for v in sessions.values()),
          f'{len(sessions)} archive(s), one directory per Session id', results, 'archives')
    for agent in agents:
        record = found.get(agent) or {}
        session = record.get('session')
        hit = [i for i in sessions if session and (natives.get(i) == session
                                                   or (isinstance(i, str) and i.endswith(':' + session)))]
        check(bool(hit), f'{agent} ({record.get("runtime")}, native Session {session!r}) is archived: {hit}',
              results, 'archives')
    return all(results)


def main(argv):
    mode, results = argv[0], []
    if mode == 'snap':
        print('\n'.join(records(argv[1])))
        return 0
    if mode == 'owned':
        print('\n'.join(agent for agent, record in records(argv[1]).items()
                        if (record.get('creator') or {}).get('host') == argv[2]))
        return 0
    if mode == 'archives':
        return 0 if archives(argv[1], set(Path(argv[2]).read_text().split()), argv[3:]) else 1
    text = Path(argv[1]).read_text(errors='replace')
    if mode == 'tools':
        errors = tool_errors(text) + ([DENIED] if DENIED in text else [])
        tools = line(text, 'TOOLS:') or ''
        if argv[2] == 'present':
            check('mcp__graftling__agents' in tools, f'TOOLS line names mcp__graftling__agents: {tools[:160]!r}', results)
            check(line(text, 'RESULT:') is not None, 'a RESULT: line holds the status call result', results)
            check(not errors, f'no tool error in the output (found: {errors})', results)
        else:
            check('NO AGENTS TOOL' in text and 'mcp__graftling__agents' not in tools,
                  f'no agents tool: TOOLS line {tools[:160]!r}, NO AGENTS TOOL present: {"NO AGENTS TOOL" in text}', results)
        return 0 if results and all(results) else 1
    if mode in ('create', 'pair'):
        root, before, host, word = argv[2], set(Path(argv[3]).read_text().split()), argv[4], argv[5]
        linked, mine = association(text, root, before, host)
        done = outcome(text, mine, word)
        if mode == 'create':
            return 0 if linked and done else 1
        seen = visibility(text, root, host)
        return (0 if linked else 1) | (0 if done else 2) | (0 if seen else 4)
    if mode == 'listed':
        return 0 if visibility(text, argv[2], argv[3]) else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
