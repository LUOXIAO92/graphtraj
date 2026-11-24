"""Task 613 step helper: read the Main's subagents calls, rehearse them, and judge them.

main OUT.jsonl CALLS.json
    From a `claude -p --output-format stream-json` run, write every mcp__graftling__subagents
    call as {"feature", "arguments", "document", "failed"} (the tool result's JSON document),
    and print the Main's init model, apiKeySource and final result line.
rehearse DATAROOT PROJECT CHILD STEP CALLS.json     (rehearsal only, never acceptance)
    With the graftling this interpreter imports, do what the Claude Code host does for the
    same calls: start-time require_connections (a refusal answers every call with its code),
    then the bound subagents function; the child executable is the stub CHILD.
check CALLS.json STEP DATAROOT
    The step's CHECK lines from the calls and the data root's agent records.
"""
import json
import os
import re
from pathlib import Path
import sys

TOOL = 'mcp__graftling__subagents'
REFUSAL = 'base_url needs api_key_env'
# A plugin hook's denial is plain text: '... association failed: <code>: <message>'.
DENIAL = re.compile(r'failed: ([a-z][a-z0-9-]*): ')


def main_calls(out: str, target: str) -> None:
    uses, calls = {}, []
    for raw in open(out, errors='replace'):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            print('Main init: model', event.get('model'), '| apiKeySource', event.get('apiKeySource'),
                  '| subagents tool listed:', TOOL in (event.get('tools') or []),
                  '| mcp servers:', [(s.get('name'), s.get('status')) for s in event.get('mcp_servers') or []])
        if event.get('type') == 'result':
            print('Main result:', str(event.get('result'))[:300].replace('\n', ' | '))
        message = event.get('message')
        # Some events (system permission_denied, ...) carry a plain-text message: no content to read.
        content_items = message.get('content') if isinstance(message, dict) else None
        for item in content_items if isinstance(content_items, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use' and item.get('name') == TOOL:
                uses[item['id']] = item.get('input') or {}
            if item.get('type') == 'tool_result' and item.get('tool_use_id') in uses:
                content = item.get('content')
                text = content if isinstance(content, str) else ''.join(
                    part.get('text', '') for part in content or [] if isinstance(part, dict))
                try:
                    document = json.loads(text)
                except ValueError:
                    document = None
                if not isinstance(document, dict):
                    denial = DENIAL.search(text)
                    document = {'error': {'code': denial.group(1), 'message': text} if denial else
                                {'code': 'unparsed-tool-result', 'message': text[:300]}}
                request = uses[item['tool_use_id']]
                calls.append({'feature': request.get('feature'), 'arguments': request.get('arguments'),
                              'document': document, 'failed': bool(item.get('is_error')) or 'error' in document})
    Path(target).write_text(json.dumps(calls, indent=1))
    print(f'{len(calls)} subagents call(s) -> {target}')


def rehearse(root: str, project: str, child: str, step: str, target: str) -> None:
    import graftling
    from graftling import AgentControl, AgentsError, Caller
    from graftling.claude.driver import ClaudeDriver

    control = AgentControl(Path(root), {'claude': ClaudeDriver(Path(project), {'executable': child})})
    try:
        control.require_connections()
        refusal = None
    except AgentsError as error:
        refusal = {'error': {'code': error.code, 'message': error.message}}
    call = graftling.bind(control, Caller('rehearsal-613', None, 'rehearsal-session', 'claude'))
    calls = []

    def run(feature: str, arguments: dict) -> dict:
        if refusal is not None:
            document, failed = refusal, True
        else:
            result = call({'action': feature, **arguments})
            document, failed = result.document, result.failed
        calls.append({'feature': feature, 'arguments': arguments, 'document': document, 'failed': failed})
        return document

    if step == 'A':
        run('models', {'runtime': 'claude'})
        run('create', {'runtime': 'claude', 'model': 'claude-haiku-5-5', 'tools': ['Read'],
                       'instruction': 'Answer with exactly one word: ready.'})
    else:
        created = run('create', {'runtime': 'claude', 'model': 'claude-haiku-5-5', 'tools': ['Read'],
                                 'instruction': 'Answer with exactly one word: ready.'})
        if created.get('agent'):
            run('wait', {'agent': created['agent'], 'timeout_seconds': 60})
            run('retire', {'agent': created['agent']})
    Path(target).write_text(json.dumps(calls, indent=1))
    print(f'REHEARSAL (not acceptance): {len(calls)} call(s) through graftling.bind -> {target}')


def check(target: str, step: str, root: str) -> int:
    calls = json.loads(Path(target).read_text()) if Path(target).is_file() else []
    if not calls:
        print(f'  no subagents call was recorded ({target})')
    records = sorted(p.stem for p in (Path(root) / 'control' / 'agents').glob('agent-*.json'))
    for item in calls:
        document = item['document']
        print(f"  {item['feature']}: failed={item['failed']} "
              + (f"error={document['error'].get('code')}: {document['error'].get('message', '')[:200]}"
                 if isinstance(document.get('error'), dict) else
                 f"agent={document.get('agent')} state={(document.get('result') or {}).get('state')} "
                 f"outcome={((document.get('result') or {}).get('last_result') or {}).get('outcome')}"))
    results = []
    if step == 'A':
        for feature in ('models', 'create'):
            found = [item for item in calls if item['feature'] == feature]
            error = (found[0]['document'].get('error') or {}) if found else {}
            results.append((f'{feature} refused with invalid-config naming "{REFUSAL}"',
                            bool(found) and found[0]['failed'] and error.get('code') == 'invalid-config'
                            and REFUSAL in error.get('message', '')))
        results.append(('no Agent record was created', not records))
    else:
        created = [item for item in calls if item['feature'] == 'create']
        # 'failed' there may be the child's first execution; an Agent id means create started it.
        agent = created[0]['document'].get('agent') if created else None
        results.append(('create returned an Agent (the child was started)', bool(agent) and agent in records))
        record = (Path(root) / 'control' / 'agents' / f'{agent}.json') if agent else None
        print(f'  agent: {agent or "NONE"}; records: {records}')
        retired = [item for item in calls if item['feature'] == 'retire']
        results.append(('retire succeeded', bool(retired) and not retired[0]['failed']))
        if record is not None:
            print(f'  follow-up: python3 -m json.tool {record}')
    failed = 0
    for label, ok in results:
        print(f"CHECK 613 {step}: {label}: {'PASS' if ok else 'FAIL'}")
        failed |= not ok
    return failed


if __name__ == '__main__':
    operation = sys.argv[1]
    if operation == 'main':
        main_calls(*sys.argv[2:4])
    elif operation == 'rehearse':
        rehearse(*sys.argv[2:7])
    else:
        sys.exit(check(*sys.argv[2:5]))
