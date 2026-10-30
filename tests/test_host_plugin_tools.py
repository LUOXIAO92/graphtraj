"""A host plugin knows agents alone unless a package declares its own tool."""
import json
from pathlib import Path
import subprocess

import pytest

from agent_swarm import AgentsError, AgentsResult
from agent_swarm.claude import NativeCalls, claude_host_plugin
from agent_swarm.claude.host import adoption_material as agents_material
from graphtraj.runtimes.claude.host import NativeCalls as GraphTrajCalls, adoption_material as graphtraj_material

SESSION = '11111111-1111-4111-8111-111111111111'


def module_of(material: dict) -> str:
    """Return the written module from one plugin's files."""
    return next(text for path, text in material.items() if path.endswith('hooks/host_context.mjs'))


HARNESS = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const contexts = [], log = [];
const host = {
 session: {id: async () => 'first', cwd: async () => '/work'},
 command: {register: async () => {}},
 tool: {list: async () => [{name: 'mcp__agents__agents'}, {name: 'mcp__agents__notes'}, {name: 'mcp__agents__tasks'}]},
 env: {get: async key => key.endsWith('PYTHON') ? '/python' : '/config'},
 process: {run: async (argv, options) => {contexts.push(JSON.parse(options.stdin)); return {exitCode: 0, stdout: '{}', stderr: ''};}},
 ui: {log: async line => log.push(line)},
 clock: {setTimeout() {}},
};
'''


def run_module(tmp_path: Path, text: str, program: str) -> None:
    """Run ``program`` in node against one written module."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(text)
    result = subprocess.run(['node', '--input-type=module', '-e', HARNESS + program, module.as_uri()],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_a_standalone_plugin_associates_and_lists_only_agents(tmp_path: Path) -> None:
    """Nothing in the standalone plugin names or handles the tasks tool."""
    text = module_of(agents_material(tmp_path, Path('/claude')))
    assert 'tasks' not in text
    assert text == Path('src/agent_swarm/claude/host_context.mjs').read_text()
    run_module(tmp_path, text, r'''
assert.deepEqual([...handlers.keys()].filter(key => key.startsWith('tool.')).sort(),
                 ['tool.call:mcp__agents__agents', 'tool.check:mcp__agents__agents']);
await handlers.get('command.run')(host);
assert.deepEqual(log.filter(line => line.startsWith('MCP ')), ['MCP agents registered']);
''')


def test_a_declared_tool_gets_association_and_cleanup_without_an_exchange(tmp_path: Path) -> None:
    """Any package's tool is handled as tasks was: associated, ended, never rendered as an exchange."""
    text = module_of(claude_host_plugin(tmp_path, 'package-host', 'A package.', ['notes']))
    assert 'tasks' not in text
    run_module(tmp_path, text, r'''
const request = {action: 'execute', feature: 'note', arguments: {message: 'hidden'}};
await handlers.get('tool.check:mcp__agents__notes')(host, {input: request}, async () => ({decision: 'allow'}));
assert.deepEqual(contexts.at(-1), {operation: 'prepare', tool: 'notes', session: 'first', cwd: '/work', agent: null, request});
const denied = await handlers.get('tool.check:mcp__agents__notes')(host, {agentId: 'native', input: request}, async () => ({decision: 'allow'}));
assert.equal(denied.decision, 'deny');
const answer = {result: [{type: 'text', text: JSON.stringify({agent: 'agent-1', execution: 'e', result: {}})}]};
assert.equal(await handlers.get('tool.call:mcp__agents__notes')(host, {...request}, async () => answer), answer);
assert.deepEqual(contexts.at(-1), {operation: 'end', tool: 'notes', request, session: 'first'});
assert.deepEqual(log, []);
await handlers.get('command.run')(host);
assert.deepEqual(log.filter(line => line.startsWith('MCP ')), ['MCP agents registered', 'MCP notes registered']);
''')


def test_only_the_declared_tools_are_written(tmp_path: Path) -> None:
    """GraphTraj declares tasks like any other package; agents alone declares nothing."""
    assert 'const TOOLS = ["agents"];' in module_of(agents_material(tmp_path, Path('/claude')))
    assert 'const TOOLS = ["agents", "tasks"];' in module_of(graphtraj_material(tmp_path, Path('/claude')))
    files = claude_host_plugin(tmp_path / 'plugin', 'n', 'd')
    assert sorted(files) == [str(tmp_path / 'plugin' / name) for name in (
        '.claude-plugin/plugin.json', 'hooks/hooks.json', 'hooks/host_context.mjs')]
    json.dumps({path: value for path, value in files.items() if not isinstance(value, str)})


@pytest.mark.parametrize('tools', [['agents'], ['notes', 'notes'], ['a b'], [''], ["x'];"], [3]])
def test_a_tool_the_module_cannot_carry_is_refused(tmp_path: Path, tools: list) -> None:
    """A declared name reaches JavaScript and an MCP tool name, so it stays plain."""
    with pytest.raises(ValueError):
        claude_host_plugin(tmp_path, 'n', 'd', tools)


def prepare_document(tool: str, cwd: Path) -> dict:
    """One native preparation for ``tool``."""
    return {'operation': 'prepare', 'tool': tool, 'session': SESSION, 'cwd': str(cwd), 'agent': None, 'request': {}}


def test_a_standalone_host_refuses_an_undeclared_tool(tmp_path: Path) -> None:
    """A standalone association names agents only, however the plugin was written."""
    host = NativeCalls(lambda session, cwd: None, tmp_path)
    with pytest.raises(AgentsError) as refused:
        host.context(prepare_document('tasks', tmp_path))
    assert (refused.value.code, refused.value.message) == ('invalid-input', 'Expected the agents entry.')
    assert host.context(prepare_document('agents', tmp_path)) == {'prepared': True}


def test_a_declared_tool_is_associated_and_served(tmp_path: Path) -> None:
    """The host serves a declared tool with the same per-call association."""
    calls = []

    def make_call(session: str, cwd: Path):
        def call(tool: str, request: dict) -> AgentsResult:
            calls.append((session, tool))
            return AgentsResult({})
        return call

    host = NativeCalls(make_call, tmp_path, tools=['notes'])
    host.context(prepare_document('notes', tmp_path))
    host.call({}, 'notes')
    assert calls == [(SESSION, 'notes')]


def test_graphtraj_declares_tasks_to_its_host(tmp_path: Path) -> None:
    """GraphTraj's association keeps both of its entries and no other."""
    host = GraphTrajCalls(lambda session, cwd: None, tmp_path)
    assert host.context(prepare_document('tasks', tmp_path)) == {'prepared': True}
    with pytest.raises(AgentsError, match='agents or tasks'):
        host.context(prepare_document('notes', tmp_path))
