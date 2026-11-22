"""Task 574 verdicts, computed from a real Claude Code Main's stream-json output and the agent records on disk.

usage:
  judge.py snap <root>                               agent ids recorded under <root>, one per line
  judge.py catalog <claude> <cwd>                    Claude's own initialize model catalog: every field of every model
                                                     entry (model metadata only), and the names (not values) of the
                                                     other response keys
  judge.py calls <stream>                            each mcp__graftling__agents call of the Main and its real result
  judge.py case <stream> <root> <before> <expect> <model> <word>
      expect old-alias   the base's failure: create accepted, the child failed RUNTIME_REQUEST_FAILED with
                         'requested model <model>, observed model claude-...'
      expect refused     refused before start: no new record, the create result is invalid-model
                         (old-full: plus 'is not a candidate of the native claude login')
      expect old-full    as refused, with the base's wording
      expect completed   the child completed with <word>; its record keeps model <model>; for an alias the record
                         and the status result show the resolved full model (claude-<alias>-...)
Prints PASS/FAIL lines; exit 0 only when every check passed. Nothing here echoes expected text: each verdict reads
the records under <root> and the tool results the Main actually received.
"""
import json, subprocess, sys
from pathlib import Path

TOOL = 'mcp__graftling__agents'


def records(root):
    found = {}
    for path in sorted((Path(root) / 'control' / 'agents').glob('*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        found[record.get('agent', path.stem)] = record
    return found


def text_of(content):
    if isinstance(content, str):
        return content
    return '\n'.join(block.get('text', '') if isinstance(block, dict) else str(block) for block in content or [])


def calls(stream):
    """[(feature, arguments, result text, is_error)] for each agents call, in order, from the native stream."""
    uses, results = [], {}
    for raw in Path(stream).read_text(errors='replace').splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        for block in (event.get('message') or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and block.get('name') == TOOL:
                uses.append(block)
            elif block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = (text_of(block.get('content')), bool(block.get('is_error')))
    found = []
    for use in uses:
        given = use.get('input') or {}
        text, error = results.get(use.get('id'), ('<no result>', True))
        found.append((given.get('feature'), given.get('arguments') or {}, text, error))
    return found


def check(ok, message, results):
    print(('PASS: ' if ok else 'FAIL: ') + message)
    results.append(bool(ok))


def catalog(claude, cwd):
    command = [claude, '--print', '--verbose', '--input-format', 'stream-json', '--output-format', 'stream-json',
               '--restricted', '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    query = {'type': 'control_request', 'request_id': 'catalog', 'request': {'subtype': 'initialize'}}
    done = subprocess.run(command, input=json.dumps(query) + '\n', text=True, capture_output=True, timeout=120, cwd=cwd)
    for raw in done.stdout.splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        reply = event.get('response') or {}
        if event.get('type') == 'control_response' and reply.get('request_id') == 'catalog':
            body = reply.get('response') or {}
            print('initialize subtype:', reply.get('subtype'))
            print('initialize response keys (names only):', sorted(body))
            for item in body.get('models') or []:
                print('  model entry:', json.dumps(item, sort_keys=True))
            return 0
    print('FAIL: no initialize response; exit', done.returncode, 'stderr:', done.stderr[-400:])
    return 1


def case(stream, root, before, expect, model, word):
    results = []
    made = calls(stream)
    for feature, arguments, text, error in made:
        print(f'  call {feature} {json.dumps(arguments)[:200]} -> is_error={error}: {text[:600]!r}')
    creates = [item for item in made if item[0] == 'create']
    check(len(creates) == 1 and creates[0][1].get('model') == model,
          f'the Main called create once with model {model!r} (calls: {[c[0] for c in made]})', results)
    created = creates[0][2] if creates else ''
    new = {agent: record for agent, record in records(root).items() if agent not in before}
    for agent, record in new.items():
        last = (record.get('executions') or [{}])[-1]
        shown = {key: record.get(key) for key in ('runtime', 'model', 'resolved_model', 'creator') if key in record}
        print(f'  record {agent}: {json.dumps(shown)}; last execution: outcome {last.get("outcome")}, state '
              f'{last.get("state")}, error {json.dumps(last.get("error"))[:400]}, '
              f'last_message {(last.get("last_message") or "")[:80]!r}')
    if expect in ('refused', 'old-full'):
        check(not new, f'no new agent record under {root} (found {sorted(new)})', results)
        check('invalid-model' in created, 'the create result is invalid-model', results)
        if expect == 'old-full':
            check('is not a candidate of the native claude login' in created,
                  "the create result says 'is not a candidate of the native claude login'", results)
        return results
    claude = {agent: record for agent, record in new.items() if record.get('runtime') == 'claude'}
    check(len(new) == 1 and len(claude) == 1, f'one new claude agent record under {root}: {sorted(new)}', results)
    check('invalid-model' not in created and claude and next(iter(claude)) in created,
          'create accepted (its result names the new agent, no invalid-model)', results)
    if not claude:
        return results
    agent, record = next(iter(claude.items()))
    last = (record.get('executions') or [{}])[-1]
    error = json.dumps(last.get('error') or {})
    if expect == 'old-alias':
        check(last.get('outcome') != 'completed' and 'RUNTIME_REQUEST_FAILED' in error,
              f'the child failed RUNTIME_REQUEST_FAILED (outcome {last.get("outcome")})', results)
        check(f'Claude selected a different Session or model: requested model {model}, observed model claude-' in error,
              f"the error says 'requested model {model}, observed model claude-...'", results)
        return results
    check(last.get('outcome') == 'completed' and word in (last.get('last_message') or '').lower(),
          f'{agent} completed with {word!r}: outcome {last.get("outcome")}, error {error[:200]}', results)
    check(record.get('model') == model, f'the record keeps the requested model: model {record.get("model")!r}', results)
    resolved = record.get('resolved_model')
    status = ' '.join(text for feature, arguments, text, _ in made if feature == 'status' and arguments.get('agent'))
    if model.startswith('claude-'):
        check(resolved in (None, model), f'a full id resolves to itself: resolved_model {resolved!r}', results)
    else:
        check(isinstance(resolved, str) and resolved.startswith(f'claude-{model}-'),
              f'the record shows the resolved model of alias {model!r}: resolved_model {resolved!r}', results)
        check(bool(resolved) and resolved in status, f'the status result the Main received shows {resolved!r}', results)
    return results


def main(argv):
    mode = argv[0]
    if mode == 'snap':
        print('\n'.join(records(argv[1])))
        return 0
    if mode == 'catalog':
        return catalog(argv[1], argv[2])
    if mode == 'calls':
        for feature, arguments, text, error in calls(argv[1]):
            print(f'{feature} {json.dumps(arguments)} -> is_error={error}: {text[:800]}')
        return 0
    if mode == 'case':
        stream, root, before, expect, model, word = argv[1:7]
        results = case(stream, root, set(Path(before).read_text().split()), expect, model, word)
        return 0 if results and all(results) else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
