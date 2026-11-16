"""N466r: the 466 production check on a second member's agents session_read calls (read only).

usage: nr466.py <project> <raw dir> <child session 'claude:<id>'> <task directory name>

Real result shape (seen in member Session claude:6d5623bc… seq 151-152): the archive's user/message holds a
tool_result whose content is a JSON string {action, agent, session, execution, message, result: {session, content,
total, start, stop, events: [{index, seq, type, text}], earlier, pending, omitted}}; a search result holds hits
[{index, seq, type, snippet}]. The parser walks nested dicts, lists and JSON strings until a dict with 'total' is
found; when none is found it prints a structural diagnostic (keys, types, lengths; never contents).
The member is the alias of the swarm result <raw>/N466.txt. The fake value is never printed; only counts.
"""
import json, re, sys
from pathlib import Path

import yaml

project, raw, child_session, task = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
KEYWORD = 'KW478-ORCHID'
FAKE = 'sk-probe478fake' + 'value0000'
SESS = project / '.graphtraj/swarm/sessions'
HOME = Path.home()
failed = False


def check(label, ok, detail=''):
    global failed
    verdict = ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')
    failed |= verdict != 'PASS'
    print(f"CHECK {label}: {verdict}{(' (' + detail + ')') if detail else ''}")


def bare(s: str) -> str:
    return str(s).split(':', 1)[-1]


def archive(session: str) -> Path | None:
    hits = []
    for f in SESS.glob('*/session.jsonl'):
        try:
            head = json.loads(f.open(errors='replace').readline())
        except (OSError, ValueError):
            continue
        head = head.get('header', head) if isinstance(head, dict) else {}
        if bare(head.get('id', '')) == bare(session) and not (head.get('native') or {}).get('agentId'):
            hits.append(f)
    print(f'  archive for {session}: {[str(h) for h in hits]}')
    return hits[0] if len(hits) == 1 else None


def events(path: Path | None) -> list[dict]:
    out = []
    for line in (path.read_text(errors='replace').splitlines() if path else []):
        try: out.append(json.loads(line))
        except ValueError: pass
    return out


def items(e: dict):
    data = e.get('data') if isinstance(e.get('data'), dict) else {}
    for content in (data.get('content'), (data.get('message') or {}).get('content'), (e.get('message') or {}).get('content')):
        if isinstance(content, list):
            yield from (i for i in content if isinstance(i, dict))


def find_doc(value, depth=0):
    """The first dict holding 'total', walking dicts, lists and JSON strings."""
    if depth > 8:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in '{[':
            try: return find_doc(json.loads(s), depth + 1)
            except ValueError: return None
        return None
    if isinstance(value, dict):
        if 'total' in value:
            return value
        for key in ('result', 'text', 'content'):
            if key in value:
                found = find_doc(value[key], depth + 1)
                if found is not None: return found
        for v in value.values():
            found = find_doc(v, depth + 1)
            if found is not None: return found
    if isinstance(value, list):
        for v in value:
            found = find_doc(v, depth + 1)
            if found is not None: return found
    return None


