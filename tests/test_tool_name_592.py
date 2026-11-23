"""GraphTraj offers ``subagents`` and ``tasks``, never the old ``agents`` tool or feature (592).

graftling 0.9.0 renamed its tool to ``subagents`` (graftling Task 591), and with
it GraphTraj's gateway feature. The guard below fails on any production line that
names ``agents`` as a quoted literal or inside a native tool name, or shows an
old human-facing label, unless the line is a listed look-alike: names spelled
``agents`` that are not the tool (result keys, data paths, an old server key,
Codex's and DSH's own keys, migration of old records, recorded history).
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from graftling.tool import TOOL_NAME

ROOT = Path(__file__).resolve().parents[1]

# A quoted 'agents', "agents" or `agents` (not RST ``agents`` prose), or the old
# name inside a native tool name or plugin server prefix.
OLD_NAME = re.compile(r"(?<![`'\"])(['\"`])agents\1(?![`'\"])|__agents\b|_agents__")
# The result key {"agents": [...]} and the data paths control/agents, live/agents.
RESULT_KEY_OR_PATH = re.compile(
    r"""(['"])agents\1\s*:(?!\s*$)|\[(['"])agents\2\]|\.get\((['"])agents\3|/ (['"])agents\4|\((['"])control\5, (['"])agents\6\)""")
# Human-facing labels and messages that named the tool or one of its actions.
OLD_LABEL = re.compile(r"\bagents (·|→|host\b|review|notice|context|tool\b|entry|feature)"
                       r"|(?<![-\w])agents-call\b|\[agents\b|'agents: |agents/connectivity-check"
                       r"|(?<![-\w.])agents (needs|access|status|send|create|wait|requests|reply|resume|interrupt"
                       r"|retire)\b|read-only agents\b")

# (file relative to the repository root, a fragment of the allowed line). Each
# entry must still match a line.
ALLOWED = [
    # The .mcp.json server key configuration --write wrote before 514, removed on re-run.
    ('src/graphtraj/runtimes/claude/host.py', "OLD_SERVER = 'agents'"),
    ('README.md', 'an `agents` entry that starts this host'),
    ('README.md', 'any other `agents` entry stays'),
    # Pi still displays Sessions whose server key was agents (before 514).
    ('src/graphtraj/runtimes/pi/extension.mjs', "displayServers: ['graphtraj', 'agents']"),
    ('src/graphtraj/runtimes/pi/extension.mjs', "'graftling', 'graphtraj', 'agents']"),
    # The notice event label.
    ('src/graphtraj/interfaces/agents.py', "'source': 'agents'"),
    # Codex's own configuration key, not GraphTraj's tool.
    ('src/graphtraj/runtimes/codex/codex_adapter.py', '("agents", self.agents)'),
    # DSH's own agents service.
    ('src/graphtraj/runtimes/dsh/tool.mjs', "inject = ['tools', 'shellEnv', 'sessionQuery', 'agents']"),
    # Migration recognises the names old DSH tool configuration used.
    ('src/graphtraj/workspace/agent_migration.py', "in {None, '', 'graphtraj', 'agents', 'tasks'}"),
    ('src/graphtraj/workspace/agent_migration.py', "in {'graphtraj', 'agents', 'tasks'}"),
    # The README's history: the old name, the graftling 0.7.0 row, and Task 580's observation.
    ('README.md', '(named `agents` before'),
    ('README.md', 'row started no agents host'),
    ('README.md', 'the continuity claim is written and `mcp__graphtraj__agents`'),
    ('README.md', 'Two agents hosts and two `agents` tools'),
    ('README.md', '`mcp__graftling__agents` next to `mcp__graphtraj__agents`'),
    ('README.md', '`mcp__graftling__agents` is recorded only under'),
    ('README.md', "GraphTraj's `agents` and `tasks` do not list it"),
    # A count of Agents in the desktop footer, not the tool.
    ('desktop/src/Activity.tsx', '.agents.length} agents ·'),
]


def production_files() -> list[Path]:
    """Shipped sources, manifests, Skills, manuals, README and the desktop UI; not history."""
    files = [ROOT / 'pyproject.toml', ROOT / 'README.md']
    for base, suffixes in (('src/graphtraj', {'.py', '.mjs', '.json', '.yml', '.toml', '.md'}),
                           ('skills', {'.md'}), ('plugins', {'.md', '.json'}), ('manuals', {'.md'}),
                           ('desktop/src', {'.ts', '.tsx'}), ('desktop/electron', {'.ts'})):
        for path in sorted((ROOT / base).rglob('*')):
            if (path.is_file() and not path.is_symlink() and path.suffix in suffixes
                    and not {'__pycache__', 'node_modules'} & set(path.parts)):
                files.append(path)
    return files


def flagged(line: str) -> bool:
    """Whether ``line`` shows an old label or names agents other than as a result key or path."""
    return bool(OLD_LABEL.search(line) or OLD_NAME.search(RESULT_KEY_OR_PATH.sub('', line)))


def old_lines() -> list[tuple[str, int, str]]:
    """Return ``(file, line number, line)`` for each line naming the old tool, feature or label."""
    found = []
    for path in production_files():
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if flagged(line):
                found.append((path.relative_to(ROOT).as_posix(), number, line.strip()))
    return found


def test_no_production_line_names_the_old_tool_or_feature() -> None:
    """A half rename fails here: only the listed look-alikes keep ``agents``."""
    unexpected = [hit for hit in old_lines()
                  if not any(hit[0] == path and fragment in hit[2] for path, fragment in ALLOWED)]
    assert unexpected == []


def test_every_allowed_look_alike_is_still_there() -> None:
    """The allow-list holds no entry that no longer matches, so it cannot grow stale."""
    hits = old_lines()
    stale = [(path, fragment) for path, fragment in ALLOWED
             if not any(hit[0] == path and fragment in hit[2] for hit in hits)]
    assert stale == []


def test_the_guard_sees_the_forms_a_half_rename_leaves() -> None:
    """The patterns catch each form the old name took, and not result keys, paths or the new name."""
    for line in ("for name in ('agents', 'tasks')", "if tool == 'agents':",
                 "request.get('feature') == 'agents'", "{'task_graph', 'agents'}",
                 "envelope = {'action': 'execute', 'feature': 'agents'}", 'Use MCP `agents` / `tasks`',
                 '`mcp__graphtraj__agents`', "'The agents tool, where you have it'",
                 "'agents host stopped'", "'[agents · a → b]'",
                 '"agents needs a verified caller: a managed Session"', "'Native helpers have read-only agents access.'",
                 "'the current hierarchy view is agents status.'", '"plain messages use agents send without one."',
                 "'(agents interrupt), which retains a terminal-confirmation receipt.'"):
        assert flagged(line), line
    for line in ("for name in ('subagents', 'tasks')", "document['agents']", "{'agents': nodes}",
                 'response = {"agents": []}', "status.get('agents', [])", "swarm / 'control' / 'agents'",
                 "relative.parts[:2] == ('control', 'agents')", 'the ``agents`` core', '.agents-control',
                 "'agents-review'", '/agents-context', "'subagents host stopped'",
                 "'subagents needs a verified caller'", "'read-only subagents access'", "'subagents status'",
                 "'Use migrate-agents --snapshot first'", "'Standalone agents config cannot replace'"):
        assert not flagged(line), line


def test_the_mcp_server_lists_subagents_and_tasks_only() -> None:
    """graphtraj-mcp and the Claude host offer exactly subagents and tasks."""
    from graphtraj.interfaces.mcp import _tool_documents
    from graphtraj.runtimes.claude.mcp import descriptors

    assert TOOL_NAME == 'subagents'
    assert [tool['name'] for tool in _tool_documents()] == ['subagents', 'tasks']
    assert [tool['name'] for tool in descriptors()] == ['subagents', 'tasks']


def test_the_old_tool_name_is_unknown_to_graphtraj_mcp() -> None:
    """A call to agents is refused as an unknown tool."""
    from graphtraj.interfaces.mcp import _tool_call_response

    response = _tool_call_response(1, {'name': 'agents', 'arguments': {'action': 'discover'}})
    assert response['error']['message'] == 'Unknown tool: agents'


def test_the_gateway_feature_is_subagents() -> None:
    """The tasks registry carries graftling's own name, so tasks refuses subagents and hides it."""
    from graphtraj.interfaces.tools import TOOLS

    assert 'subagents' in TOOLS and 'agents' not in TOOLS


