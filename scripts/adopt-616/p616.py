"""616 P/Pr/Mr helpers. Read only; prints names only, never a key value.

usage: <production>/bin/python -I p616.py expect <project root> <expectation json out>
       <any python> -I p616.py judge <raw result file> <expectation json> <counts before> <counts after>
       <any python> -I p616.py calls <label> <after epoch> <feature or -> <transcript>...

expect  With the INSTALLED graphtraj and graftling (production's own, after I):
        - the contract: graftling's ACTION_FIELDS['models'] (required and optional fields) and agents.py's models
          branch serving role_models(self.root, arguments["runtime"], arguments.get("provider")); prints ARGS, the
          exact inline arguments for Main's call;
        - the code reads only project roles and the user catalog: role_models, _candidates, _with_provider,
          load_project_roles, resolve_preset, resolve_connection and read_catalog start no process and use no network
          or discovery, and their only environment read is os.environ.get(variable) for a Runtime HOME path (never an
          api_key_env value). If not, LOGIN-OR-KEY: STOP (Main asks the user);
        - the user catalog through read_catalog: entries, runtimes, providers, whether a base_url is set, api_key_env
          names and model counts (names only);
        - role_models(<project root>, "claude") computed here: the groups and key names Main's call must answer.
judge   Main's raw result against that expectation: not an error; runtime claude, status available; grouped by
        provider (each model's provider is its group's, providers unique, groups == models); the same groups and
        api_key_env names as expected; every api_key_env a variable NAME; no credential-like string; counts unchanged.
calls   Main's transcript after <after epoch>: with a feature, an mcp__graphtraj__subagents execute of that feature
        answered without error (CHECK); always lists ToolSearch calls: `select:` of an mcp__graphtraj__ tool is
        Claude Code's deferred tool-schema load and is ALLOWED (614's lesson), shown as INFO; other ToolSearch
        queries are INFO too.
"""
import inspect
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ok_all: list[bool] = []
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
CRED = (re.compile(r'sk-[A-Za-z0-9_-]{8,}'), re.compile(r'(?i)bearer\s+\S{8,}'), re.compile(r'[A-Za-z0-9_+=-]{40,}'),
        re.compile(r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S{6,}'))
FORBIDDEN = ('subprocess', 'Popen', 'socket', 'urlopen', 'http.client', 'requests.', 'discover_models', 'getenv',
             'environ[')


def ck(name: str, ok: bool, detail: str = '') -> None:
    ok_all.append(ok)
    print(f"CHECK 616 {name}: {'PASS' if ok else 'FAIL'}{f' ({detail})' if detail else ''}")


def expect(root: str, out: str) -> int:
    import graftling
    import graphtraj
    from graftling.tool import ACTION_FIELDS
    from graphtraj.configuration import project_roles, runtime_connections
    from graphtraj.execution import agent_driver
    from graphtraj.interfaces import agents

    print(f'installed: graphtraj {Path(graphtraj.__file__).parent} | graftling {graftling.__version__}')
    required, optional = (sorted(x) for x in ACTION_FIELDS['models'])
    print(f"graftling ACTION_FIELDS['models']: required {required} optional {optional}")
    ck('P the installed contract: models requires runtime, offers provider', required == ['runtime'] and optional == ['provider'])
    branch = 'role_models(self.root, arguments["runtime"], arguments.get("provider"))'
    ck('P the installed agents.py models branch serves role_models(self.root, runtime, provider)',
       branch in inspect.getsource(agents))
    funcs = [agent_driver.role_models, agent_driver._candidates, agent_driver._with_provider,
             project_roles.load_project_roles, project_roles.resolve_preset,
             runtime_connections.resolve_connection, runtime_connections.read_catalog]
    found = []
    for func in funcs:
        source = inspect.getsource(func)
        found += [f'{func.__name__}: {t}' for t in FORBIDDEN if t in source]
        found += [f'{func.__name__}: {m}' for m in re.findall(r'os\.environ[^\n]{0,30}', source)
                  if not m.startswith('os.environ.get(variable)')]
    print(f'models code read: {", ".join(f.__name__ for f in funcs)} | process, network, discovery or other '
          f'environment reads: {found or "none"}')
    no_key = not found
    ck('P models reads only project roles and the user catalog (no process, network or key value)', no_key, str(found))
    print('LOGIN-OR-KEY ' + ('none: models reads files only; the call is carried by the running Main (Claude login, '
                             'approved)' if no_key else 'STOP: the code above may use a login or key; Main asks the user'))
    try:
        document, revision = runtime_connections.read_catalog()
        print(f'user catalog (names only; revision {revision[:12]}):')
        for entry, spec in sorted((document.get('runtimes') or {}).items()):
            for provider, p in sorted((spec.get('providers') or {}).items()):
                print(f"  {entry}: runtime {spec.get('runtime')} | provider {provider} | base_url "
                      f"{'set' if p.get('base_url') else 'none'} | api_key_env {p.get('api_key_env') or 'none'} | "
                      f"models {len(p.get('models') or {})}")
    except Exception as error:                          # noqa: BLE001 - shown, judged through role_models below
        print(f'user catalog: not read ({type(error).__name__}: {str(error)[:160]})')
    try:
        result = agent_driver.role_models(Path(root), 'claude')
    except Exception as error:                          # noqa: BLE001
        ck('P role_models(<Harness>, claude) answers here', False, f'{type(error).__name__}: {str(error)[:200]}')
        return 1
    groups = {str(g['provider']): sorted(m['configuration'] for m in g['models']) for g in result['groups']}
    keys = {m['configuration']: m['api_key_env'] for m in result['models']}
    print(f'expected groups (provider -> roles): {groups}')
    print(f'expected api_key_env names: {keys}')
    ck('P role_models(<Harness>, claude) lists at least one role', bool(result['models']), f"{len(result['models'])} roles")
    Path(out).write_text(json.dumps({'groups': groups, 'keys': keys}, sort_keys=True))
    print('ARGS {"runtime":"claude"}')
    return 0 if all(ok_all) else 1


def first_document(text: str):
    """The raw result: the whole text as JSON, else the first JSON object in it that holds a `groups` list."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for start in [m.start() for m in re.finditer(r'\{', text)]:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and ('groups' in json.dumps(value) or 'error' in value):
            return value
    return None


def strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from strings(k); yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, str):
        yield value


def judge(raw: str, expectation: str, before: str, after: str) -> int:
    text = Path(raw).read_text(errors='replace')
    doc = first_document(text)
    want = json.loads(Path(expectation).read_text())
    ck('Pr the raw result is a JSON document', isinstance(doc, dict), text[:120] if not isinstance(doc, dict) else '')
    doc = doc if isinstance(doc, dict) else {}
    result = doc.get('result') if isinstance(doc.get('result'), dict) else doc
    error = doc.get('error') or doc.get('is_error') or doc.get('isError')
    ck('Pr not an error', not error and 'groups' in result, json.dumps(error)[:200] if error else '')
    ck('Pr runtime claude, status available', result.get('runtime') == 'claude' and result.get('status') == 'available',
       f"{result.get('runtime')} {result.get('status')}")
    groups, models = result.get('groups') or [], result.get('models') or []
    providers = [g.get('provider') for g in groups]
    inner = [m for g in groups for m in g.get('models') or []]
    grouped = (len(providers) == len(set(map(str, providers))) and bool(groups)
               and all(m.get('provider') == g.get('provider') for g in groups for m in g.get('models') or [])
               and sorted(m.get('configuration') for m in inner) == sorted(m.get('configuration') for m in models))
    got = {str(g.get('provider')): sorted(m.get('configuration') for m in g.get('models') or []) for g in groups}
    keys = {m.get('configuration'): m.get('api_key_env') for m in models}
    print(f'result groups (provider -> roles): {got}')
    print(f'result api_key_env: {keys}')
    ck('Pr grouped by provider (unique providers; each model in its provider group; groups == models)', grouped)
    ck("Pr the same groups as P's role_models on the installed code", got == want['groups'], f"expected {want['groups']}")
    ck('Pr every api_key_env is a variable NAME (or none), as expected',
       all(v is None or NAME.match(str(v)) for v in keys.values()) and keys == want['keys'], f"expected {want['keys']}")
    hits = sorted({p.pattern for s in strings(doc) for p in CRED if p.search(s)})
    ck('Pr no credential-like value in the result', not hits, f'patterns hit: {hits}')
    print(f'counts at P: {before} | now: {after}')
    ck('Pr nothing created (Agent records, Session archives, member Sessions unchanged)', before == after and bool(before))
    return 0 if all(ok_all) else 1


def stamp(value) -> float | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return None


def calls(label: str, after: str, feature: str, paths: list[str]) -> int:
    split = float(after)
    uses, results = {}, {}
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        for line in p.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            when = stamp(record.get('timestamp'))
            content = ((record.get('message') or {}).get('content') if isinstance(record.get('message'), dict) else None) or []
            for item in content if isinstance(content, list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get('type') == 'tool_use' and item.get('id'):
                    uses.setdefault(item['id'], (item.get('name'), item.get('input') or {}, when))
                elif item.get('type') == 'tool_result' and item.get('tool_use_id'):
                    results[item['tool_use_id']] = item
    window = [(i, n, inp) for i, (n, inp, w) in uses.items() if w is not None and w > split]
    print(f'[{label}] tool calls after the split ({len(window)}): '
          f'{sorted({n for _, n, _ in window})}')
    for ident, name, inp in window:
        if name == 'ToolSearch':
            query = str(inp.get('query', ''))
            allowed = bool(re.fullmatch(r'select:mcp__graphtraj__(subagents|tasks)', query))
            print(f"INFO 616 [{label}] ToolSearch {json.dumps(inp)[:120]}: "
                  f"{'ALLOWED (Claude Code loads the deferred schema of the same mcp__graphtraj tool; 614)' if allowed else 'other query (information, not judged)'}")
    if feature == '-':
        return 0
    hits = [(i, inp) for i, n, inp in window if n == 'mcp__graphtraj__subagents'
            and inp.get('action') == 'execute' and inp.get('feature') == feature]
    answered = [i for i, _ in hits if i in results and results[i].get('is_error') is not True]
    for i, inp in hits:
        r = results.get(i)
        print(f"[{label}] mcp__graphtraj__subagents execute {feature} {json.dumps(inp.get('arguments'))}: "
              f"{'no result' if r is None else 'is_error ' + str(r.get('is_error') is True)}"
              f"{'' if inp.get('arguments') is not None else ' (arguments not inline)'}")
    ck(f'Pr Main called mcp__graphtraj__subagents execute {feature} after P, answered without error',
       bool(answered), f'{len(hits)} call(s), {len(answered)} without error')
    return 0 if all(ok_all) else 1


if __name__ == '__main__':
    mode, rest = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    if mode == 'expect' and len(rest) == 2:
        sys.exit(expect(*rest))
    if mode == 'judge' and len(rest) == 4:
        sys.exit(judge(*rest))
    if mode == 'calls' and len(rest) >= 3:
        sys.exit(calls(rest[0], rest[1], rest[2], rest[3:]))
    print(__doc__); sys.exit(2)
