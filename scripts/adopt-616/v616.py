"""616 V: the new `models` surface of a scratch venv (graphtraj 4ef36426 + graftling 0.10.0). Never the Harness.

usage: <venv>/bin/python -I v616.py mcp <label> <project> <graphtraj-mcp command> [args...]
       <venv>/bin/python -I v616.py bound <label> <project>          (HOME must be a scratch directory named vhome-*)

mcp    Starts the plain MCP entry in the isolated project and sends initialize, tools/list, subagents discover and
       subagents describe models (newline-delimited JSON-RPC). CHECKs: tools/list is exactly subagents and tasks;
       discover lists `models`; describe's input_schema requires `runtime` and offers `provider` (P's arguments).
       The server is closed by closing its stdin, and killed only if it ignores that for 20 s (this probe's child).
bound  Executes `models` through graftling's handle_request bound to GraphTraj's backend exactly as the native host
       binds a Main (614's selftest binding), on a SCRATCH catalog ($HOME/.graphtraj/connections.yml) and scratch
       project roles (the project's roles.yml is replaced for the call and restored afterwards). A random value is
       set for FAKE616_KEY inside this process only (not a credential) to show no key value is read. CHECKs: no
       error; groups {anthropic: [claude], gw616: [routed], null: [inline]}; api_key_env names only; the random
       value appears nowhere; a provider filter keeps one group; an unused provider is refused invalid-provider.
"""
import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

checks: list[bool] = []
KEY_ENV = 'FAKE616_KEY'
EXPECTED = {'anthropic': ['claude'], 'gw616': ['routed'], None: ['inline']}


def check(label: str, name: str, ok: bool, detail: str = '') -> None:
    """Print one CHECK line and keep its outcome."""
    checks.append(ok)
    print(f"CHECK 616 {label} {name}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")


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

    def call(number: int, arguments: dict) -> dict:
        return {'jsonrpc': '2.0', 'id': number, 'method': 'tools/call',
                'params': {'name': 'subagents', 'arguments': arguments}}

    threading.Thread(target=reader, daemon=True).start()
    for message in ({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                'clientInfo': {'name': 'probe-616', 'version': '0'}}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                    call(3, {'action': 'discover'}),
                    call(4, {'action': 'describe', 'feature': 'models'})):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    done.wait(90)
    process.stdin.close()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()

    def document(number: int) -> tuple[bool, dict]:
        answer = replies.get(number) or {}
        result = answer.get('result') or {}
        found = result.get('structuredContent')
        if found is None:
            text = ' '.join(i.get('text', '') for i in result.get('content', []) if isinstance(i, dict))
            try:
                found = json.loads(text)
            except ValueError:
                found = {'text': text[:300]}
        return 'error' in answer or bool(result.get('isError')), found if isinstance(found, dict) else {}

    tools = sorted(t.get('name') for t in (replies.get(2) or {}).get('result', {}).get('tools', []))
    print(f'{label} server: {" ".join(command[:3])} | tools: {tools}')
    if not tools:
        print(f'{label} stderr tail: {process.stderr.read()[-400:]!r}')
    check(label, 'MCP tools/list is exactly subagents, tasks', tools == ['subagents', 'tasks'])
    failed, found = document(3)
    features = [i.get('feature') for i in found.get('features') or [] if isinstance(i, dict)]
    print(f'{label} subagents discover: error {failed} | features {features}')
    check(label, 'subagents discover lists models', not failed and 'models' in features)
    failed, found = document(4)
    schema = found.get('input_schema') or {}
    props, required = sorted((schema.get('properties') or {})), sorted(schema.get('required') or [])
    print(f'{label} subagents describe models: error {failed} | properties {props} | required {required}')
    check(label, "describe models: 'runtime' required, 'provider' optional (P sends {\"runtime\": \"claude\"})",
          not failed and required == ['runtime'] and 'provider' in props)


