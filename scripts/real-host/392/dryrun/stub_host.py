#!/usr/bin/env python3
"""Stand in for claude, codex, pi and dsh when dry-checking the 392 steps. Never used on a real run.

It reads the numbered calls in a prompt and answers each with a plausible public result, in the output
format of the host it stands in for. It proves the steps' plumbing and judgement only: no real host,
Runtime, model, notice or sandbox is exercised. Set RH_DRY_BAD=1 to answer so that criteria must fail.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

BAD = os.environ.get('AGENTS_392_DRY_BAD') == '1'
NAME = Path(sys.argv[0]).name
ARGV = sys.argv[1:]


def plan(prompt: str) -> list[str]:
    """Return the numbered call lines of a prompt, those in its tail included."""
    return [match.group(1) for match in re.finditer(r'^\d+\. (.*)$', prompt, re.M)]


def run(prompt: str, state: dict) -> tuple[list[dict], list[dict]]:
    """Answer each call; return public results and notices."""
    results, notices = [], []
    created: dict[int, str] = {}
    for number, line in enumerate(plan(prompt), 1):
        for index, agent in created.items():
            line = line.replace(f'<agent from {index}>', agent)
        line = re.sub(r'<the first request document from call \d+, unchanged>', '{}', line).replace('<that child>', 'c1')
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if request.get('action') != 'execute':
            results.append({'action': 'discover', 'result': {'features': []}})
            continue
        feature, arguments = request['feature'], request['arguments']
        agent = arguments.get('agent')
        record = state['agents'].get(agent)
        if feature == 'create':
            if 'no-such' in str(arguments.get('model')) and 'claude-no-such' not in str(arguments.get('model')):
                results.append({'action': 'create', 'error': {'code': 'invalid-model', 'message': 'not a candidate'}})
                continue
            if arguments.get('workspace', '').endswith('layer1-outside'):
                results.append({'action': 'create', 'error': {'code': 'workspace-denied', 'message': 'outside'}})
                continue
            agent = uuid.uuid4().hex[:12]
            record = state['agents'][agent] = {
                'agent': agent, 'name': arguments.get('name'), 'runtime': arguments['runtime'], 'preset': None,
                'connection': None, 'model': arguments.get('model'), 'reasoning_effort': arguments.get('reasoning_effort'),
                'review': 'checker' if 'review' in os.environ.get('RH_STUB_NAME', '') else None,
                'workspace': arguments.get('workspace'), 'state': 'active', 'parent': None,
                'creator': {'host': 'stub', 'agent': None, 'session': 'stub-session'}, 'host': 'stub',
                'session': agent + '-s', 'last': arguments['instruction']}
            created[number] = agent
            results.append({'action': 'create', 'agent': agent, 'session': record['session'], 'result': dict(record)})
            continue
        if record is None:
            results.append({'action': feature, 'result': {'agents': list(state['agents'].values())}} if feature == 'status'
                           else {'action': feature, 'error': {'code': 'not-found', 'message': agent}})
            continue
        result = {key: value for key, value in record.items() if key != 'last'}
        if feature == 'send' or feature == 'resume':
            record['last'] = arguments.get('message', '')
        if feature == 'interrupt':
            result['interrupt'] = 'requested'
            record['outcome'] = 'interrupted'
        if feature == 'wait':
            if 'ask_parent' in record['last'] or 'Bash tool' in record['last'] or 'printf changed' in record['last'] or 'echo ran' in record['last']:
                if not record.get('answered'):
                    result['pending_requests'] = 1
                    notices.append({'id': f'e-{agent}:request:r', 'agent': agent, 'event': 'request', 'message': 'Permission request'})
            token = re.search(r'exactly: ([A-Z0-9=-]+)', record['last'])
            shown = 'BLUE392' if record.get('answered') and 'ask_parent' in record['last'] else '39202' if record.get('answered') else None
            if token and not BAD:
                shown = token.group(1)
            if 'outcome' in record:
                shown = None
            result['last_result'] = {'id': 'e', 'outcome': record.pop('outcome', 'completed'), 'last_message': shown,
                                     'error': None, 'terminal_confirmed': True, 'notification': 'delivered'}
        if feature == 'requests':
            method = ('agents/decision' if 'ask_parent' in record['last'] else 'claude/can_use_tool' if 'Bash tool' in record['last']
                      else 'item/autoApprovalReview/completed' if 'printf changed' in record['last'] else 'agents/review')
            result['requests'] = [{'method': method, 'params': {'reason': 'stub'}}]
        if feature == 'reply':
            record['answered'] = True
            result['reply_status'] = 'submitted'
            result['duplicate'] = bool(record.get('replied'))
            record['replied'] = True
            match = re.search(r'(/\S*review-\S+\.txt)', record['last'])
            if match and 'accept' in line:
                Path(match.group(1)).write_text('ran\n')
        if feature == 'status':
            result['last_result'] = {'id': 'e', 'outcome': 'failed' if 'NEVER' in record['last'] else 'completed',
                                     'last_message': None, 'error': {'code': 'X', 'message': 'stub reason EPERM'},
                                     'terminal_confirmed': True, 'notification': 'delivered'}
        if feature == 'retire':
            result['retired'] = True
            result['duplicate'] = bool(record.get('retired'))
            record['retired'] = True
        results.append({'action': feature, 'agent': agent, 'session': record['session'], 'execution': 'e', 'result': result})
    # A failed start's notice, which the Pi parent would receive in its turn.
    for agent, record in state['agents'].items():
        if 'NEVER' in record['last'] and not record.get('told'):
            record['told'] = True
            notices.append({'id': f'e-{agent}:failed', 'agent': agent, 'event': 'failed', 'message': 'stub reason'})
    return results, notices


def load_state(key: str) -> tuple[dict, Path]:
    """Keep agents between one host's turns, keyed by its data directory or session."""
    path = Path(os.environ.get('AGENTS_392_DRY_ROOT', '/tmp')) / f'stub-{key}.json'
    return (json.loads(path.read_text()) if path.exists() else {'agents': {}}), path


