"""Task 546: a real Claude Main creates a Claude child and sends to it at once; what happened to each send.

  python -I drv546.py main <project> <out> <claude> <model>     one headless Main run (stream-json, timed lines)
  python -I drv546.py ready <dir> <out> <claude> <model>        one-line READY answer with init model and login
  python -I drv546.py summary <project> <out>                   the observable from <out>/main.jsonl + agent record
Standard library only. The agent record is the product's own (<project>/.graphtraj/**/control/agents/<id>.json).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROMPT = """You are checking the agents tool. Do exactly these steps, nothing else.
0. Call the agents tool with action describe for feature create, then for feature send (schema true), to learn the
   argument names. Do not call execute yet while learning.
1. Call agents execute create: runtime claude, name probe546, instruction "Reply with exactly the word: first".
2. As soon as create returns, with no other call and no text in between, call agents execute send to that agent
   with message "Reply with exactly the word: second".
3. If that send's result is not an error and its delivery is "submitted", call send again at once with message
   "Reply with exactly the word: again". Send at most 5 times in total; stop after the first send whose result is
   an error or whose delivery is not "submitted".
4. Call agents execute wait for that agent with timeout_seconds 120.
5. Answer with one line per send: SEND <n>: <its delivery value or its error code, verbatim>.
"""


def flags(model: str) -> list[str]:
    return ['-p', '--model', model, '--output-format', 'stream-json', '--verbose',
            '--setting-sources', 'project,local', '--allowedTools', 'mcp__graphtraj__agents']


def run_timed(argv: list[str], cwd: str, stdin: str, out: Path) -> int:
    """Run and save every stdout line with its arrival time (epoch seconds)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.with_suffix('.argv.json')).write_text(json.dumps({'cwd': cwd, 'argv': argv}, indent=1))
    with open(out, 'w') as sink, open(out.with_suffix('.err'), 'w') as err:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True)
        proc.stdin.write(stdin)
        proc.stdin.close()
        for line in proc.stdout:
            sink.write(json.dumps({'t': time.time(), 'line': line.rstrip('\n')}) + '\n')
            sink.flush()
        return proc.wait(timeout=900)


def records(path: Path):
    for row in path.read_text().splitlines():
        row = json.loads(row)
        try:
            yield row['t'], json.loads(row['line'])
        except ValueError:
            continue


def ready(cwd: str, out: str, claude: str, model: str) -> int:
    path = Path(out) / 'ready.jsonl'
    rc = run_timed([claude, '-p', '--model', model, '--output-format', 'stream-json', '--verbose'], cwd,
                   'Answer with exactly one line: READY-546-CLAUDE', path)
    init = next((r for _, r in records(path) if r.get('type') == 'system' and r.get('subtype') == 'init'), {})
    result = next((r for _, r in records(path) if r.get('type') == 'result'), {})
    answer = str(result.get('result', '')).strip()
    ok = rc == 0 and 'READY-546-CLAUDE' in answer and init.get('model', '').startswith(model)
    print(f"CHECK 546 READY-546-CLAUDE: {'PASS' if ok else 'FAIL'} | init model: {init.get('model')} | "
          f"auth source (init apiKeySource): {init.get('apiKeySource')} | answer: {answer[:80]!r} | exit {rc}")
    return 0 if ok else 1


def main_run(project: str, out: str, claude: str, model: str) -> int:
    path = Path(out) / 'main.jsonl'
    (Path(out) / 'prompt.txt').write_text(PROMPT)
    rc = run_timed([claude, *flags(model)], project, PROMPT, path)
    print(f'Main exit {rc}; stream {path}')
    return summary(project, out)


def iso(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec='milliseconds')


