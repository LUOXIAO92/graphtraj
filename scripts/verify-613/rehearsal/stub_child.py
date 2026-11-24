#!/Users/luoxiao/miniconda3/bin/python3.13 -I
"""REHEARSAL ONLY: a stand-in for a Claude child's Claude Code; never acceptance evidence.

`--version` answers a supported version. Otherwise it sends one Messages request to
ANTHROPIC_BASE_URL with the authentication its environment would give (in Claude Code's
documented order: ANTHROPIC_AUTH_TOKEN as Bearer, else ANTHROPIC_API_KEY as x-api-key, else
CLAUDE_CODE_OAUTH_TOKEN as Bearer; ANTHROPIC_CUSTOM_HEADERS added), then exits 1. It cannot
read a keychain or settings file; only the real step B shows what real Claude Code sends.
"""
import json
import os
import sys
from urllib.request import ProxyHandler, Request, build_opener

if sys.argv[1:] == ['--version']:
    print('2.1.300 (Claude Code)')
    sys.exit(0)
base = os.environ.get('ANTHROPIC_BASE_URL')
if base:
    headers = {'content-type': 'application/json', 'anthropic-version': '2023-06-01'}
    if os.environ.get('ANTHROPIC_AUTH_TOKEN'):
        headers['authorization'] = 'Bearer ' + os.environ['ANTHROPIC_AUTH_TOKEN']
    elif os.environ.get('ANTHROPIC_API_KEY'):
        headers['x-api-key'] = os.environ['ANTHROPIC_API_KEY']
    elif os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'):
        headers['authorization'] = 'Bearer ' + os.environ['CLAUDE_CODE_OAUTH_TOKEN']
    for line in os.environ.get('ANTHROPIC_CUSTOM_HEADERS', '').splitlines():
        if ':' in line:
            name, value = line.split(':', 1)
            headers[name.strip().lower()] = value.strip()
    # As Claude Code does: its own Session id on every Messages request.
    for flag in ('--session-id', '--resume'):
        if flag in sys.argv:
            headers['x-claude-code-session-id'] = sys.argv[sys.argv.index(flag) + 1]
    # Negative rehearsal cases only (VERIFY613_STUB_BAD): a second credential, or another Session id.
    bad = os.environ.get('VERIFY613_STUB_BAD', '')
    if bad == 'authorization':
        headers['authorization'] = 'Bearer stub-not-the-dummy'
    elif bad == 'session':
        headers['x-claude-code-session-id'] = 'stub-wrong-session-id'
    body = json.dumps({'model': 'claude-haiku-5-5', 'max_tokens': 8, 'stream': False,
                       'messages': [{'role': 'user', 'content': 'ready?'}]}).encode()
    records = os.environ.get('VERIFY613_STUB_RECORDS')
    if records:  # no-bind rehearsal: the record recorder.py would write, by its own rule
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from recorder import describe
        dummy = os.environ.get(os.environ.get('VERIFY613_STUB_DUMMY', ''), '')
        with open(records, 'a') as stream:
            count = sum(1 for _ in open(records))
            stream.write(json.dumps({'n': count + 1, 'method': 'POST', 'path': '/v1/messages',
                                     **describe(headers, dummy)}, sort_keys=True) + '\n')
        sys.exit(1)
    try:
        build_opener(ProxyHandler({})).open(Request(base.rstrip('/') + '/v1/messages', data=body, headers=headers),
                                            timeout=10).read()
    except OSError as error:
        print(f'stub child: request failed: {type(error).__name__}', file=sys.stderr)
sys.exit(1)
