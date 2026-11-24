"""614 helper: isolated catalog and roles, a plain-MCP probe, and the judge of a real Claude stream.

usage (the step venv's python, -I):
  x614.py catalog <out.yml>                 the isolated user catalog (claude-614: anthropic + gw614; codex-614)
  x614.py roles <project>                   roles.yml: claude, routed, inline (no catalog provider), coder
  x614.py mcpconfig <.mcp.json> <out.json> <home> <fake value file>
                                            Claude's --mcp-config: the project's graphtraj entry plus env HOME and
                                            FAKE614_KEY (a FAKE value, never a credential; nothing is launched on it)
  x614.py mcp <project> <fake value file> <command...>
                                            plain MCP path: starts <command> (graphtraj-mcp) in <project> and makes
                                            the same three subagents calls the real host makes; judged as `judge`
  x614.py judge <stream.jsonl> <stderr.txt> <fake value file>
                                            the real host's stream: its three mcp__graphtraj__subagents calls
  x614.py prompt                            the one-line prompt of the real host
  x614.py selfenv                           credential-class names this python sees (names only)
Prints only facts; never prints the fake value.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

KEY_ENV  = 'FAKE614_KEY'
TOOL     = 'mcp__graphtraj__subagents'
CALLS    = ({'action': 'discover', 'query': ''},
            {'action': 'describe', 'feature': 'models'},
            {'action': 'execute', 'feature': 'models', 'arguments': {'runtime': 'claude'}})
PROMPT   = ('Use only the mcp__graphtraj__subagents tool, inline arguments, one call at a time in this order: '
            + '; '.join(f'call {n} = {json.dumps(call, separators=(",", ":"))}' for n, call in enumerate(CALLS, 1))
            + '. Make no other call. Then reply with exactly one line: DONE-614.')
EXPECTED = {'anthropic': ['claude'], None: ['inline'], 'gw614': ['routed']}
CRED     = re.compile(r'(KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$')


def catalog(out: str) -> int:
    """Two claude providers (one a declared gateway keyed by FAKE614_KEY, never launched) and a codex entry."""
    import yaml

    document = {'version': 1, 'runtimes': {
        'claude-614': {'runtime': 'claude', 'providers': {
            'anthropic': {'models': {'opus': {'id': 'claude-opus-5-5', 'source': 'manual',
                                              'supported_efforts': ['low', 'medium', 'high']}}},
            'gw614': {'base_url': 'https://gateway-614.invalid/v1', 'api_key_env': KEY_ENV,
                      'models': {'sonnet': {'id': 'claude-sonnet-5-5', 'source': 'manual'}}},
        }},
        'codex-614': {'runtime': 'codex', 'providers': {
            'openai': {'models': {'gpt': {'id': 'gpt-5.5', 'source': 'manual'}}}}},
    }}
    Path(out).write_text(yaml.safe_dump(document, sort_keys=False))
    print(f'catalog draft {out}:')
    print(Path(out).read_text(), end='')
    return 0


def roles(project: str) -> int:
    """Three claude roles (two catalog providers, one inline without a provider) and one codex role."""
    import yaml

    path = Path(project) / '.graphtraj/roles.yml'
    names = {'claude': {'connection': 'claude-614/anthropic/opus'},
             'routed': {'connection': 'claude-614/gw614/sonnet'},
             'inline': {'runtime': 'claude', 'model': 'claude-haiku-5-5'},
             'coder':  {'connection': 'codex-614/openai/gpt'}}
    path.write_text(yaml.safe_dump({'roles': names, 'role_tree': {name: {} for name in names}}, sort_keys=False))
    print(f'roles file {path}:')
    print(path.read_text(), end='')
    return 0


def mcpconfig(source: str, out: str, home: str, fake_file: str) -> int:
    """Claude's --mcp-config: the graphtraj entry configuration --write made, with HOME and the fake key."""
    entry = json.loads(Path(source).read_text())['mcpServers']['graphtraj']
    entry = {**entry, 'env': {**entry.get('env', {}), 'HOME': home, KEY_ENV: Path(fake_file).read_text().strip()}}
    Path(out).write_text(json.dumps({'mcpServers': {'graphtraj': entry}}, indent=2))
    print(f'{out}: graphtraj -> {entry["command"]} {" ".join(entry["args"])} | env names: {sorted(entry["env"])}')
    return 0


