"""Task 546: a real Claude Main creates a Claude child and sends to it at once; what happened to each send.

  python -I drv546.py main <project> <out> <claude> <model>     one headless Main run (stream-json, timed lines)
  python -I drv546.py ready <dir> <out> <claude> <model>        one-line READY answer with init model and login
  python -I drv546.py gate <project> <out> <claude> <model> <label>    verify-519 plugin gate (no tool use)
  python -I drv546.py probe <project> <out> <claude> <model> <label>   agents tool loaded + status call not refused
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


def flags(model: str, project: str) -> list[str]:
    """B/A/P/gate flags (as verify-519 main_run): only the project's graphtraj server, only its agents tool allowed."""
    return ['-p', '--model', model, '--output-format', 'stream-json', '--verbose',
            '--mcp-config', str(Path(project) / '.mcp.json'), '--strict-mcp-config',
            '--allowedTools', 'mcp__graphtraj__agents']


def gate_of(path: Path, label: str) -> bool:
    """verify-519's plugin gate on a stream's init record; prints one line."""
    init = next((r for _, r in records(path) if r.get('type') == 'system' and r.get('subtype') == 'init'), {})
    servers = [(s.get('name'), s.get('status')) for s in init.get('mcp_servers') or [] if isinstance(s, dict)]
    warnings = json.dumps(init.get('plugin_warnings', []))
    tools = [t for t in init.get('tools') or [] if str(t).startswith('mcp__')]
    plugins = [p.get('name') if isinstance(p, dict) else p for p in init.get('plugins') or []]
    ok = ([n for n, _ in servers] == ['graphtraj'] and 'untrusted' not in warnings
          and 'mcp__graphtraj__agents' in tools and any('graphtraj-claude-host' in str(p) for p in plugins))
    print(f"plugin gate {label}: {'PASS' if ok else 'NOT PASSED'} | init model: {init.get('model')} | "
          f"mcp_servers: {servers} | mcp tools: {tools} | plugins: {plugins} | plugin_warnings: {warnings[:300]}")
    return ok


def gate(project: str, out: str, claude: str, model: str, label: str) -> int:
    """One no-tool answer with B/A's flags; the plugin gate on its init record."""
    path = Path(out) / f'gate-{label}.jsonl'
    rc = run_timed([claude, *flags(model, project)], project, 'Reply with one line: READY-546-GATE. Use no tool.', path)
    return 0 if gate_of(path, label) and rc == 0 else 1


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


PROBE = """PROBE-546. Call the agents tool exactly once: action execute, feature status, arguments {} (no agent).
Do not call describe first. Then answer with exactly one line: PROBE-546 DONE.
"""


