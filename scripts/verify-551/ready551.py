"""Task 551 00: judge one host's one-line READY from the host's OWN record, not from the model's reply.

  python -I ready551.py <claude|codex|pi> <output file> <expected model> [<expected provider>]
  python -I ready551.py dsh <dsh --json output> <expected model> - <DSH sessions root> <copy dir> <dump-config file>

claude: stream-json `system/init` record: `model` and `apiKeySource`.
codex:  `codex exec` human output (stdout+stderr): the header lines `model:` and `provider:`.
pi:     `pi --mode json` events: every string under a `model`/`modelId` key and every `provider` value.
dsh:    the `--json` stream has no model key (Main's run 2: session/status/thinking/text/final), so DSH's own session
        log for the stream's sessionId is read (read only; copied to <copy dir>). If no DSH record names a model, the
        model DSH resolved from its profile (`--dump-config`, agent-default-model) is printed and judged instead:
        a documented limit, not a failure, as long as DSH answered.
Prints the actual model, its source, the reply (marked self-report) and `READY-551 <host>: PASS|FAIL`; exit 0 = PASS.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Claude Code's init apiKeySource: 'none' = no API key; the CLI used its own login (claude.ai OAuth subscription).
# Any other value names the API key source (for example ANTHROPIC_API_KEY or apiKeyHelper).
API_KEY_SOURCE = {'none': 'none = no API key: Claude Code logged in with its OAuth (claude.ai subscription) login'}


def events(text: str) -> list:
    found = []
    for line in text.splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def main() -> int:
    host, path, expected = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    provider_expected = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != '-' else None
    text = path.read_text(errors='replace') if path.is_file() else ''
    reply = next((line.strip() for line in reversed(text.splitlines()) if 'READY-551' in line), '(none)')
    models: list[str] = []
    providers: list[str] = []
    extra = ''
    if host == 'claude':
        records = events(text)
        init = next((r for r in records if isinstance(r, dict) and r.get('subtype') == 'init'), {})
        result = next((r for r in records if isinstance(r, dict) and r.get('type') == 'result'), {})
        models = [init['model']] if isinstance(init.get('model'), str) else []
        source = str(init.get('apiKeySource'))
        extra = f" | login source (init apiKeySource): {API_KEY_SOURCE.get(source, source + ' = API key source')}"
        reply = str(result.get('result', '(none)')).strip().replace('\n', ' ')[:160]
        where = 'stream-json system/init model'
    elif host == 'codex':
        plain = re.sub(r'\x1b\[[0-9;]*m', '', text)
        models = re.findall(r'^model:\s*(\S+)', plain, re.M)
        providers = re.findall(r'^provider:\s*(\S+)', plain, re.M)
        where = "codex exec header 'model:' line"
    else:
        records = events(text)
        sources = [('pi --mode json events' if host == 'pi' else 'dsh --json events', records)]
        checked = [sources[0][0]]
        if host == 'dsh':
            # DSH's own session log for this run's sessionId (read only, copied as evidence):
            # <sessions root>/<projectKey(cwd)>/<id>/<generation log>, dsh-session-persistence-jsonl.
            session = next((node['sessionId'] for record in records for node in walk(record)
                            if isinstance(node.get('sessionId'), str)), None)
            root, copy = Path(sys.argv[5]), Path(sys.argv[6])
            files = sorted(root.glob(f'*/{session}/*')) if session else []
            checked.append(f"DSH session log {root}/*/{session or '<no sessionId in the stream>'}/* "
                           f"({len(files)} file(s))")
            copy.mkdir(parents=True, exist_ok=True)
            for file in files:
                if not file.is_file():
                    continue
                data = file.read_bytes()
                (copy / file.name).write_bytes(data)
                if file.suffix == '.gz':
                    import gzip
                    data = gzip.decompress(data)
                elif file.suffix not in ('.jsonl', '.json', ''):
                    checked.append(f'{file.name}: compressed {file.suffix}, not read')
                    continue
                sources.append((f'DSH session log {file}', events(data.decode('utf-8', 'replace'))))
        for _name, found in sources:
            for record in found:
                for node in walk(record):
                    for key in ('model', 'modelId'):
                        if isinstance(node.get(key), str):
                            models.append(node[key])
                    if isinstance(node.get('provider'), str):
                        providers.append(node['provider'])
        where = '; '.join(checked) + ' (model/modelId/provider keys)'
        if host == 'dsh' and not models:
            # Documented limit (Leader 551): no DSH record names the model; show the explicit selection.
            config = Path(sys.argv[7]).read_text(errors='replace') if len(sys.argv) > 7 and Path(sys.argv[7]).is_file() else ''
            match = re.search(r'- id: agent-default-model\n(?:  .*\n)*?    model: (\S+)', config)
            answered = any(isinstance(r, dict) and r.get('type') == 'final' for r in records) or 'READY-551' in text
            print(f"dsh: actual model NOT RECORDED BY DSH (checked: {where})")
            print(f"dsh: model selected explicitly: {match.group(1) if match else 'not found'} "
                  f"(from `dsh --profile headless --dump-config`, entry agent-default-model; no --model argv)")
            print(f"dsh: reply (self-report, not judged): {reply[:200]}")
            ok = answered and match is not None and match.group(1) == expected
            print(f"READY-551 dsh: {'PASS (documented limit: DSH records no model; judged from its resolved config)' if ok else 'FAIL'}"
                  f" (expected {expected}; answered: {answered})")
            return 0 if ok else 1
    models = sorted(set(models))
    providers = sorted(set(providers))
    ok = expected in models and (provider_expected is None or provider_expected in providers or not providers)
    if host == 'pi' and provider_expected is not None:
        ok = ok and provider_expected in providers
    print(f"{host}: actual model {models or 'NOT RECORDED'}{' provider ' + str(providers) if providers else ''} "
          f"(from {where}){extra}")
    print(f"{host}: reply (self-report, not judged): {reply[:200]}")
    print(f"READY-551 {host}: {'PASS' if ok else 'FAIL'} (expected {provider_expected + '/' if provider_expected else ''}{expected})")
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5, 8):
        print(__doc__)
        sys.exit(2)
    sys.exit(main())