def payload(text: str) -> object:
    """The JSON document of one tool result text, else the text."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def check(results: list, secret: str, everything: str) -> int:
    """Judge the three answers: discover lists models, describe works, execute models groups roles by provider."""
    failed = 0

    def ck(name: str, ok: bool, detail: str = '') -> None:
        nonlocal failed
        failed += not ok
        print(f'CHECK 614 {name}: {"PASS" if ok else "FAIL"}{f" ({detail})" if detail else ""}')

    while len(results) < 3:
        results.append((True, 'no answer'))
    (d_err, discover), (s_err, describe), (m_err, models) = results
    features = [item.get('feature') for item in discover.get('features', [])] if isinstance(discover, dict) else []
    ck('discover lists models', not d_err and 'models' in features, f'features: {features}')
    ck('describe models answers', not s_err and isinstance(describe, dict) and 'error' not in describe,
       str(describe)[:160] if s_err or not isinstance(describe, dict) or 'error' in describe else '')
    result = models.get('result') if isinstance(models, dict) else None
    ck('execute models is not an error', not m_err and isinstance(result, dict), str(models)[:300] if m_err else '')
    result = result or {}
    groups = {group.get('provider'): [model.get('configuration') for model in group.get('models', [])]
              for group in result.get('groups', [])}
    print(f'models groups (provider -> roles): {groups}')
    for model in result.get('models', []):
        print(f"  model {model.get('id')} | provider {model.get('provider')} | configuration "
              f"{model.get('configuration')} | connection {model.get('connection')} | api_key_env "
              f"{model.get('api_key_env')} | supported_efforts {model.get('supported_efforts')}")
    ck('grouped by provider: anthropic, gw614 and the provider-null inline role; no codex role', groups == EXPECTED,
       f'expected {EXPECTED}')
    keys = {model.get('configuration'): model.get('api_key_env') for model in result.get('models', [])}
    ck(f'key NAMES only: routed names {KEY_ENV}, the others none', keys.get('routed') == KEY_ENV
       and keys.get('claude') is None and keys.get('inline') is None, str(keys))
    ck('the fake key value appears nowhere in the record', bool(secret) and secret not in everything,
       '' if secret else 'no fake value to look for')
    print(f'RESULT 614 judge: {"PASS" if not failed else f"FAIL ({failed})"}')
    return 1 if failed else 0


def mcp(project: str, fake_file: str, command: list[str]) -> int:
    """Plain MCP path: the server answers the same three calls; no Claude, no native association."""
    process = subprocess.Popen(command, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    replies, done, last = {}, threading.Event(), 2 + len(CALLS)

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

    threading.Thread(target=reader, daemon=True).start()
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'probe-614', 'version': '0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}]
    messages += [{'jsonrpc': '2.0', 'id': 3 + n, 'method': 'tools/call',
                  'params': {'name': 'subagents', 'arguments': call}} for n, call in enumerate(CALLS)]
    for message in messages:
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    done.wait(90)
    process.stdin.close()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()
    stderr = process.stderr.read()
    tools = [tool.get('name') for tool in ((replies.get(2) or {}).get('result') or {}).get('tools', [])]
    print(f'serving path: plain MCP ({" ".join(command)}; no native association) | tools/list: {tools}')
    results = []
    for number in range(3, last + 1):
        answer = (replies.get(number) or {}).get('result') or {}
        text = ' '.join(item.get('text', '') for item in answer.get('content', []) if isinstance(item, dict))
        results.append((bool(answer.get('isError')) or not answer, answer.get('structuredContent') or payload(text)))
    everything = json.dumps(replies) + stderr
    return check(results, Path(fake_file).read_text().strip(), everything)


def judge(stream: str, stderr: str, fake_file: str) -> int:
    """The real host's stream: init (plugins, MCP server), the three calls in order and their results."""
    records, uses, answers, final = [], [], {}, None
    text = Path(stream).read_text() if Path(stream).is_file() else ''
    for line in text.splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    for record in records:
        if record.get('type') == 'system' and record.get('subtype') == 'init':
            plugins = [plugin.get('name') for plugin in record.get('plugins', [])]
            servers = [(server.get('name'), server.get('status')) for server in record.get('mcp_servers', [])]
            print(f'init: model {record.get("model")} | apiKeySource {record.get("apiKeySource")} | plugins {plugins}'
                  f' | mcp servers {servers} | tools with graphtraj: '
                  f'{[tool for tool in record.get("tools", []) if "graphtraj" in tool]}')
            native = 'graphtraj-claude-host' in plugins
            print('serving path: ' + ('native graphtraj-claude-host association (the plugin hook prepares each call; '
                                      'host.py serve answers through NativeCalls)' if native else
                                      'graphtraj-claude-host NOT loaded: the native host refuses every call '
                                      '(no association); trust the folder first (step trust)'))
        for item in (record.get('message') or {}).get('content') or []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use':
                uses.append((item.get('id'), item.get('name'), item.get('input')))
            if item.get('type') == 'tool_result':
                content = item.get('content')
                body = (' '.join(part.get('text', '') for part in content if isinstance(part, dict))
                        if isinstance(content, list) else str(content))
                answers[item.get('tool_use_id')] = (bool(item.get('is_error')), payload(body))
        if record.get('type') == 'result':
            final = record
    for number, (use, name, arguments) in enumerate(uses, 1):
        print(f'call {number}: {name} {json.dumps(arguments)[:200]} -> '
              f'{"ERROR " if answers.get(use, (True,))[0] else ""}{json.dumps(answers.get(use, (None, None))[1])[:200]}')
    ours = [(use, arguments) for use, name, arguments in uses if name == TOOL]
    print(f'{TOOL} calls: {len(ours)}; other tool calls: {len(uses) - len(ours)}')
    if final is not None:
        print(f'final: {str(final.get("result"))[:120]!r} | is_error {final.get("is_error")} | models used '
              f'{list((final.get("modelUsage") or {}).keys())}')
    in_order = [arguments for _, arguments in ours] == list(CALLS)
    print(f'CHECK 614 the three calls were made inline, in order, and nothing else: {"PASS" if in_order and len(ours) == len(uses) else "FAIL"}')
    results = [answers.get(use, (True, 'no result')) for use, _ in ours[:3]]
    everything = text + (Path(stderr).read_text() if Path(stderr).is_file() else '')
    verdict = check(results, Path(fake_file).read_text().strip(), everything)
    return verdict or (0 if in_order and len(ours) == len(uses) else 1)


def selfenv() -> int:
    """Credential-class names in this process's environment (names only)."""
    names = sorted(name for name in os.environ
                   if any(CRED.search(part) for part in name.upper().split('_')) and not name.startswith('GIT_CONFIG_KEY_'))
    print(' '.join(names) or 'none')
    return 0


if __name__ == '__main__':
    operation, rest = sys.argv[1], sys.argv[2:]
    if operation == 'catalog':
        sys.exit(catalog(*rest))
    if operation == 'roles':
        sys.exit(roles(*rest))
    if operation == 'mcpconfig':
        sys.exit(mcpconfig(*rest))
    if operation == 'mcp':
        sys.exit(mcp(rest[0], rest[1], rest[2:]))
    if operation == 'judge':
        sys.exit(judge(*rest))
    if operation == 'prompt':
        print(PROMPT)
        sys.exit(0)
    if operation == 'selfenv':
        sys.exit(selfenv())
    sys.exit(f'unknown operation {operation}')
