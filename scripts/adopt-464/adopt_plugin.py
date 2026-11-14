"""GraphTraj-side helpers of steps.zsh; run with -I under a venv holding the new wheels.

  regen <project> <claude> <target directory>
      Write only the plugin part of adoption_material into <target>.
  entries <project> <claude> <production python> <out directory>
      Print, writing nothing in the project, what `configuration --write` (419: a merge
      that keeps every key it does not own) would make of .mcp.json, settings.local.json
      and config.json, plus the removal of the two GRAPHTRAJ_CLAUDE_HOST_* names the
      renamed plugin no longer reads. Each predicted file goes to <out directory>.
  apply <project> <out directory>
      Write each predicted file that differs from the project's, with graftling's own
      write_adoption (the same merge, applied to the predicted content), then compare.
  readcheck <project> <state clone>
      Read every Session archive, the configuration and roles, and the Task graph of a clone.
"""
import json
from pathlib import Path
import sys

PLUGIN = '.claude/skills/graphtraj-claude-host'
CONFIG_KEYS = {'root', 'cwd', 'claude', 'channel_file'}
# The 0.2.4 plugin read these; graftling's host_context.mjs reads only GRAFTLING_CLAUDE_HOST_*.
OLD_ENV = ('GRAPHTRAJ_CLAUDE_HOST_PYTHON', 'GRAPHTRAJ_CLAUDE_HOST_CONFIG')
ENTRY_FILES = ('.mcp.json', '.claude/settings.local.json', '.graphtraj/claude-host/config.json')


def regen(project: str, claude: str, target: str) -> int:
    from graphtraj.runtimes.claude.host import adoption_material
    from graftling.claude.plugin import write_adoption

    root = Path(project).resolve()
    prefix = str(root / PLUGIN) + '/'
    material = adoption_material(root, Path(claude))
    chosen = {str(Path(target) / path[len(prefix):]): content
              for path, content in material.items() if path.startswith(prefix)}
    others = sorted(set(material) - {path for path in material if path.startswith(prefix)})
    if len(chosen) != 3 or len(others) != 3:
        print(f'STOP: expected 3 plugin and 3 other files, got {sorted(chosen)} and {others}')
        return 1
    write_adoption(chosen)
    print('written:', sorted(chosen))
    print('not written here:', others)
    return 0


def hide(value: object) -> object:
    value = json.loads(json.dumps(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in key.lower() for word in ('key', 'token', 'secret', 'password', 'credential')) \
                    and isinstance(item, str):
                value[key] = '<hidden>'
            else:
                value[key] = hide(item)
    elif isinstance(value, list):
        value = [hide(item) for item in value]
    return value


def flat(value: object, prefix: str = '') -> dict[str, object]:
    if isinstance(value, dict) and value:
        found = {}
        for key, item in value.items():
            found.update(flat(item, f'{prefix}.{key}' if prefix else key))
        return found
    return {prefix: value}


def entries(project: str, claude: str, python: str, out: str) -> int:
    from graphtraj.runtimes.claude.host import adoption_material
    from graftling.claude.plugin import _existing_document, _merged

    root = Path(project).resolve()
    # This scratch venv is not the one production will serve from.
    sys.executable = python
    material = adoption_material(root, Path(claude))
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    code = 0
    for name in ENTRY_FILES:
        path = root / name
        current = _existing_document(path)
        predicted = _merged(current, material[path.as_posix()])
        if name == '.claude/settings.local.json':
            for key in OLD_ENV:
                predicted.get('env', {}).pop(key, None)
        (target / name.replace('/', '__')).write_text(json.dumps(predicted, indent=2) + '\n', encoding='utf-8')
        before, after = flat(hide(current or {})), flat(hide(predicted))
        changed = sorted(key for key in before.keys() | after.keys() if before.get(key, '<absent>') != after.get(key, '<absent>'))
        print(f'{"SAME   " if not changed else "CHANGES"} {name}')
        for key in changed:
            print(f'    {key}: before={json.dumps(before.get(key, "<absent>"), ensure_ascii=False)}'
                  f' after={json.dumps(after.get(key, "<absent>"), ensure_ascii=False)}')
        if name == '.mcp.json':
            print('    agents.env kept:', sorted((predicted['mcpServers']['agents'].get('env') or {})),
                  '| other servers (names):', sorted(set(predicted['mcpServers']) - {'agents'}))
        if name == '.graphtraj/claude-host/config.json' and set(predicted) != CONFIG_KEYS:
            print(f'    STOP: the host accepts exactly {sorted(CONFIG_KEYS)}, prediction has {sorted(predicted)}')
            code = 1
        if name == '.claude/settings.local.json':
            env = predicted.get('env', {})
            if not all(env.get(key) for key in ('GRAFTLING_CLAUDE_HOST_PYTHON', 'GRAFTLING_CLAUDE_HOST_CONFIG')):
                print('    STOP: prediction lacks GRAFTLING_CLAUDE_HOST_PYTHON/CONFIG')
                code = 1
    print(f'predictions written to {target}')
    return code


def apply(project: str, out: str) -> int:
    from graftling.claude.plugin import write_adoption

    root = Path(project).resolve()
    code = 0
    for name in ENTRY_FILES:
        path = root / name
        predicted = json.loads((Path(out) / name.replace('/', '__')).read_text(encoding='utf-8'))
        current = json.loads(path.read_text(encoding='utf-8'))
        if current == predicted:
            print(f'UNCHANGED {name} (bytes kept)')
            continue
        # write_adoption merges into the existing file; the predicted document holds every key,
        # and the two removed names are dropped from the merge result before writing.
        write_adoption({str(path): predicted})
        written = json.loads(path.read_text(encoding='utf-8'))
        if name == '.claude/settings.local.json':
            for key in OLD_ENV:
                if key in written.get('env', {}):
                    written['env'].pop(key)
                    path.write_text(json.dumps(written, indent=2) + '\n', encoding='utf-8')
        now = json.loads(path.read_text(encoding='utf-8'))
        ok = now == predicted
        print(f'{"WRITTEN-AS-VALIDATED" if ok else "WRITTEN-DIFFERENT"} {name}')
        code |= not ok
    return int(code)


def readcheck(project: str, clone: str) -> int:
    from graftling.sessions.archive import read_session
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.graph.task_graph import read_graph
    from graphtraj.interfaces.agents import swarm_root

    root = Path(project)
    failures = 0
    counts: dict[str, int] = {}
    sessions = swarm_root(root) / 'sessions'
    for path in sorted(sessions.glob('*/session.jsonl')):
        with path.open(encoding='utf-8') as stream:
            version = str(json.loads(next(stream)).get('header', {}).get('version'))
        counts[version] = counts.get(version, 0) + 1
        try:
            read_session(path)
        except Exception as error:
            failures += 1
            print(f'READ-FAIL {path.parent.name} version={version}: {type(error).__name__}: {error}')
    print(f'read_session by file version: {counts}; failures={failures}')
    configuration = load_project_configuration(root)
    print('configuration loaded; state:', configuration.state)
    roles = load_project_roles(configuration.harness_root)
    print('roles loaded: presets =', len(roles.presets), 'roots =', len(roles.roots))
    graph = read_graph(Path(clone), view='full')
    print('task graph of the clone: tasks =', len(graph['tasks']))
    return 1 if failures else 0


OPERATIONS = {'regen': regen, 'entries': entries, 'apply': apply, 'readcheck': readcheck}
sys.exit(OPERATIONS[sys.argv[1]](*sys.argv[2:]))
