"""617 V/I/Qr helpers: subagents discover with an intent query (615's fix in graftling 0.10.1). Read only.

usage: <venv>/bin/python -I q617.py mcp <label> <project> <graphtraj-mcp command> [args...]
       <any python> -I q617.py judge <raw result file>
       <any python> -I q617.py calls <label> <after epoch> <raw result file> <transcript>...

mcp    Starts the plain MCP entry in the isolated project and sends initialize, tools/list and two subagents discover
       calls (newline-delimited JSON-RPC): query 'start an agent' and query 'list models'. CHECKs: 'start an agent'
       answers without error with features exactly [create]; 'list models' still finds models. The server is closed
       by closing its stdin, and killed only if it ignores that for 20 s (this probe's own child).
judge  Main's saved raw discover result (Q.txt): a JSON document, not an error, features exactly [create].
calls  Main's transcript after <after epoch>: an mcp__graphtraj__subagents call with action discover and query
       'start an agent' (case and spaces as Main typed them are compared lower-cased and collapsed), answered without
       error, whose result lists the same features as the raw result file. ToolSearch calls are INFO: `select:` of an
       mcp__graphtraj__ tool is Claude Code's deferred schema load and is ALLOWED (614).
"""
import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

QUERY = 'start an agent'
checks: list[bool] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    """Print one CHECK line and keep its outcome."""
    checks.append(ok)
    print(f"CHECK 617 {name}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")


def features_of(value) -> list | None:
    """The feature names of a discover document, or None when it holds none."""
    if isinstance(value, dict) and isinstance(value.get('result'), dict) and 'features' in value['result']:
        value = value['result']
    if not isinstance(value, dict) or not isinstance(value.get('features'), list):
        return None
    return [i.get('feature') if isinstance(i, dict) else i for i in value['features']]


def document(text: str):
    """The whole text as JSON, else the first JSON object in it that holds `features` or `error`."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and (features_of(value) is not None or 'error' in value):
            return value
    return None


def mcp(label: str, project: str, command: list[str]) -> None:
    process = subprocess.Popen(command, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    replies, done, last = {}, threading.Event(), 4

    def reader() -> None:
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'id' in message:
                replies[message['id']] = message
                if message['id'] == last:
                    done.set()

    def call(number: int, query: str) -> dict:
        return {'jsonrpc': '2.0', 'id': number, 'method': 'tools/call',
                'params': {'name': 'subagents', 'arguments': {'action': 'discover', 'query': query}}}

    threading.Thread(target=reader, daemon=True).start()
    for message in ({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                'clientInfo': {'name': 'probe-617', 'version': '0'}}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                    call(3, QUERY), call(4, 'list models')):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    done.wait(90)
    process.stdin.close()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()

    def answer(number: int) -> tuple[bool, list | None]:
        reply = replies.get(number) or {}
        result = reply.get('result') or {}
        found = result.get('structuredContent')
        if found is None:
            found = document(' '.join(i.get('text', '') for i in result.get('content', []) if isinstance(i, dict)))
        return 'error' in reply or bool(result.get('isError')), features_of(found)

    tools = sorted(t.get('name') for t in (replies.get(2) or {}).get('result', {}).get('tools', []))
    print(f'{label} server: {" ".join(command[:3])} | tools: {tools}')
    if not tools:
        print(f'{label} stderr tail: {process.stderr.read()[-400:]!r}')
    failed, features = answer(3)
    print(f"{label} subagents discover query {QUERY!r}: error {failed} | features {features}")
    check(f"{label} subagents discover {QUERY!r} answers exactly [create] (615)", not failed and features == ['create'],
          str(features))
    failed, features = answer(4)
    print(f"{label} subagents discover query 'list models': error {failed} | features {features}")
    check(f"{label} subagents discover 'list models' still finds models", not failed and 'models' in (features or []),
          str(features))


def judge(raw: str) -> None:
    text = Path(raw).read_text(errors='replace')
    doc = document(text)
    check('Qr the raw result is a JSON document', isinstance(doc, dict), '' if isinstance(doc, dict) else text[:120])
    doc = doc if isinstance(doc, dict) else {}
    error = doc.get('error') or doc.get('is_error') or doc.get('isError')
    features = features_of(doc)
    print(f'Q.txt features: {features}')
    check('Qr not an error', not error and features is not None, json.dumps(error)[:200] if error else '')
    check(f"Qr discover {QUERY!r} lists exactly [create] (models no longer matches; 615 in graftling 0.10.1)",
          features == ['create'], str(features))


def stamp(value) -> float | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return None


def result_text(item: dict) -> str:
    content = item.get('content')
    if isinstance(content, str):
        return content
    return ' '.join(i.get('text', '') for i in content or [] if isinstance(i, dict))


def calls(label: str, after: str, raw: str, paths: list[str]) -> None:
    split = float(after)
    want = features_of(document(Path(raw).read_text(errors='replace')) if Path(raw).is_file() else None)
    uses, results = {}, {}
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        for line in p.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            when = stamp(record.get('timestamp'))
            message = record.get('message') if isinstance(record.get('message'), dict) else {}
            content = message.get('content') or []
            for item in content if isinstance(content, list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get('type') == 'tool_use' and item.get('id'):
                    uses.setdefault(item['id'], (item.get('name'), item.get('input') or {}, when))
                elif item.get('type') == 'tool_result' and item.get('tool_use_id'):
                    results[item['tool_use_id']] = item
    window = [(i, n, inp) for i, (n, inp, w) in uses.items() if w is not None and w > split]
    print(f'[{label}] tool calls after the split ({len(window)}): {sorted({str(n) for _, n, _ in window})}')
    for _, name, inp in window:
        if name == 'ToolSearch':
            query = str(inp.get('query', ''))
            allowed = bool(re.fullmatch(r'select:mcp__graphtraj__(subagents|tasks)', query))
            print(f"INFO 617 [{label}] ToolSearch {json.dumps(inp)[:120]}: "
                  f"{'ALLOWED (Claude Code loads the deferred schema of the same mcp__graphtraj tool; 614)' if allowed else 'other query (information, not judged)'}")
    norm = lambda s: ' '.join(str(s).lower().split())
    hits = [(i, inp) for i, n, inp in window if n == 'mcp__graphtraj__subagents'
            and inp.get('action') == 'discover' and norm(inp.get('query', '')) == QUERY]
    good = []
    for ident, inp in hits:
        r = results.get(ident)
        got = features_of(document(result_text(r))) if r is not None else None
        error = r is None or r.get('is_error') is True
        print(f"[{label}] mcp__graphtraj__subagents discover {json.dumps(inp)[:120]}: "
              f"{'no result' if r is None else 'is_error ' + str(r.get('is_error') is True)} | features {got}")
        if not error and got is not None and got == want:
            good.append(ident)
    check(f"{label} Main called mcp__graphtraj__subagents discover {QUERY!r} after Q, answered without error with "
          f"the same features as Q.txt", bool(good) and want is not None,
          f'{len(hits)} call(s), {len(good)} matching; Q.txt features {want}')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'mcp' and len(sys.argv) > 4:
        mcp(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif mode == 'judge' and len(sys.argv) == 3:
        judge(sys.argv[2])
    elif mode == 'calls' and len(sys.argv) >= 5:
        calls(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    else:
        print(__doc__); sys.exit(2)
    sys.exit(0 if checks and all(checks) else 1)