def shape(value, depth=0):
    if depth > 3: return '…'
    if isinstance(value, dict): return {k: shape(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, list): return [f'list[{len(value)}]'] + ([shape(value[0], depth + 1)] if value else [])
    if isinstance(value, str): return f'str[{len(value)}]' + (' json' if value.strip()[:1] in '{[' else '')
    return type(value).__name__


def reads(evs: list[dict]) -> list[tuple[dict, object]]:
    """(arguments, raw result content) of each agents session_read call, in order."""
    calls, out = {}, []
    for e in evs:
        for i in items(e):
            if i.get('type') in ('tool_use', 'tool-call') and str(i.get('name', '')).endswith('agents__agents'):
                arg = i.get('input', i.get('arguments', {}))
                if isinstance(arg, str):
                    try: arg = json.loads(arg)
                    except ValueError: arg = {}
                if isinstance(arg, dict) and arg.get('feature') == 'session_read':
                    calls[i.get('id')] = arg.get('arguments') or {}
            elif i.get('type') == 'tool_result' and i.get('tool_use_id') in calls:
                out.append((calls.pop(i['tool_use_id']), i.get('content')))
    return out


# --- this member: alias from N466.txt, Session from its mapping ---------------------------------------------------
swarm = (raw / 'N466.txt').read_text(errors='replace') if (raw / 'N466.txt').is_file() else ''
alias = (re.findall(r'"alias"\s*:\s*"([^"]+)"', swarm) or [''])[-1]
mapping = {}
for c in [project / '.graphtraj/core/runner/sessions' / alias / 'mapping.yml'] + sorted(
        project.glob(f'.graphtraj/core/state/tasks/{task}/teams/*/traces/{alias}/runner/session.yml')):
    if alias and c.is_file():
        d = yaml.safe_load(c.read_text()) or {}
        mapping = d if c.name == 'mapping.yml' else ((d.get('retirement') or {}).get('mapping') or {})
        break
sid = mapping.get('session'); sid = sid.get('id') if isinstance(sid, dict) else sid
print(f'466: member {alias or "NOT FOUND (no alias in N466.txt)"} session={sid}')
marc = archive(str(sid)) if sid else None
carc = archive(child_session)
mev, cev = events(marc), events(carc)
where = f'member archive {marc}' if marc else f'member archive NOT FOUND (alias {alias!r}, session {sid})'
found = reads(mev)
print(f'466: session_read calls in the member archive: {[sorted(a.items()) for a, _ in found]}')


def pick(pred, label):
    for a, content in found:
        if pred(a):
            d = find_doc(content)
            if d is None:
                print(f'  {label}: no dict with total; structure: {json.dumps(shape(content))[:600]}')
            return a, d, content
    return None, None, None


plain = lambda a: not ({'start', 'stop', 'search'} & set(a)) and a.get('content', 'text') == 'text'
_, default, _ = pick(plain, 'default')
_, page, _ = pick(lambda a: a.get('start') == -10 and a.get('stop') == -5, 'page back')
_, search, _ = pick(lambda a: a.get('search') == KEYWORD, 'keyword')
ta, tools, traw = pick(lambda a: a.get('content') == 'tools', 'tools')
aa, every, araw = pick(lambda a: a.get('content') == 'all', 'all')

for label, d, want in (('default read = last 5', default, lambda t: list(range(t))[-5:]),
                       ('page back [-10:-5]', page, lambda t: list(range(t))[-10:-5])):
    if d is None:
        check(f'466 {label}', 'BLOCKED', f'no parsed result in {where}')
        continue
    idx, total = [e.get('index') for e in d.get('events', [])], d.get('total')
    check(f'466 {label}', isinstance(total, int) and idx == want(total), f'total={total} indices={idx}')
if search is None:
    check('466 keyword search', 'BLOCKED', f'no parsed result in {where}')
else:
    hits = [(h.get('index'), h.get('seq')) for h in search.get('hits', [])]
    seqs = {e.get('seq') for e in cev if KEYWORD in json.dumps(e)}
    check('466 keyword hits are child-archive events holding the keyword', bool(hits) and bool(cev) and all(s in seqs for _, s in hits),
          f'hits (index, seq)={hits} child seqs with it={sorted(s for s in seqs if s is not None)} child archive={carc}')
# credential masking: tools/all results
fake_seqs = sorted(e.get('seq') for e in cev if FAKE in json.dumps(e))
masked_ok, details = True, []
for label, d, content in (('tools', tools, traw), ('all', every, araw)):
    text = json.dumps(content) if not isinstance(content, str) else content
    if d is None:
        masked_ok = False; details.append(f'{label}: no parsed result'); continue
    evs = d.get('events') or d.get('hits') or []
    at_fake = [e for e in evs if (e.get('seq') if 'seq' in e else (e.get('event') or {}).get('seq')) in fake_seqs]
    red_at = sum(json.dumps(e).count('[redacted]') for e in at_fake)
    details.append(f"{label}: value count {text.count(FAKE)}, '[redacted]' total {text.count('[redacted]')}, "
                   f"result events at the child's fake-value seqs {[e.get('seq') for e in at_fake]} with '[redacted]' {red_at}")
    masked_ok &= text.count(FAKE) == 0 and red_at > 0
in_member = sum(json.dumps(e).count(FAKE) for e in mev)
native = sorted((HOME / '.claude/projects').glob(f'*/{bare(str(sid))}.jsonl')) if sid else []
in_native = sum(p.read_text(errors='replace').count(FAKE) for p in native)
print(f"466: child archive seqs holding the fake value: {fake_seqs}; member archive count {in_member}; "
      f"member native transcript count {in_native} ({len(native)} file(s)); " + '; '.join(details))
if not fake_seqs:
    check('466 credential masked', 'BLOCKED', f'the child archive {carc} holds no fake value')
else:
    check('466 credential masked (tools/all results: value 0, [redacted] at its events; member archive and transcript 0)',
          masked_ok and bool(marc) and in_member == 0 and in_native == 0, 'counts above')
sys.exit(1 if failed else 0)
