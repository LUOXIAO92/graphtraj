"""Task 609 real-host helper: list, pick and judge. Prints names, ids and PASS/FAIL lines, never a key value.

Usage (run with -I by the Python named in each case):
  <venv python> -I x609.py discover <data root> <choice file>
      Installed graftling's discover_models for each declared connection (what the `models` feature calls).
      Prints each connection's groups (provider: count, ids) and writes <choice file> with the Pi Main's model
      and the provider/model C uses: provider opencode-go first, then opencode; the first model id that contains
      glm or deepseek (the models the user says the key serves), else the group's first id.
  <python> -I x609.py L <data root> <file>...
  <python> -I x609.py C <data root> <provider> <model> <token> <file>...
      Judge the subagents result documents found in the Pi records <file>... (stdout.jsonl, Session files).
  <python> -I x609.py nokey <variable> <path>...
      PASS when no file under <path>... contains the variable's value; the value itself is never printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

PROVIDERS = ('opencode-go', 'opencode')          # the two Pi connections, in C's order of preference
CONNECTIONS = {'pi-opencode': 'opencode', 'pi-opencode-go': 'opencode-go'}
PREFERRED = re.compile(r'glm|deepseek', re.IGNORECASE)


def check(label: str, ok: bool, detail: str = '') -> bool:
    """Print one CHECK line and return ``ok``."""
    print(f"CHECK 609 {label}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")
    return ok


def documents(paths: list[str]) -> list[dict]:
    """Return every subagents result document in the records, first-seen order, without repeats.

    A document is a JSON object with ``action`` and ``result`` or ``error``; tool results carry it as text,
    possibly inside another JSON string, so strings that look like JSON are parsed and searched again.
    """
    found: dict[str, dict] = {}

    def walk(value):
        if isinstance(value, dict):
            if 'action' in value and ('result' in value or 'error' in value):
                found.setdefault(json.dumps(value, sort_keys=True), value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.lstrip().startswith(('{', '[')) and '"action"' in value:
            try:
                walk(json.loads(value))
            except ValueError:
                pass

    for name in paths:
        path = Path(name)
        for item in ([path] if path.is_file() else sorted(path.rglob('*.jsonl')) if path.is_dir() else []):
            for line in item.read_text(encoding='utf-8', errors='replace').splitlines():
                try:
                    walk(json.loads(line))
                except ValueError:
                    continue
    return list(found.values())


def records(root: Path) -> list[dict]:
    """Return the Agent records in the data root."""
    return [json.loads(path.read_text()) for path in sorted((root / 'control' / 'agents').glob('*.json'))]


def discover(root: str, choice: str) -> int:
    """List each declared connection with installed graftling and write C's choice."""
    from graftling import __version__, discover_models, read_connections

    print(f'graftling {__version__} from {Path(sys.modules["graftling"].__file__).parent}')
    connections = read_connections(Path(root))['connections']
    groups: dict[str, list[str]] = {}
    ok = True
    for name, entry in connections.items():
        found = discover_models(entry)
        shown = [(group['provider'], [model['id'] for model in group['models']]) for group in found['groups']]
        print(f"connection {name}: provider {entry.get('provider')}, api_key_env {entry.get('api_key_env')}, "
              f"status {found['status']}")
        for provider, ids in shown:
            print(f'  group {provider}: {len(ids)} models: {" ".join(ids)}')
            groups.setdefault(provider, []).extend(ids)
        ok &= check(f'discover_models {name} lists only its provider {entry.get("provider")!r}',
                    found['status'] == 'available' and [p for p, _ in shown] == [entry.get('provider')],
                    f"groups {[p for p, _ in shown]}")

    shared = sorted(set(groups.get(PROVIDERS[0], ())) & set(groups.get(PROVIDERS[1], ())))
    print(f'ids offered by both providers (create needs provider to choose one): {" ".join(shared) or "none"}')
    for provider in PROVIDERS:
        ids = groups.get(provider) or []
        if ids:
            model = next((item for item in ids if PREFERRED.search(item)), ids[0])
            Path(choice).write_text(f'provider={provider}\nmodel={model}\n', encoding='utf-8')
            print(f'choice for the Pi Main and C: provider={provider} model={model} '
                  f"({'matches glm|deepseek' if PREFERRED.search(model) else 'first id; none matched glm|deepseek'})")
            return 0 if ok else 1
    print('STOP: neither opencode-go nor opencode listed a model, so there is nothing to choose.')
    return 1


