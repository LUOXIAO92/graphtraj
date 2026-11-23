"""Task 578 helper for steps.zsh. Run with python -I; PyYAML from the graftling venv for `accept`.

  diag JSONL STDERR LABEL               One direct `claude -p --permission-mode auto` run: system/init model,
                                        permissionMode and apiKeySource, every other system event's subtype and
                                        permission/auto fields, the result, and stderr lines about auto mode,
                                        permission mode or the classifier. Prints DIAG-MODE <model> <mode>.
  snap ROOT                             The Agent ids recorded under data root ROOT (control/agents/*.json).
  accept MODE ROOT SNAP PARENTJSONL     Verdicts (MODE repro|check) for the children the parent created through
                                        its agents tool, from the parent's stream-json, each child's Agent record,
                                        session.yml (permissions, native_init), claude-diagnostics-*.yml and its
                                        transcript (rollout_path).
"""
import json
import re
import sys
from pathlib import Path

MARKERS = ('R578-A.', 'R578-B.', 'R578-C.', 'R578-D.')
BASH_TEXT = 'r578-bash'
MISMATCH = 'Claude did not confirm the requested permission mode'
# Narrower than or equal to `auto`: Claude asks (default/manual), plans only (plan) or denies what it would ask (dontAsk).
NOT_WIDER = {'auto': {'auto', 'default', 'manual', 'plan', 'dontAsk'},
             'default': {'default', 'manual', 'plan', 'dontAsk'}}


