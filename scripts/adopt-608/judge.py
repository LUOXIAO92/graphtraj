"""Task 608 verdicts from the hosts' own records (run with python3 -I; stdlib only). Names only, never values.

usage:
  judge.py snap <data root>                       record ids now under <root>/control/agents
  judge.py selfenv                                the credential-class variable NAMES this python3 sees
  judge.py pids <data root> <snap>                runtime_pid values of the records not in <snap>
  judge.py envnames <out file>                    stdin: `ps -E -ww -o command= -p <pid>`; writes the variable NAMES only
  judge.py pick <listing.json> <candidates file>  the opencode listing -> ordered "provider model" candidates
  judge.py pi <session dir> <output> <root> <snap> <tool> <word> <connection> <provider> <model> <env dir> <credential>
      a real Pi Main created one DSH child: the tool calls and results (Pi Session file), the one new record (host
      pi-native, runtime dsh, completed with <word>, <connection>, <model>), the provider and model in the child's native
      DSH trace, and the credential-class variable names of the child's DSH process (sampled into <env dir>), which must
      be exactly <credential>.

Every verdict line starts PASS or FAIL; the exit status is 0 only when every line is PASS.
"""
import json, os, re, sys
from pathlib import Path

FAILED = []
# graftling child_env.is_credential_name, restated for a stdlib-only judge (a '_'-separated part ending in a marker).
PART = re.compile(r'(?:KEY|TOKEN|SECRET|SECRETS|PASSWORD|CREDENTIAL|CREDENTIALS)$')


def credential(name):
    upper = name.upper()
    return not re.fullmatch(r'GIT_CONFIG_KEY_[0-9]+', upper) and any(PART.search(p) for p in upper.split('_'))


def check(ok, message):
    print(('PASS: ' if ok else 'FAIL: ') + message)
    if not ok:
        FAILED.append(message)


def records(root):
    found = {}
    for path in sorted((Path(root) / 'control' / 'agents').glob('*.json')):
        try:
            found[path.stem] = json.loads(path.read_text())
        except (OSError, ValueError):
            found[path.stem] = {}
    return found


