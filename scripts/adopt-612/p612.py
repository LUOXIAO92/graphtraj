"""612 P and Pr: list models by provider through Main's MCP (tasks runtime_connections discover). Read only.

usage: p612.py choose
         Run by production's own Python (-I): reads the user catalog (~/.graphtraj/connections.yml) through
         graphtraj's read_catalog, prints every entry with its runtime and providers (base_url present or not,
         api_key_env NAME, model count; no value), then one line `CHOICE <entry> <provider> <why>` or `CHOICE none`.
         Choice order (Leader, 612): a claude entry's provider with neither base_url nor api_key_env (the
         pre-approved Claude login is the only credential); otherwise a provider whose api_key_env is exactly
         OPENCODE_API_KEY or DEEPSEEK_API_KEY (approved for Task 612); never any other.
       p612.py judge <raw result file> <entry> <provider> <counts before> <counts after>
         Reads Main's saved raw result (JSON or YAML) and prints CHECK lines.
"""
import json
import re
import sys

APPROVED = ('OPENCODE_API_KEY', 'DEEPSEEK_API_KEY')
NAME     = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
SECRET   = re.compile(r'(sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{10,}|eyJ[A-Za-z0-9_-]{20,})')
KEYLIKE  = re.compile(r'(^|_)(api_key|apikey|token|secret|password|authorization)($|_)', re.IGNORECASE)


def choose() -> int:
    """Print the catalog's entries (names only) and the entry/provider P asks Main to discover."""
    from graphtraj.configuration.runtime_connections import connections_file, read_catalog

    catalog, revision = read_catalog()
    print(f'catalog: {connections_file()} | revision {revision[:12]}')
    first, second = None, None
    for entry, runtime in sorted((catalog.get('runtimes') or {}).items()):
        for provider, spec in sorted((runtime.get('providers') or {}).items()):
            key, url = spec.get('api_key_env'), bool(spec.get('base_url'))
            print(f'  entry {entry} | runtime {runtime["runtime"]} | provider {provider} | base_url '
                  f'{"yes" if url else "no"} | api_key_env {key or "none"} | models {len(spec.get("models") or {})}')
            if first is None and runtime['runtime'] == 'claude' and not url and not key:
                first = (entry, provider, 'claude login only (pre-approved)')
            if second is None and key in APPROVED:
                second = (entry, provider, f'api_key_env {key} (approved for Task 612)')
    picked = first or second
    print('CHOICE ' + (' '.join(picked) if picked else 'none'))
    return 0 if picked else 1


def walk(value, path: str = ''):
    """Yield (path, key, value) for every scalar of a nested document."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f'{path}.{key}') if isinstance(item, (dict, list)) else [(f'{path}.{key}', key, item)]
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f'{path}[{index}]')


def judge(raw_file: str, entry: str, provider: str, before: str, after: str) -> int:
    """CHECK Main's raw discover result: grouped by provider, key names only, nothing created."""
    import yaml

    text = open(raw_file, encoding='utf-8').read()
    try:
        result = json.loads(text)
    except ValueError:
        result = yaml.safe_load(text)
    if isinstance(result, dict) and isinstance(result.get('structuredContent'), dict):
        result = result['structuredContent']
    checks = []

    def check(name: str, ok: bool, detail: str = '') -> None:
        checks.append(ok)
        print(f"CHECK 612 Pr {name}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")

    discovery = (result or {}).get('discovery') if isinstance(result, dict) else None
    check('the raw result is a runtime_connections document with discovery', isinstance(discovery, dict),
          '' if isinstance(discovery, dict) else text[:200].replace('\n', ' '))
    discovery = discovery or {}
    check(f'discovery is for entry {entry}, provider {provider}',
          discovery.get('runtime_entry') == entry and discovery.get('provider') == provider,
          f"{discovery.get('runtime_entry')} / {discovery.get('provider')}")
    groups = discovery.get('groups')
    shape  = (isinstance(groups, list) and groups
              and all(isinstance(g, dict) and isinstance(g.get('provider'), str) and isinstance(g.get('models'), list)
                      for g in groups))
    sizes = [f"{g.get('provider')}: {len(g.get('models') or [])}" for g in groups or [] if isinstance(g, dict)]
    print(f"discovery status {discovery.get('status')} | groups {sizes} | models {len(discovery.get('models') or [])}")
    check('models are grouped by provider (groups: [{provider, models}], at least one model)',
          bool(shape) and sum(len(g['models']) for g in groups) > 0)
    check(f'the groups are the requested provider {provider}', bool(shape) and {g['provider'] for g in groups} == {provider})
    names = [(p, v) for p, k, v in walk(result) if k == 'api_key_env']
    print(f'api_key_env values in the result (names): {sorted({v for _, v in names if v})}')
    check('every api_key_env is a variable NAME', all(v is None or (isinstance(v, str) and NAME.match(v)) for _, v in names))
    leaks = [p for p, k, v in walk(result)
             if isinstance(v, str) and v and (SECRET.search(v) or (KEYLIKE.search(str(k)) and k != 'api_key_env'))]
    check('no field holds a credential-like value (only key names)', not leaks, ', '.join(leaks[:5]))
    print(f'records before P: {before} | after Pr: {after}')
    check('no Agent, child Session or member Session was created (record counts unchanged)', before == after)
    return 0 if all(checks) else 1


if __name__ == '__main__':
    if sys.argv[1] == 'choose':
        sys.exit(choose())
    sys.exit(judge(*sys.argv[2:7]))