def events(path):
    for line in open(path, errors='replace'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def diag(jsonl: str, stderr: str, label: str) -> int:
    init, other, result = None, [], None
    for event in events(jsonl):
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            init = event
        elif event.get('type') == 'system':
            fields = {k: v for k, v in event.items() if re.search('permission|auto|mode', k, re.I)}
            other.append(f'{event.get("subtype")} {json.dumps(fields)[:200]}')
        elif event.get('type') == 'result':
            result = event
    if init is None:
        print('   NO system/init event')
    else:
        extra = {k: v for k, v in init.items() if re.search('auto|permission', k, re.I) and k != 'permissionMode'}
        print(f'   init: model {init.get("model")} permissionMode {init.get("permissionMode")}'
              f' apiKeySource {init.get("apiKeySource")} other permission/auto fields {json.dumps(extra)}')
    for line in other[:8]:
        print(f'   system event: {line}')
    if result is not None:
        print(f'   result: is_error {result.get("is_error")} {str(result.get("result"))[:120]!r}')
    lines = [l.rstrip() for l in open(stderr, errors='replace')
             if re.search(r'auto[- _]?mode|permission[- _]?mode|classifier|autoMode', l, re.I)]
    print(f'   stderr lines about auto mode / permission mode / classifier: {len(lines)}')
    for line in lines[:12]:
        print(f'     {line[:300]}')
    print(f'DIAG-MODE {label} {init and init.get("model")} {init and init.get("permissionMode")}')
    return 0 if init else 1


def snap(root: str) -> int:
    for path in sorted(Path(root, 'control', 'agents').glob('*.json')):
        print(path.stem)
    return 0


def parent_children(path: str) -> dict:
    uses, results, found = {}, {}, {}
    for event in events(path):
        message = event.get('message')
        if not isinstance(message, dict):
            continue
        for block in message.get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and str(block.get('name', '')).endswith('__agents'):
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
        try:
            agent = json.loads(text).get('agent')
        except (ValueError, AttributeError):
            agent = None
        found[marker] = {'agent': agent, 'arguments': arguments, 'result': text[:600]}
    return found


def child_facts(root: str, agent: str) -> dict:
    import yaml
    facts = {'bash_calls': [], 'bash_output_seen': False, 'reply': None, 'warnings': [], 'permissions': None}
    record = json.loads(Path(root, 'control', 'agents', f'{agent}.json').read_text())
    last = (record.get('executions') or [{}])[-1]
    facts.update(state=last.get('state'), outcome=last.get('outcome'), error=last.get('error'),
                 last_message=last.get('last_message'), session=record.get('session'))
    native = Path(root, 'native', agent)
    if (native / 'session.yml').exists():
        data = yaml.safe_load((native / 'session.yml').read_text()) or {}
        facts['permissions'] = data.get('permissions')
        facts['init_model'] = (data.get('native_init') or {}).get('model')
        facts['transcript'] = data.get('rollout_path')
    for path in sorted(native.glob('claude-diagnostics-*.yml')):
        data = yaml.safe_load(path.read_text()) or {}
        facts['warnings'] += data.get('warnings') or []
        facts['diag_permission'] = data.get('permission_mode', facts.get('diag_permission'))
    transcript = facts.get('transcript')
    if transcript and Path(transcript).exists():
        bash_ids = set()
        for event in events(transcript):
            message = event.get('message')
            if not isinstance(message, dict):
                continue
            content = message.get('content')
            if isinstance(content, str):
                if message.get('role') == 'assistant':
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
                    facts['bash_output_seen'] = facts['bash_output_seen'] or BASH_TEXT in text
                if block.get('type') == 'text' and message.get('role') == 'assistant':
                    facts['reply'] = block.get('text', '')[:300]
    return facts


def accept(mode: str, root: str, snapshot: str, parent: str) -> int:
    before = set(open(snapshot).read().split())
    children = parent_children(parent)
    failed, mismatched, narrower_ok = 0, 0, 0
    print(f'parent stream-json: {parent}')
    for marker in MARKERS:
        child = children.get(marker)
        print(f'-- child [{marker}]')
        if not child or not child['agent']:
            print(f'   FAIL: no create result with an agent id ({child["result"] if child else "no create call"})')
            failed += 1
            continue
        agent = child['agent']
        if agent in before:
            print(f'   FAIL: {agent} existed before this run')
            failed += 1
            continue
        facts = child_facts(root, agent)
        perm = facts['permissions'] or {}
        requested, observed = perm.get('requested'), perm.get('observed')
        ran = facts['bash_output_seen'] or BASH_TEXT in str(facts['last_message'] or '')
        print(f'   create arguments: {json.dumps(child["arguments"])}')
        print(f'   agent {agent}; init model {facts.get("init_model")}; state {facts["state"]};'
              f' outcome {facts["outcome"]}; error {json.dumps(facts["error"])}')
        print(f'   permissions (session.yml): {json.dumps(perm)}')
        print(f'   diagnostics: permission_mode {json.dumps(facts.get("diag_permission"))};'
              f' warnings {json.dumps(facts["warnings"])}')
        print(f'   work: Bash calls {facts["bash_calls"]}; Bash output contained {BASH_TEXT!r}:'
              f' {facts["bash_output_seen"]}; last reply {facts["reply"]!r}; record last_message'
              f' {str(facts["last_message"])[:120]!r}')
        if observed in (None, 'unknown') or requested is None:
            print('   FAIL: no requested/observed permission mode recorded')
            failed += 1
            continue
        same = requested == ('default' if observed == 'manual' else observed)
        mismatched += not same
        error_text = str((facts['error'] or {}).get('message'))
        if mode == 'repro':
            premise = not same and facts['outcome'] == 'failed' and MISMATCH in error_text
            print(f'   {"MISMATCH" if not same else "match"}: requested {requested}, observed {observed};'
                  f' work ran: {ran}; outcome {facts["outcome"]}'
                  + ('; PREMISE: failed with the permission-mode error' if premise else ''))
            continue
        if same:
            ok = facts['outcome'] == 'completed' and ran
            why = 'matching mode: outcome completed and the work ran'
        elif observed in NOT_WIDER.get(requested, ()):
            warned = any(w.get('category') == 'permission_mode_narrower' for w in facts['warnings'])
            recorded = perm.get('matches_request') is False and perm.get('narrower') is True
            ok = facts['outcome'] == 'completed' and ran and warned and recorded
            narrower_ok += ok
            why = (f'narrower mode: outcome completed ({facts["outcome"]}), the work ran ({ran}), permissions record'
                   f' matches_request false and narrower true ({recorded}), diagnostics warning'
                   f' permission_mode_narrower ({warned})')
        else:
            ok = facts['outcome'] == 'failed' and MISMATCH in error_text
            why = 'wider or not comparable mode: outcome failed with the permission-mode error'
        print(f'   {"PASS" if ok else "FAIL"}: requested {requested}, observed {observed}; {why}')
        failed += not ok
    if mode == 'repro':
        print(f'children with a mode mismatch: {mismatched}')
        if mismatched:
            print('REPRODUCED: at least one child reported a permission mode other than the requested one')
            return 0
        print(f'NOT REPRODUCED: no child reported a permission mode other than the requested one'
              f' ({failed} of {len(MARKERS)} children without a usable record)')
        return 1
    if not narrower_ok:
        print('FAIL (INCONCLUSIVE): no child showed a narrower observed mode that completed; the changed behaviour'
              ' was not exercised')
        failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'diag':
        sys.exit(diag(*args[:3]))
    if command == 'snap':
        sys.exit(snap(args[0]))
    if command == 'accept':
        sys.exit(accept(*args[:4]))
    sys.exit(f'unknown command {command}')