def test_the_claude_hook_copy_names_subagents_and_tasks(tmp_path: Path) -> None:
    """graftling's writer produces GraphTraj's hook copy with [TOOL, "tasks"] and TOOL = subagents."""
    from graphtraj.runtimes.claude.host import adoption_material

    material = adoption_material(tmp_path, Path('/claude'))
    hook = next(text for path, text in material.items() if path.endswith('hooks/host_context.mjs'))
    lines = hook.splitlines()
    assert 'const TOOL = "subagents";' in lines and 'const TOOLS = [TOOL, "tasks"];' in lines
    assert not OLD_NAME.search(hook.replace('`agents-context`', ''))
    manifest = next(text for path, text in material.items() if path.endswith('.claude-plugin/plugin.json'))
    text = manifest if isinstance(manifest, str) else json.dumps(manifest)
    assert 'subagents and tasks' in text


def test_role_system_text_names_subagents() -> None:
    """Every child role's system text names the subagents tool."""
    import inspect

    from graphtraj.configuration import role_definitions

    source = inspect.getsource(role_definitions)
    assert 'The `subagents` tool, where you have' in source
    assert 'The `agents` tool' not in source


def test_skills_and_manuals_say_subagents() -> None:
    """The Skill and the delivery guide tell the model to use MCP subagents / tasks."""
    for relative in ('skills/graphtraj/SKILL.md', 'plugins/graphtraj/skills/graphtraj/SKILL.md',
                     'manuals/task-delivery/guide.md', 'manuals/task-delivery/references/command-inputs.md'):
        text = (ROOT / relative).read_text(encoding='utf-8')
        assert 'MCP `subagents` / `tasks`' in text, relative
