"""593 X: the review exemption under the new tool name, from real records.

usage: x593.py reviewer <log>                      (graftling runs it as a local command reviewer)
       x593.py inventory <config.yml>...           (read only: reviewer names and the connections that name one)
       x593.py judge <data root> <reviewer log> <child name>

reviewer: reads graftling's review document {policy, request} from stdin, appends {at, tool, runtime} of the request
  (never its input) to <log>, and answers {"decision": "allow", "reason": ...}. It is a stand-in reviewer that allows
  everything, so the check needs no provider; it only shows WHICH calls graftling sends for review.
inventory: prints, for each graftling config.yml, the reviewer names (never their fields) and the connections whose
  settings name a reviewer. Production runs review only through such a connection (graftling config.py).
judge: the child named <child name> in <data root>/control/agents/*.json, its directory's review.jsonl and
  claude-diagnostics-*.yml, its Session archive, and the reviewer log. CHECKs:
  - review was active: the reviewer saw the create's connectivity probe under the new name (tool
    'subagents/connectivity-check', 591) and the child's Bash call;
  - exempt: neither the reviewer log nor review.jsonl holds a tool named mcp__<server>__subagents, while the child's
    archive holds a tool_use of mcp__<server>__subagents with a non-error result (it ran, without a review);
  - startup with the new name: the child's execution completed and its own mcp__<server>__subagents call ran
    (claude-diagnostics-*.yml keeps no tool list, so the registration is shown by the call itself).
"""
import json
import re
import sys
import time
from pathlib import Path

NEW = re.compile(r'^mcp__[A-Za-z0-9_-]+__subagents$')


def reviewer(log: str) -> int:
    document = json.loads(sys.stdin.read() or '{}')
    request = document.get('request') or {}
    with open(log, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': time.time(), 'tool': request.get('tool'), 'runtime': request.get('runtime')}) + '\n')
    print(json.dumps({'decision': 'allow', 'reason': '593 stand-in reviewer: allowed (records the tool name only)'}))
    return 0


def inventory(paths: list[str]) -> int:
    import yaml
    for name in paths:
        path = Path(name)
        try:
            document = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except FileNotFoundError:
            print(f'{path}: absent'); continue
        except (OSError, ValueError) as error:
            print(f'{path}: unreadable ({type(error).__name__})'); continue
        reviewers = sorted((document.get('reviewers') or {}).keys()) if isinstance(document, dict) else []
        connections = document.get('connections') or {} if isinstance(document, dict) else {}
        reviewed = sorted(f'{c} -> {v.get("review")}' for c, v in connections.items() if isinstance(v, dict) and v.get('review'))
        print(f'{path}: reviewers {reviewers or "none"} | connections naming a reviewer: {reviewed or "none"}')
    return 0


def lines(path: Path) -> list[dict]:
    out = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def judge(root: Path, log: Path, name: str) -> int:
    def check(label: str, ok: bool, detail: str = '') -> bool:
        print(f"CHECK 593 X {label}: {'PASS' if ok else 'FAIL'}{' (' + detail + ')' if detail else ''}")
        return ok

    records = [(p, json.loads(p.read_text())) for p in sorted(root.glob('control/agents/*.json'))]
    child = [(p, d) for p, d in records if d.get('name') == name]
    if not child:
        print(f'NO child named {name} under {root}/control/agents'); return 1
    path, record = max(child, key=lambda item: item[0].stat().st_mtime)
    selection, executions = record.get('selection') or {}, record.get('executions') or []
    print(f"child {name}: agent={record.get('agent')} review={selection.get('review')!r} "
          f"executions={[(e.get('id'), e.get('outcome')) for e in executions]} record={path}")
    seen = lines(log)
    tools = [str(item.get('tool')) for item in seen]
    print(f'reviewer log {log}: {len(seen)} request(s); tools {tools}')
    decisions = [d for p in root.rglob('review.jsonl') for d in lines(p)]
    print(f'review.jsonl decisions under {root}: {[(d.get("tool"), d.get("decision")) for d in decisions]}')
    diagnostics = sorted(root.rglob('claude-diagnostics-*.yml'))
    init_tools = set()
    for diag in diagnostics:
        text = diag.read_text(encoding='utf-8', errors='replace')
        init_tools |= set(re.findall(r'mcp__[A-Za-z0-9_-]+__subagents', text))
    used, results = {}, {}
    for archive in sorted(root.glob('sessions/*/session.jsonl')):
        for event in lines(archive):
            for item in walk(event):
                if item.get('type') in ('tool_use', 'tool-call') and NEW.match(str(item.get('name', ''))) and item.get('id'):
                    used[str(item['id'])] = (item['name'], archive)
                elif item.get('type') == 'tool_result' and item.get('tool_use_id'):
                    results[str(item['tool_use_id'])] = item
    ok_calls = [(n, str(a)) for i, (n, a) in used.items() if i in results and results[i].get('is_error') is not True]
    print(f'archived subagents calls: {len(used)}; with a non-error result: {len(ok_calls)} {ok_calls[:2]}')
    verdicts = [
        check('review active: the reviewer saw the create probe under the new name (subagents/connectivity-check)',
              'subagents/connectivity-check' in tools, f'{tools[:6]}'),
        check('review active: the child Bash call was sent for review', 'Bash' in tools or any(d.get('tool') == 'Bash' for d in decisions)),
        check('exempt: no subagents call reached the reviewer or review.jsonl',
              not any(NEW.match(t) for t in tools) and not any(NEW.match(str(d.get('tool'))) for d in decisions)),
        check('exempt: the child called mcp__<server>__subagents and got a non-error result (ran without review)', bool(ok_calls)),
        # claude-diagnostics-*.yml keeps only typed fields (claude/diagnostics.py), not the tool list, so the startup
        # registration shows as a completed child whose own mcp__<server>__subagents call ran.
        check('startup with the new name: the child execution completed and its mcp__<server>__subagents call ran',
              any(e.get('outcome') == 'completed' for e in executions) and bool(ok_calls),
              f'diagnostics files {len(diagnostics)}; names seen there {sorted(init_tools) or "none (not recorded)"}'),
    ]
    return 0 if all(verdicts) else 1


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'reviewer' and len(sys.argv) == 3:
        sys.exit(reviewer(sys.argv[2]))
    if mode == 'inventory':
        sys.exit(inventory(sys.argv[2:]))
    if mode == 'judge' and len(sys.argv) == 5:
        sys.exit(judge(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]))
    print(__doc__)
    sys.exit(2)