def parse_at(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def summary(project: str, out: str) -> int:
    path = Path(out) / 'main.jsonl'
    calls, agent = {}, None
    init = {}
    lines = []
    for t, r in records(path):
        if r.get('type') == 'system' and r.get('subtype') == 'init':
            init = r
        for block in (r.get('message') or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and 'agents' in str(block.get('name')):
                args = block.get('input') or {}
                calls[block['id']] = (t, args)
            elif block.get('type') == 'tool_result' and block.get('tool_use_id') in calls:
                t0, args = calls[block['tool_use_id']]
                content = block.get('content')
                text = content if isinstance(content, str) else ' '.join(
                    c.get('text', '') for c in content or [] if isinstance(c, dict))
                feature = args.get('feature')
                if args.get('action') == 'execute' and feature in ('create', 'send', 'wait'):
                    code = next((w.split(':', 1)[1].strip() for w in text.splitlines() if w.strip().startswith('code:')), '')
                    delivery = next((w.split(':', 1)[1].strip() for w in text.splitlines()
                                     if w.strip().startswith('delivery:') and w.split(':', 1)[1].strip()), '')
                    execution = next((w.split(':', 1)[1].strip() for w in text.splitlines()
                                      if w.strip().startswith('execution:')), '')
                    if feature == 'create' and agent is None:
                        agent = next((w.split(':', 1)[1].strip() for w in text.splitlines()
                                      if w.strip().startswith('agent:')), None)
                    lines.append((t0, t, feature, code, delivery, execution, text))
    print(f"Main init model: {init.get('model')} | auth source: {init.get('apiKeySource')} | "
          f"agents tool in init tools: {any('agents' in str(x) for x in init.get('tools') or [])}")
    print(f'child agent: {agent}')
    for t0, t, feature, code, delivery, execution, text in lines:
        print(f'  {feature:6} called {iso(t0)} returned {iso(t)} | error code: {code or "-"} | '
              f'delivery: {delivery or "-"} | execution: {execution or "-"}')
        if code or 'next-execution' in text:
            print('    result text: ' + ' / '.join(x.strip() for x in text.splitlines() if x.strip())[:900])
    found = list(Path(project, '.graphtraj').glob(f'**/control/agents/{agent}.json')) if agent else []
    verdict = 'NOT-HIT (no send landed in the closing window; run again)'
    if found:
        record = json.loads(found[0].read_text())
        (Path(out) / 'agent-record.json').write_text(json.dumps(record, indent=1))
        print(f'agent record: {found[0]}')
        for ex in record['executions']:
            ended = parse_at(ex.get('ended_at'))
            print(f"  execution {ex['id']} op={ex['operation']} started {ex.get('started_at')} ended "
                  f"{ex.get('ended_at')} outcome={ex.get('outcome')} last_message={str(ex.get('last_message'))[:40]!r}")
            for receipt in ex.get('inputs') or []:
                at = parse_at(receipt.get('at'))
                gap = f'{ended - at:.3f}s before this execution\'s recorded end' if at and ended else 'end unknown'
                print(f"    input {receipt.get('at')} delivery={receipt.get('delivery')} "
                      f"error={(receipt.get('error') or {}).get('code')} next={receipt.get('execution', '-')} | {gap}")
                if (receipt.get('error') or {}).get('code') == 'runtime-input-closed':
                    if receipt.get('delivery') == 'rejected':
                        verdict = 'REPRODUCED: send refused with runtime-input-closed while the execution was finishing'
                    elif receipt.get('delivery') == 'next-execution':
                        verdict = ('CLOSING WINDOW HIT, NOT REFUSED: delivered to the next execution '
                                   f"{receipt.get('execution')}")
    print(f'VERDICT 546: {verdict}')
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['main'] and len(a) == 5:
        sys.exit(main_run(*a[1:]))
    if a[:1] == ['ready'] and len(a) == 5:
        sys.exit(ready(*a[1:]))
    if a[:1] == ['summary'] and len(a) == 3:
        sys.exit(summary(*a[1:]))
    print(__doc__)
    sys.exit(2)
