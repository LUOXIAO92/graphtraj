"""Task 576 helper for steps.zsh. Run with python3 -I; standard library only.

  init OUTJSON TIMEOUT CWD -- ARGV...   Start ARGV in CWD (environment inherited), send one stream-json user
                                        message, read stdout until the system/init event, then stop the process
                                        group. Writes {init, tools, exit, stderr_tail, elapsed} to OUTJSON.
  row LABEL OUTJSON [NAME...]           Print one diagnosis row: the raw init tools and present/absent per NAME;
                                        INCONCLUSIVE when there is no init event or its tools list is empty.
  snap ROOT                             Print the Agent ids recorded under data root ROOT (control/agents/*.json).
  accept MODE ROOT SNAP PARENTJSONL     Acceptance verdicts (MODE repro|check) for the three children the parent
                                        created through its agents tool. Needs PyYAML (run it with the venv's
                                        python -I). Observables: the create results in the parent's stream-json,
                                        the child's Agent record, its system/init `tools` as graftling recorded it
                                        (session.yml native_init) and the Bash call and result in its transcript.
"""
import json
import os
import select
import signal
import subprocess
import sys
import time


def init(out: str, timeout: float, cwd: str, argv: list[str]) -> int:
    start = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    message = {'type': 'user', 'message': {'role': 'user', 'content': 'Reply with one word: diag.'}}
    found, lines, err = None, [], b''
    try:
        proc.stdin.write((json.dumps(message) + '\n').encode())
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    buffer = b''
    streams = [proc.stdout, proc.stderr]
    while streams and found is None and time.monotonic() - start < timeout:
        ready, _, _ = select.select(streams, [], [], 0.5)
        for stream in ready:
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                streams.remove(stream)
                continue
            if stream is proc.stderr:
                err += chunk
                continue
            buffer += chunk
            while b'\n' in buffer and found is None:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    event = json.loads(line)
                except ValueError:
                    lines.append(line.decode(errors='replace')[:300])
                    continue
                if isinstance(event, dict) and event.get('type') == 'system' and event.get('subtype') == 'init':
                    found = event
                else:
                    lines.append(json.dumps(event)[:300])
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        code = proc.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        code = proc.wait()
    result = {
        'init': found is not None,
        'tools': found.get('tools') if found else None,
        'model': found.get('model') if found else None,
        'permissionMode': found.get('permissionMode') if found else None,
        'mcp_servers': found.get('mcp_servers') if found else None,
        'exit': code, 'elapsed': round(time.monotonic() - start, 1),
        'timed_out': found is None and time.monotonic() - start >= timeout,
        'other_stdout': lines[-5:], 'stderr_tail': err.decode(errors='replace')[-800:],
    }
    with open(out, 'w') as handle:
        json.dump(result, handle, indent=1)
    return 0


def row(label: str, path: str, names: list[str]) -> int:
    data = json.load(open(path))
    tools = data.get('tools')
    print(f'-- {label}')
    print(f'   init event: {"yes" if data["init"] else "NO"}; exit {data["exit"]}; {data["elapsed"]} s;'
          f' model {data.get("model")}; permissionMode {data.get("permissionMode")}')
    print(f'   raw init tools ({len(tools or [])}): {json.dumps(tools)}')
    if not data['init'] or not tools:
        print(f'   INCONCLUSIVE: {"no system/init event" if not data["init"] else "empty tools list"}')
        print(f'   stdout before: {data["other_stdout"]}')
        print(f'   stderr tail: {data["stderr_tail"]!r}')
        return 1
    for name in names:
        print(f'   {name}: {"present" if name in tools else "absent"}')
    return 0


MARKERS = ('R576-I.', 'R576-II.', 'R576-III.')
BASH_TEXT = 'r576-bash'


def snap(root: str) -> int:
    from pathlib import Path
    for path in sorted(Path(root, 'control', 'agents').glob('*.json')):
        print(path.stem)
    return 0