def judge_l(root: str, paths: list[str]) -> int:
    """The models listing through the MCP, and the two refusals before any child starts."""
    found = documents(paths)
    ok = True
    listing = [doc for doc in found if doc.get('action') == 'models' and isinstance(doc.get('result'), dict)]
    connections = listing[0]['result'].get('connections', []) if listing else []
    for entry in connections:
        shown = [(group['provider'], [model['id'] for model in group['models']]) for group in entry.get('groups', [])]
        print(f"models: connection {entry.get('connection')} provider {entry.get('provider')} "
              f"api_key_env {entry.get('api_key_env')} status {entry.get('status')}: "
              + '; '.join(f'{p} {len(ids)} models' for p, ids in shown))
    ok &= check('L models through mcp__graftling__subagents lists both connections, each as its own provider group '
                'with models', bool(connections) and
                {e.get('connection'): [g['provider'] for g in e.get('groups', []) if g.get('models')]
                 for e in connections} == {name: [provider] for name, provider in CONNECTIONS.items()},
                f'{len(listing)} models result(s)')

    codes = [doc['error'].get('code') for doc in found if doc.get('action') == 'create' and 'error' in doc]
    print(f'create errors seen: {codes}')
    ok &= check('L create without provider -> ambiguous-connection', 'ambiguous-connection' in codes)
    ok &= check('L create with an undeclared provider -> invalid-provider', 'invalid-provider' in codes)
    created = records(Path(root))
    ok &= check('L no Agent record was created', not created, f'{len(created)} record(s)')
    return 0 if ok else 1


def judge_c(root: str, provider: str, model: str, token: str, paths: list[str]) -> int:
    """A child created with provider and model ended with the token; its record names that provider and model."""
    found = documents(paths)
    ok = True
    created = [doc for doc in found if doc.get('action') == 'create' and isinstance(doc.get('result'), dict)]
    agent = created[0].get('agent') if created else None
    result = created[0]['result'] if created else {}
    print(f"create: agent {agent} connection {result.get('connection')} model {result.get('model')}")
    ok &= check('C create through mcp__graftling__subagents selected the provider\'s connection and the model',
                result.get('connection') == f'pi-{provider}' and result.get('model') == model)

    waits = [doc for doc in found if doc.get('action') in ('wait', 'status') and doc.get('agent') == agent
             and isinstance(doc.get('result'), dict)]
    ends = [(doc['action'], (doc['result'].get('last_result') or {})) for doc in waits]
    for action, last in ends:
        print(f"{action}: outcome {last.get('outcome')} last_message {str(last.get('last_message'))[:80]!r}")
    ok &= check(f'C the child ended (wait result outcome completed) with last_message {token}',
                any(action == 'wait' and last.get('outcome') == 'completed'
                    and str(last.get('last_message', '')).strip() == token for action, last in ends))

    record = next((item for item in records(Path(root)) if item.get('agent') == agent), {})
    # A Pi driver's settings hold its launch request under adapter_request (pi/driver.py prepare).
    settings = (record.get('settings') or {}).get('adapter_request') or record.get('settings') or {}
    print(f"record: selection {json.dumps(record.get('selection'))}; settings provider {settings.get('provider')} "
          f"model {settings.get('model')} api_key_env {settings.get('api_key_env')} "
          f"provider_domain {settings.get('provider_domain')}")
    ok &= check('C the child ran on that provider and model with the connection\'s key variable',
                (settings.get('provider'), settings.get('model'), settings.get('api_key_env'))
                == (provider, model, 'OPENCODE_API_KEY'))
    retired = [doc for doc in found if doc.get('action') == 'retire' and (doc.get('result') or {}).get('retired')]
    ok &= check('C the child was retired', bool(retired) or bool(record.get('retired_at')))
    return 0 if ok else 1


def nokey(variable: str, paths: list[str]) -> int:
    """Check that no retained file holds the variable's value."""
    value = os.environ.get(variable)
    if not value:
        print(f'CHECK 609 no {variable} value in the records: CANNOT ({variable} is not set here)')
        return 1
    hits = []
    for name in paths:
        path = Path(name)
        for item in ([path] if path.is_file() else sorted(path.rglob('*')) if path.is_dir() else []):
            if item.is_file() and not item.is_symlink() and value.encode() in item.read_bytes():
                hits.append(str(item))
    return 0 if check(f'no {variable} value in the records', not hits, f'found in {hits}' if hits else '') else 1


if __name__ == '__main__':
    command, *arguments = sys.argv[1:]
    if command == 'discover':
        sys.exit(discover(*arguments))
    if command == 'L':
        sys.exit(judge_l(arguments[0], arguments[1:]))
    if command == 'C':
        sys.exit(judge_c(*arguments[:4], arguments[4:]))
    if command == 'nokey':
        sys.exit(nokey(arguments[0], arguments[1:]))
    sys.exit(f'unknown command {command}')
