"""GraphTraj-side helpers of steps.zsh; run with -I under a venv holding the new wheels.

  regen <project> <claude> <target directory>
      Write only the plugin part of adoption_material into <target>. `configuration --write`
      would replace mcpServers.agents whole and lose its env, so it is not used.
  material <project> <claude> <production python>
      Print, writing nothing, how the rest of adoption_material differs from production.
  readcheck <project> <state clone>
      Read every Session archive, the configuration and roles, and the Task graph of a clone.
"""
import json
from pathlib import Path
import sys

PLUGIN = '.claude/skills/graphtraj-claude-host'
CONFIG_KEYS = {'root', 'cwd', 'claude', 'channel_file'}


def regen(project: str, claude: str, target: str) -> int:
    from graphtraj.runtimes.claude.host import adoption_material, write_adoption

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
    print('not written:', others)
    return 0


def material(project: str, claude: str, python: str) -> int:
    from graphtraj.runtimes.claude.host import adoption_material

    root = Path(project).resolve()
    # This scratch venv is not the one production will serve from.
    sys.executable = python
    documents = adoption_material(root, Path(claude))
    code = 0

    config = root / '.graphtraj/claude-host/config.json'
    current = json.loads(config.read_text(encoding='utf-8'))
    print(f'config.json keys exactly {sorted(CONFIG_KEYS)}: {set(current) == CONFIG_KEYS}')
    code |= set(current) != CONFIG_KEYS
    written = documents[str(config)]
    print('config.json values equal the full material:',
          {key: current.get(key) == written.get(key) for key in sorted(written)})

    mcp = json.loads((root / '.mcp.json').read_text(encoding='utf-8'))['mcpServers']
    written = documents[str(root / '.mcp.json')]['mcpServers']['agents']
    print('.mcp.json agents entry now      :', json.dumps(hide(mcp.get('agents')), ensure_ascii=False))
    print('.mcp.json agents entry in full  :', json.dumps(written, ensure_ascii=False))
    print('.mcp.json other entries (names) :', sorted(set(mcp) - {'agents'}))
    print('--write would drop these keys of the agents entry:', sorted(set(mcp.get('agents', {})) - set(written)))

    settings = json.loads((root / '.claude/settings.local.json').read_text(encoding='utf-8'))
    written = documents[str(root / '.claude/settings.local.json')]['env']
    env = settings.get('env', {})
    for key in sorted(written):
        print(f'settings.local.json env {key}: now={env.get(key)} full={written[key]} '
              f'{"same" if env.get(key) == written[key] else "DIFFERS"}')
        code |= env.get(key) != written[key]
    print('settings.local.json other top-level keys (names):', sorted(set(settings) - {'env'}))
    print('settings.local.json other env keys (count only):', len(set(env) - set(written)))
    return int(code)


def hide(entry: object) -> object:
    entry = json.loads(json.dumps(entry))
    if isinstance(entry, dict):
        for key in entry.get('env') or {}:
            if any(word in key.lower() for word in ('key', 'token', 'secret', 'password')):
                entry['env'][key] = '<hidden>'
    return entry


def readcheck(project: str, clone: str) -> int:
    from agent_swarm.sessions.archive import read_session
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


OPERATIONS = {'regen': regen, 'material': material, 'readcheck': readcheck}
sys.exit(OPERATIONS[sys.argv[1]](*sys.argv[2:]))