def parent_children(path: str) -> dict:
    """Marker -> {agent, create_result, errors} from the parent's own stream-json tool calls and results."""
    uses, results, found = {}, {}, {}
    for line in open(path, errors='replace'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get('message') if isinstance(event, dict) else None
        for block in (message or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and block.get('name', '').endswith('__agents'):
                uses[block['id']] = block.get('input') or {}
            if block.get('type') == 'tool_result':
                content = block.get('content')
                text = content if isinstance(content, str) else ''.join(
                    item.get('text', '') for item in content or [] if isinstance(item, dict))
                results[block.get('tool_use_id')] = text
    for use_id, call in uses.items():
        arguments = call.get('arguments') or {}
        if call.get('feature') != 'create':
            continue
        marker = next((m for m in MARKERS if m in str(arguments.get('instruction', ''))), None)
        if marker is None:
            continue
        text = results.get(use_id, '')
        agent = None
        try:
            agent = json.loads(text).get('agent')
        except (ValueError, AttributeError):
            pass
        found[marker] = {'agent': agent, 'arguments': arguments, 'result': text[:600]}
    return found


def child_facts(root, agent: str) -> dict:
    """The child's Agent record, recorded system/init and transcript facts."""
    import yaml
    from pathlib import Path
    facts = {'record': None, 'session_yml': None, 'tools': None, 'transcript': None,
             'bash_calls': [], 'bash_output_seen': False, 'reply': None}
    record_path = Path(root, 'control', 'agents', f'{agent}.json')
    if record_path.exists():
        record = json.loads(record_path.read_text())
        facts['record'] = str(record_path)
        last = (record.get('executions') or [{}])[-1]
        facts['state'] = last.get('state')
        facts['outcome'] = (record.get('last_result') or {}).get('outcome') or last.get('outcome')
        session = record.get('session')
    else:
        session = None
    for path in Path(root).rglob('session.yml'):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        if agent in str(path) or (session and data.get('session') == session):
            facts['session_yml'] = str(path)
            init = data.get('native_init') or {}
            facts['tools'] = init.get('tools') if isinstance(init, dict) else None
            facts['init_model'] = init.get('model') if isinstance(init, dict) else None
            facts['transcript'] = data.get('rollout_path')
    if facts['transcript'] and Path(facts['transcript']).exists():
        bash_ids = set()
        for line in open(facts['transcript'], errors='replace'):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get('message') if isinstance(event, dict) else None
            content = (message or {}).get('content')
            if isinstance(content, str):
                if (message or {}).get('role') == 'assistant':
                    facts['reply'] = content[:300]
                continue
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                    bash_ids.add(block.get('id'))
                    facts['bash_calls'].append(str((block.get('input') or {}).get('command'))[:200])
                if block.get('type') == 'tool_result' and block.get('tool_use_id') in bash_ids:
                    body = block.get('content')
                    text = body if isinstance(body, str) else json.dumps(body)
                    facts['bash_result'] = text[:300]
                    facts['bash_output_seen'] = facts['bash_output_seen'] or BASH_TEXT in text
                if block.get('type') == 'text' and (message or {}).get('role') == 'assistant':
                    facts['reply'] = block.get('text', '')[:300]
    return facts


def accept(mode: str, root: str, snapshot: str, parent: str) -> int:
    before = set(open(snapshot).read().split())
    children = parent_children(parent)
    failed = 0
    print(f'parent stream-json: {parent}')
    for marker, label in zip(MARKERS, ('(i) no tools', '(ii) tools [Read]', '(iii) disallowed_tools [Bash]')):
        child = children.get(marker)
        print(f'-- child {label} [{marker}]')
        if not child or not child['agent']:
            print(f'   FAIL: {label}: no create result with an agent id in the parent output'
                  f' ({child["result"] if child else "no create call"})')
            failed += 1
            continue
        agent = child['agent']
        facts = child_facts(root, agent)
        print(f'   create arguments: {json.dumps(child["arguments"])}')
        print(f'   agent {agent} (new in this run: {agent not in before}); record {facts["record"]};'
              f' state {facts.get("state")}; outcome {facts.get("outcome")}')
        print(f'   recorded system/init ({facts["session_yml"]}): model {facts.get("init_model")};'
              f' tools {json.dumps(facts["tools"])}')
        print(f'   transcript {facts["transcript"]}: Bash calls {facts["bash_calls"]};'
              f' Bash result {facts.get("bash_result")!r}; last reply {facts["reply"]!r}')
        tools = facts['tools']
        if agent in before:
            print(f'   FAIL: {label}: {agent} existed before this run')
            failed += 1
            continue
        if not tools:
            print(f'   FAIL: {label}: no recorded system/init tools for {agent}')
            failed += 1
            continue
        has_bash = 'Bash' in tools
        if marker == 'R576-I.':
            if mode == 'repro':
                if has_bash:
                    print('   PREMISE NOT REPRODUCED: on the base the child without tools HAS Bash in its init tools'
                          f'; Bash output seen: {facts["bash_output_seen"]}')
                    failed += 1
                else:
                    print('   PASS (premise reproduced): the child without tools has no Bash in its system/init tools'
                          f'; Bash calls in its transcript: {len(facts["bash_calls"])}')
            else:
                ok = has_bash and facts['bash_output_seen']
                print(f'   {"PASS" if ok else "FAIL"}: {label}: Bash in system/init tools: {has_bash}; a Bash call'
                      f' returned exactly-containing {BASH_TEXT!r}: {facts["bash_output_seen"]};'
                      f' state {facts.get("state")}, outcome {facts.get("outcome")}')
                failed += not ok
        else:
            ok = not has_bash and (marker != 'R576-II.' or 'Read' in tools)
            print(f'   {"PASS" if ok else "FAIL"}: {label}: Bash absent from system/init tools: {not has_bash}'
                  + ('; Read present: ' + str('Read' in tools) if marker == 'R576-II.' else ''))
            failed += not ok
    return 1 if failed else 0


if __name__ == '__main__':
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'init':
        split = args.index('--')
        sys.exit(init(args[0], float(args[1]), args[2], args[split + 1:]))
    if command == 'row':
        sys.exit(row(args[0], args[1], args[2:]))
    if command == 'snap':
        sys.exit(snap(args[0]))
    if command == 'accept':
        sys.exit(accept(*args[:4]))
    sys.exit(f'unknown command {command}')