def probe(project: str, out: str, claude: str, model: str, label: str) -> int:
    """With B/A's exact flags: the agents tool is loaded and a status call is not refused for authority."""
    path = Path(out) / f'probe-{label}.jsonl'
    rc = run_timed([claude, *flags(model, project)], project, PROBE, path)
    gated = gate_of(path, label)
    init, results, calls = {}, [], {}
    for _, r in records(path):
        if r.get('type') == 'system' and r.get('subtype') == 'init':
            init = r
        for block in (r.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use' and 'agents' in str(block.get('name')):
                calls[block['id']] = block
            elif isinstance(block, dict) and block.get('type') == 'tool_result' and block.get('tool_use_id') in calls:
                content = block.get('content')
                text = content if isinstance(content, str) else ' '.join(
                    c.get('text', '') for c in content or [] if isinstance(c, dict))
                results.append((calls[block['tool_use_id']].get('input'), bool(block.get('is_error')), text))
    loaded = 'mcp__graphtraj__agents' in (init.get('tools') or [])
    servers = {s.get('name'): s.get('status') for s in init.get('mcp_servers') or [] if isinstance(s, dict)}
    refused = [t for _, _, t in results if 'authority' in t or 'verified caller' in t]
    ok = rc == 0 and loaded and bool(results) and not refused and not any(e for _, e, _ in results)
    first = ' / '.join(x.strip() for x in (results[0][2] if results else '').splitlines()[:3] if x.strip())
    print(f"CHECK 546 AGENTS {label}: {'PASS' if ok else 'FAIL'} | init model: {init.get('model')} | "
          f"mcp servers: {servers} | mcp__graphtraj__agents in init tools: {loaded} | "
          f"call: {results[0][0] if results else None} | error: {results[0][1] if results else None} | "
          f"result: {first[:300]!r} | exit {rc}")
    return 0 if ok and gated else 1


def main_run(project: str, out: str, claude: str, model: str) -> int:
    path = Path(out) / 'main.jsonl'
    (Path(out) / 'prompt.txt').write_text(PROMPT)
    rc = run_timed([claude, *flags(model, project)], project, PROMPT, path)
    print(f'Main exit {rc}; stream {path}')
    return summary(project, out, save_record=True)


def iso(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec='milliseconds')


def parse_at(value) -> float | None:
    """Epoch seconds from an epoch number (agent records store floats) or an ISO string."""
    if isinstance(value, bool) or value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def shown(value) -> str:
    """A record timestamp as local ISO, whatever form it was stored in."""
    t = parse_at(value)
    return iso(t) if t is not None else str(value)


def result_fields(text: str, is_error: bool | None) -> tuple[str, str, str, str | None]:
    """(error code, delivery, execution, agent) of one agents result: JSON first, `key: value` text as fallback."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get('error') if isinstance(data.get('error'), dict) else {}
        result = data.get('result') if isinstance(data.get('result'), dict) else data
        delivery = result.get('delivery')
        if isinstance(delivery, dict):
            delivery = delivery.get('delivery')
        code = str(error.get('code') or ('tool-error' if is_error else ''))
        return code, str(delivery or ''), str(result.get('execution') or data.get('execution') or ''), \
            result.get('agent') or data.get('agent')

    def value(key: str) -> str:
        return next((w.split(':', 1)[1].strip() for w in text.splitlines()
                     if w.strip().startswith(key + ':') and w.split(':', 1)[1].strip()), '')
    code = value('code') or ('tool-error' if is_error else '')
    return code, value('delivery'), value('execution'), value('agent') or None


def summary(project: str, out: str, save_record: bool = False) -> int:
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
                    code, delivery, execution, found_agent = result_fields(text, block.get('is_error'))
                    if feature == 'create' and agent is None and not code:
                        agent = found_agent
                    lines.append((t0, t, feature, code, delivery, execution, text))
    print(f"Main init model: {init.get('model')} | auth source: {init.get('apiKeySource')} | "
          f"agents tool in init tools: {any('agents' in str(x) for x in init.get('tools') or [])}")
    print(f'child agent: {agent}')
    for t0, t, feature, code, delivery, execution, text in lines:
        print(f'  {feature:6} called {iso(t0)} returned {iso(t)} | error code: {code or "-"} | '
              f'delivery: {delivery or "-"} | execution: {execution or "-"}')
        if code or 'next-execution' in text:
            print('    result text: ' + ' / '.join(x.strip() for x in text.splitlines() if x.strip())[:900])
    # The copy saved with the attempt first (S re-reads old attempts), else the live record.
    copied = Path(out) / 'agent-record.json'
    found = ([copied] if copied.is_file() else
             list(Path(project, '.graphtraj').glob(f'**/control/agents/{agent}.json')) if agent else [])
    verdict = 'NOT-HIT (no send landed in the closing window; run again)'
    if found:
        record = json.loads(found[0].read_text())
        if save_record and found[0] != copied:
            copied.write_text(json.dumps(record, indent=1))
        print(f'agent record: {found[0]}')
        for ex in record['executions']:
            ended = parse_at(ex.get('ended_at'))
            print(f"  execution {ex['id']} op={ex['operation']} started {shown(ex.get('started_at'))} ended "
                  f"{shown(ex.get('ended_at'))} outcome={ex.get('outcome')} last_message={str(ex.get('last_message'))[:40]!r}")
            for receipt in ex.get('inputs') or []:
                at = parse_at(receipt.get('at'))
                gap = (f'{ended - at:.3f}s before this execution\'s recorded end'
                       if at is not None and ended is not None else 'end unknown')
                print(f"    input {shown(receipt.get('at'))} delivery={receipt.get('delivery')} "
                      f"error={(receipt.get('error') or {}).get('code')} next={receipt.get('execution', '-')} | {gap}")
                if (receipt.get('error') or {}).get('code') == 'runtime-input-closed':
                    if receipt.get('delivery') == 'rejected':
                        verdict = 'REPRODUCED: send refused with runtime-input-closed while the execution was finishing'
                    elif receipt.get('delivery') == 'next-execution':
                        verdict = ('CLOSING WINDOW HIT, NOT REFUSED: delivered to the next execution '
                                   f"{receipt.get('execution')}")
        if verdict.startswith('NOT-HIT') and any(ex.get('operation') == 'send' for ex in record['executions']):
            verdict = 'NOT-HIT (send after the end: it started a new send execution)'
    if any(f == 'send' and c == 'runtime-input-closed' for _, _, f, c, *_ in lines) and not verdict.startswith('REPRO'):
        verdict = 'REPRODUCED: a send result carried runtime-input-closed'
    creates = [entry for entry in lines if entry[2] == 'create']
    sends = [entry for entry in lines if entry[2] == 'send']
    invalid = ('no create call' if not creates else
               f'create error {creates[0][3]}' if creates[0][3] else
               'create returned no agent' if agent is None else
               'no send call' if not sends else None)
    if invalid:
        print(f'VERDICT 546: INVALID ({invalid})')
        return 3
    print(f'VERDICT 546: {verdict}')
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['main'] and len(a) == 5:
        sys.exit(main_run(*a[1:]))
    if a[:1] == ['ready'] and len(a) == 5:
        sys.exit(ready(*a[1:]))
    if a[:1] == ['gate'] and len(a) == 6:
        sys.exit(gate(*a[1:]))
    if a[:1] == ['probe'] and len(a) == 6:
        sys.exit(probe(*a[1:]))
    if a[:1] == ['summary'] and len(a) == 3:
        sys.exit(summary(*a[1:]))
    print(__doc__)
    sys.exit(2)