def bound(label: str, project: str) -> None:
    import yaml
    from graftling import Caller, bind
    from graftling.discovery import handle_request
    from graphtraj.configuration.project_roles import roles_file
    from graphtraj.interfaces.agents import GraphTrajAgents

    home = Path.home()
    if not home.name.startswith('vhome'):
        print(f'STOP: HOME {home} is not a scratch vhome-* directory'); sys.exit(2)
    fake = 'fake-616-' + secrets.token_hex(12)
    os.environ[KEY_ENV] = fake                          # this process only; a declared NAME, never launched
    catalog = {'version': 1, 'runtimes': {'claude-616': {'runtime': 'claude', 'providers': {
        'anthropic': {'models': {'opus': {'id': 'claude-opus-5-5', 'source': 'manual',
                                          'supported_efforts': ['low', 'medium', 'high']}}},
        'gw616': {'base_url': 'https://gateway-616.invalid/v1', 'api_key_env': KEY_ENV,
                  'models': {'sonnet': {'id': 'claude-sonnet-5-5', 'source': 'manual'}}}}}}}
    (home / '.graphtraj').mkdir(parents=True, exist_ok=True)
    (home / '.graphtraj/connections.yml').write_text(yaml.safe_dump(catalog, sort_keys=False))
    root = Path(project).resolve()
    path = roles_file(root)
    before = path.read_bytes() if path.exists() else None
    names = {'claude': {'connection': 'claude-616/anthropic/opus'},
             'routed': {'connection': 'claude-616/gw616/sonnet'},
             'inline': {'runtime': 'claude', 'model': 'claude-haiku-5-5'}}
    print(f'{label} scratch catalog {home}/.graphtraj/connections.yml | scratch roles {path} (restored afterwards)')
    try:
        path.write_text(yaml.safe_dump({'roles': names, 'role_tree': {name: {} for name in names}}, sort_keys=False))
        os.chdir(root)
        call = bind(GraphTrajAgents(root, root), Caller('claude-native', None, 'v-616', 'claude'))
        answers = [handle_request({'action': 'execute', 'feature': 'models', 'arguments': arguments}, call)
                   for arguments in ({'runtime': 'claude'}, {'runtime': 'claude', 'provider': 'gw616'},
                                     {'runtime': 'claude', 'provider': 'nope616'})]
    finally:
        path.write_bytes(before) if before is not None else path.unlink(missing_ok=True)
    text = json.dumps([a.document for a in answers])
    full, one, bad = answers
    result = (full.document or {}).get('result') or {}
    groups = {g.get('provider'): sorted(m.get('configuration') for m in g.get('models', []))
              for g in result.get('groups') or []}
    keys = {m.get('configuration'): m.get('api_key_env') for m in result.get('models') or []}
    print(f'{label} execute models {{runtime: claude}}: error {full.failed} | groups {groups} | key names {keys}')
    check(label, 'execute models answers without error', not full.failed)
    check(label, 'grouped by provider: anthropic [claude], gw616 [routed], null [inline]', groups == EXPECTED, str(groups))
    check(label, 'api_key_env names only (routed FAKE616_KEY, others none)',
          keys == {'claude': None, 'routed': KEY_ENV, 'inline': None})
    check(label, 'the random FAKE616_KEY value appears nowhere in the answers', fake not in text)
    one_groups = [g.get('provider') for g in ((one.document or {}).get('result') or {}).get('groups') or []]
    check(label, 'provider gw616 keeps one group', not one.failed and one_groups == ['gw616'], str(one_groups))
    code = json.dumps(bad.document)[:200]
    check(label, 'an unused provider is refused invalid-provider', bad.failed and 'invalid-provider' in code, code)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'mcp' and len(sys.argv) > 4:
        mcp(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif mode == 'bound' and len(sys.argv) == 4:
        bound(sys.argv[2], sys.argv[3])
    else:
        print(__doc__); sys.exit(2)
    sys.exit(0 if checks and all(checks) else 1)
