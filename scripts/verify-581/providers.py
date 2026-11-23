"""Task 581: which provider, model and endpoint a Main or a child used, read from files on disk (names, ids and
host names only; never a credential value). DeepSeek is the only provider the user approved.

usage:
  providers.py scan <label> <dir>...       JSON/JSONL/YAML files under the dirs (no node_modules, no symlinks):
                                           provider/providerId values, model/modelId/resolved_model values,
                                           baseURL/base_url/baseUrl hosts and llm-* plugin ids (DSH's LLM plugins)
  providers.py child <root> <agent>        the agent's record (runtime, executions[].process.resolved_model and model)
                                           plus `scan` of <root>/native/<agent> (else <root>/native) (graftling composes a dsh child's own profile
                                           there with the llm-deepseek plugin, graftling dsh/execution.py)
In YAML (DSH profile patches) `provider:` is not read: there it is a tool plugin's process mode (spawn | fork).
PASS when something was found and every provider names deepseek, every endpoint host ends in deepseek.com, every
llm-* plugin is llm-deepseek and every model id names deepseek; FAIL otherwise (with the file of each finding).
Field names follow the real files: Pi Session messages carry provider/model (Task 584 Sessions), graftling records
carry executions[].process.resolved_model, DSH profile patches carry {'id': 'llm-deepseek', 'config': {'baseURL'}}.
"""
import json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse

PROVIDER_KEYS = {'provider', 'providerId', 'provider_id'}
MODEL_KEYS = {'model', 'modelId', 'model_id', 'resolved_model'}
URL_KEYS = {'baseURL', 'base_url', 'baseUrl'}
YAML_LINE = re.compile(r'^\s*-?\s*(provider|providerId|model|modelId|resolved_model|baseURL|base_url|baseUrl|id)\s*:\s*'
                       r'["\']?([^"\'\s#,}]+)')


def walk(value, found, where):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item:
                if key in PROVIDER_KEYS:
                    found.append(('provider', item, where))
                elif key in MODEL_KEYS:
                    found.append(('model', item, where))
                elif key in URL_KEYS:
                    found.append(('endpoint', urlparse(item).hostname or item, where))
                elif key == 'id' and item.startswith('llm-'):
                    found.append(('llm plugin', item, where))
            walk(item, found, where)
    elif isinstance(value, list):
        for item in value:
            walk(item, found, where)


def scan_file(path, found):
    if path.stat().st_size > 20_000_000:
        return
    text = path.read_text(errors='replace')
    if path.suffix in ('.yml', '.yaml'):
        for line in text.splitlines():
            m = YAML_LINE.match(line)
            if not m:
                continue
            key, value = m.groups()
            # In DSH profile/patch YAML a `provider:` is a tool plugin's process mode (dsh-tool-subagent and
            # dsh-workflow-ptc: spawn | fork; Main's real run, cordis.patch.yml), not an LLM provider. The LLM evidence
            # there is the llm-* plugin ids and any baseURL host. Providers come from JSON(L) Sessions and records.
            if key in PROVIDER_KEYS:
                continue
            kind = ('model' if key in MODEL_KEYS else
                    'endpoint' if key in URL_KEYS else 'llm plugin' if value.startswith('llm-') else None)
            if kind:
                found.append((kind, urlparse(value).hostname or value if kind == 'endpoint' else value, str(path)))
        return
    docs = []
    try:
        docs = [json.loads(text)]
    except ValueError:
        for line in text.splitlines():
            try:
                docs.append(json.loads(line))
            except ValueError:
                pass
    for doc in docs:
        walk(doc, found, str(path))


def scan_dirs(dirs, found):
    for d in dirs:
        for top, subdirs, files in os.walk(d):
            subdirs[:] = [s for s in subdirs if s != 'node_modules' and not os.path.islink(os.path.join(top, s))]
            for name in files:
                p = Path(top, name)
                if not p.is_symlink() and p.suffix in ('.json', '.jsonl', '.yml', '.yaml'):
                    try:
                        scan_file(p, found)
                    except OSError:
                        pass


def bad(kind, value):
    v = value.lower()
    if kind == 'provider':
        return 'deepseek' not in v
    if kind == 'endpoint':
        return not (v == 'api.deepseek.com' or v.endswith('.deepseek.com'))
    if kind == 'llm plugin':
        return v != 'llm-deepseek'
    return 'deepseek' not in v  # model


def verdict(label, found):
    summary = {}
    for kind, value, where in found:
        summary.setdefault((kind, value), where)
    for (kind, value), where in sorted(summary.items()):
        print(f'  {label}: {kind} {value}{"   <-- NOT DeepSeek" if bad(kind, value) else ""}  ({where})')
    wrong = sorted({f'{k} {v}' for (k, v) in summary if bad(k, v)})
    if not summary:
        print(f'FAIL: {label}: no provider, model, endpoint or llm plugin found on disk')
        return 1
    if wrong:
        print(f'FAIL: {label}: not DeepSeek: {wrong}')
        return 1
    print(f'PASS: {label}: ' + ', '.join(sorted({f"{k} {v}" for (k, v) in summary})))
    return 0


def child(root, agent):
    found = []
    path = Path(root, 'control', 'agents', f'{agent}.json')
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        print(f'FAIL: child {agent}: no record ({error})')
        return 1
    for execution in record.get('executions') or []:
        process = execution.get('process') or {}
        for key in ('resolved_model', 'model'):
            if isinstance(process.get(key), str):
                found.append(('model', process[key], str(path)))
    if isinstance(record.get('model'), str):
        found.append(('model', record['model'], str(path)))
    # Only this child's own native directory (<root>/native/<agent>/, as on the real host), so an earlier child's
    # files in the same data root never decide this child's verdict; the whole native/ only if that is missing.
    own = Path(root, 'native', agent)
    scan_dirs([own if own.is_dir() else Path(root, 'native')], found)
    print(f'  child {agent}: runtime {record.get("runtime")}; native files read from {own if own.is_dir() else Path(root, "native")}')
    return verdict(f'child {agent} (runtime {record.get("runtime")})', found)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['scan'] and len(a) >= 3:
        found = []
        scan_dirs(a[2:], found)
        sys.exit(verdict(a[1], found))
    if a[:1] == ['child'] and len(a) == 3:
        sys.exit(child(a[1], a[2]))
    print(__doc__)
    sys.exit(2)