def values(node, key):
    """Every value of ``key`` anywhere in a JSON document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                yield v
            yield from values(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from values(v, key)


def pairs(node):
    """Every (provider, model) named together in one JSON object."""
    if isinstance(node, dict):
        if isinstance(node.get('provider'), str) and isinstance(node.get('model'), str):
            yield node['provider'], node['model']
        for v in node.values():
            yield from pairs(v)
    elif isinstance(node, list):
        for v in node:
            yield from pairs(v)


def pids(root, snap):
    """The runtime_pid of every new record's executions, one per line."""
    before = set(Path(snap).read_text().split()) if Path(snap).is_file() else set()
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == 'runtime_pid' and isinstance(v, int):
                    found.add(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for agent, record in records(root).items():
        if agent not in before:
            walk(record)
    print('\n'.join(map(str, sorted(found))))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(text_of(c.get('text') if isinstance(c, dict) and 'text' in c else
                                c.get('content') if isinstance(c, dict) else c) for c in content)
    return '' if content is None else str(content)


def envnames(out):
    text = sys.stdin.read()
    names = sorted(set(re.findall(r'(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=', text)))
    Path(out).write_text('\n'.join(names) + '\n')
    print(f'{len(names)} names; credential-class: {[n for n in names if credential(n)]}')


def pick(listing, out):
    found = json.loads(Path(listing).read_text())
    chosen = []
    for provider in ('opencode-go', 'opencode'):
        ids = [m['id'] for m in (found.get(provider) or {}).get('models') or [] if m.get('provider') == provider]
        glm = sorted((i for i in ids if i.lower().startswith('glm')), key=lambda i: (i != 'glm-5.3', i))
        chosen += [(provider, i) for i in glm[:2]]
    if not chosen:
        for provider in ('opencode-go', 'opencode'):
            ids = [m['id'] for m in (found.get(provider) or {}).get('models') or [] if 'deepseek' not in m['id']]
            chosen += [(provider, i) for i in ids[:1]]
    Path(out).write_text(''.join(f'{p} {m}\n' for p, m in chosen))
    print(f'candidates (in probe order): {chosen}')
    return 0 if chosen else 1


def pi(sessions, output, root, snap, tool, word, connection, provider, model, envdir, expected):
    files = sorted(Path(sessions).rglob('*.jsonl'))
    check(len(files) == 1, f'one Pi Session file in {sessions}: {[f.name for f in files]}')
    calls, results, providers = [], [], set()
    for f in files:
        for raw in f.read_text(errors='replace').splitlines():
            try:
                m = json.loads(raw).get('message')
            except (ValueError, AttributeError):
                continue
            if not isinstance(m, dict):
                continue
            if m.get('role') == 'assistant':
                providers.add(m.get('provider'))
                calls += [b.get('name') for b in m.get('content') or []
                          if isinstance(b, dict) and b.get('type') == 'toolCall']
            if m.get('role') == 'toolResult':
                results.append((m.get('toolName'), bool(m.get('isError')), text_of(m.get('content'))))
    print(f'Main assistant providers: {sorted(map(str, providers))}; tool calls: {calls}')
    check(providers == {'deepseek'}, 'deepseek is the only provider of the Main\'s answers')
    check(calls.count(tool) >= 2, f'the Main called {tool} at least twice (create, wait): {calls.count(tool)}')
    errors = [t[:300] for name, error, t in results if name == tool and error]
    check(not errors, f'no {tool} result is an error: {errors}')
    for name, error, text in results:
        print(f'  result of {name} (error {error}): {text[:300]!r}')
    check('Extension error' not in Path(output).read_text(errors='replace'), 'no Extension error in the Main\'s output')

    before = set(Path(snap).read_text().split()) if Path(snap).is_file() else set()
    new = {a: r for a, r in records(root).items() if a not in before}
    check(len(new) == 1, f'exactly one new child record under {root}/control/agents: {sorted(new)}')
    for agent, record in new.items():
        last = (record.get('executions') or [{}])[-1]
        chosen = record.get('selection') or {}
        message = last.get('last_message') or ''
        print(f'{agent}: host {(record.get("creator") or {}).get("host")}, runtime {record.get("runtime")}, '
              f'connection {chosen.get("connection")!r}, model {chosen.get("model")!r}, '
              f'providers in the record {sorted(set(values(record, "provider")))}')
        check((record.get('creator') or {}).get('host') == 'pi-native' and record.get('runtime') == 'dsh',
              f'{agent} is a dsh child of the Pi host')
        check(chosen.get('connection') == (connection or None), f'{agent} used connection {connection or None!r}')
        check(chosen.get('model') == model, f'{agent} model is {model!r}')
        check(last.get('outcome') == 'completed' and word in message.lower(),
              f'{agent} completed with {word!r}: outcome {last.get("outcome")}, error '
              f'{(last.get("error") or {}).get("code")}: {str((last.get("error") or {}).get("message"))[:300]!r}, '
              f'last_message {message[:80]!r}')
        check(any(agent in t for _, _, t in results), f'a tool result of the Main names {agent}')
        traces = [p for p in Path(root).rglob('trace.jsonl') if agent in str(p)]
        seen, named = set(), {'provider': set(), 'model': set()}
        for trace in traces:
            for raw in trace.resolve().read_text(errors='replace').splitlines():
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                seen |= set(pairs(event))
                for key in named:
                    named[key] |= set(values(event, key))
        print(f'native DSH trace: every provider value {sorted(named["provider"])}; every model value {sorted(named["model"])}')
        print(f'native DSH trace(s) {[str(t.resolve()) for t in traces]}: (provider, model) pairs {sorted(seen)}')
        check((provider, model) in seen, f'the native DSH trace names provider {provider!r} with model {model!r}')
        check(not [p for p in seen if p[0] != provider], f'the native DSH trace names no other provider')
        print(f'follow-up (paste): python3 -m json.tool {Path(root) / "control" / "agents" / (agent + ".json")}')
    samples = sorted(Path(envdir).glob('env-*.txt'))
    print(f'environment samples of the child DSH process (names only): {[s.name for s in samples]}')
    check(bool(samples), f'the child DSH process environment was sampled (see {envdir}/sampler.log if not)')
    for sample in samples:
        names = sample.read_text().split()
        found = sorted(n for n in names if credential(n))
        print(f'  {sample.name}: {len(names)} names; credential-class: {found}')
        check(found == [expected], f'{sample.name}: the only credential-class variable is {expected}')


def main(argv):
    if argv[:1] == ['snap'] and len(argv) == 2:
        print('\n'.join(records(argv[1])))
        return 0
    if argv[:1] == ['envnames'] and len(argv) == 2:
        envnames(argv[1])
        return 0
    if argv[:1] == ['selfenv'] and len(argv) == 1:
        print(' '.join(sorted(n for n in os.environ if credential(n))) or 'none')
        return 0
    if argv[:1] == ['pids'] and len(argv) == 3:
        pids(*argv[1:])
        return 0
    if argv[:1] == ['pick'] and len(argv) == 3:
        return pick(*argv[1:])
    if argv[:1] == ['pi'] and len(argv) == 12:
        pi(*argv[1:])
    else:
        print(__doc__)
        return 2
    print(f'judge: {"ALL PASS" if not FAILED else f"{len(FAILED)} FAIL"}')
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