def main() -> int:
    """Answer in the form of the host this file stands in for."""
    if '--version' in ARGV:
        print(f'{NAME} 0.0.0 (stub)')
        return 0
    if NAME == 'codex' and ARGV[:2] == ['login', 'status']:
        print('Logged in (stub)')
        return 0
    if NAME == 'claude':
        if not ARGV or (not ARGV[0].startswith('-') and '-p' not in ARGV):
            print('stub interactive Claude Code: exits at once')
            return 0
        prompt = sys.stdin.read()
        if '--output-format' not in ARGV:
            print('stub answer')
            return 0
        session = ARGV[ARGV.index('--resume') + 1] if '--resume' in ARGV else ARGV[ARGV.index('--session-id') + 1]
        state, path = load_state(session)
        results, notices = run(prompt, state)
        path.write_text(json.dumps(state))
        for index, result in enumerate(results):
            if index == 0 and notices:
                result['main_notices'] = [{'id': item['id'], 'event': {'alias': item['agent'], 'event': item['event'], 'message': item['message']}}
                                          for item in notices]
            print(json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': json.dumps(result)}]}}))
        return 0
    if NAME == 'codex-host':
        directory = ARGV[ARGV.index('--directory') + 1]
        state, path = load_state(uuid.uuid5(uuid.NAMESPACE_URL, directory).hex)
        results, notices = run(ARGV[-1], state)
        path.write_text(json.dumps(state))
        output = {'parent_session': 'p', 'stop_unconfirmed': [],
                  'operations': [{'action': item['action'], 'failed': 'error' in item, 'result': item} for item in results],
                  'deliveries': [{'id': item['id'], 'agent': item['agent'], 'event': item['event'], 'body': item['message'], 'accepted': True}
                                 for item in notices]}
        Path(ARGV[ARGV.index('--output') + 1]).write_text(json.dumps(output))
        return 0
    if NAME == 'codex':
        sys.stdin.read()
        print('stub codex answer')
        return 0
    if NAME == 'pi':
        if '--mode' not in ARGV:
            print('stub pi answer')
            return 0
        session, directory = ARGV[ARGV.index('--session-id') + 1], Path(ARGV[ARGV.index('--session-dir') + 1])
        state, path = load_state(session)
        prompt = ARGV[-1] if ARGV[ARGV.index('--mode') + 1] == 'json' else json.loads(sys.stdin.readline())['message']
        results, notices = run(prompt, state)
        path.write_text(json.dumps(state))
        with (directory / f'2026_{session}.jsonl').open('a') as session_file:
            for item in results:
                session_file.write(json.dumps({'type': 'message', 'message': {'role': 'toolResult', 'content': [{'type': 'text', 'text': json.dumps(item)}]}}) + '\n')
            for item in notices:
                session_file.write(json.dumps({'type': 'custom_message', 'customType': 'graphtraj:agent-communication', 'content': item['message'],
                                               'details': {'fact': 'notice:' + item['id'], 'agent': item['agent'], 'event': item['event'], 'body': item['message']}}) + '\n')
        print(json.dumps({'type': 'agent_end'}))
        return 0
    if NAME == 'dsh':
        if '--json' not in ARGV:
            print('stub dsh answer')
            return 0
        given = ARGV[ARGV.index('--session-id') + 1] if '--session-id' in ARGV else uuid.uuid4().hex
        state, path = load_state(given)
        results, _ = run(ARGV[-1], state)
        path.write_text(json.dumps(state))
        print(json.dumps({'type': 'session', 'sessionId': given}))
        for item in results:
            print(json.dumps({'type': 'tool_result', 'content': json.dumps(item)}))
        print(json.dumps({'type': 'final', 'sessionId': given, 'text': 'done', 'reason': {'kind': 'completed'}}))
        return 0
    print(f'stub: unknown {NAME} {ARGV}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    time.sleep(0.05)
    raise SystemExit(main())
