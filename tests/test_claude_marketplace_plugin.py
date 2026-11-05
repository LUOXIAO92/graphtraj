"""The Claude Code marketplace package of graftling (418).

Stand-ins only: a fake ``claude`` and fake Pythons, Node for the mod. No model,
network or real Claude Code; the real install is the scripts/realhost-418 steps.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import graftling
from graftling.claude import host
from graftling.claude.plugin import MARKETPLACE_DIRECTORY, marketplace_module


REPOSITORY = Path(__file__).resolve().parents[1]
PLUGIN = MARKETPLACE_DIRECTORY
LAUNCHER = PLUGIN / 'bin' / 'graftling-host'
SOURCE = Path(graftling.__file__).resolve().parents[1]


def test_checked_in_module_is_generated_from_host_context() -> None:
    """Any difference from host_context.mjs, beyond naming the plugin, fails here."""
    written = (PLUGIN / 'hooks' / 'host_context.mjs').read_text(encoding='utf-8')
    assert written == marketplace_module(), (
        'Regenerate: python -c "from graftling.claude.plugin import write_marketplace_module; '
        'write_marketplace_module()"')
    assert 'const PLUGIN = "graftling";' in written


def test_manifests_name_graftling_and_bake_in_no_path() -> None:
    """The marketplace points at the plugin; the server uses only Claude Code's path variables."""
    marketplace = json.loads((REPOSITORY / '.claude-plugin' / 'marketplace.json').read_text())
    entry, = marketplace['plugins']
    assert (marketplace['name'], entry['name']) == ('graftling', 'graftling')
    assert (REPOSITORY / entry['source']).resolve() == PLUGIN.resolve()
    manifest = json.loads((PLUGIN / '.claude-plugin' / 'plugin.json').read_text())
    assert (manifest['name'], manifest['version']) == ('graftling', graftling.__version__)
    server = manifest['mcpServers']['agents']
    assert server == {'command': 'sh', 'args': ['${CLAUDE_PLUGIN_ROOT}/bin/graftling-host', 'serve',
                                                '--project', '${CLAUDE_PROJECT_DIR}']}
    assert json.loads((PLUGIN / 'hooks' / 'hooks.json').read_text()) == {'modules': ['./host_context.mjs']}
    for path in PLUGIN.rglob('*'):
        if path.is_file():
            assert '/Users/' not in path.read_text(encoding='utf-8'), path


@pytest.fixture
def claude_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in ``claude`` first on PATH."""
    directory = tmp_path / 'bin'
    directory.mkdir()
    claude = directory / 'claude'
    claude.write_text('#!/bin/sh\n')
    claude.chmod(0o755)
    monkeypatch.setenv('PATH', f'{directory}{os.pathsep}{os.environ["PATH"]}')
    return claude


def test_plugin_configuration_is_created_then_keeps_user_keys(tmp_path: Path, claude_on_path: Path) -> None:
    """No configuration --write: the default is created; a re-run keeps what the user set."""
    project = tmp_path / 'project'
    project.mkdir()
    config = host.plugin_configuration(project)
    assert config == project.resolve() / '.agents-control' / 'claude-host.json'
    first = json.loads(config.read_text())
    assert first == {'root': str(config.parent), 'cwd': str(project.resolve()), 'claude': str(claude_on_path),
                     'channel_file': str(config.parent / 'live' / 'channel.json'), 'settings': {}}
    chosen = {**first, 'claude': '/chosen/claude', 'settings': {'model': 'chosen'}, 'runtimes': {'pi': {}}}
    config.write_text(json.dumps(chosen))
    host.plugin_configuration(project)
    assert json.loads(config.read_text()) == chosen


def test_plugin_host_stands_aside_for_configuration_write_material(tmp_path: Path, claude_on_path: Path) -> None:
    """A project whose .mcp.json starts the host keeps that host; the plugin refuses, naming the fix."""
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.mcp.json').write_text(json.dumps({'mcpServers': {'agents': {
        'command': sys.executable, 'args': ['-m', 'graftling.claude.host', 'serve', '--config', 'x']}}}))
    with pytest.raises(graftling.AgentsError) as refused:
        host.plugin_configuration(project)
    assert refused.value.code == 'host-busy'
    assert 'claude plugin disable graftling@graftling' in str(refused.value)
    assert not (project / '.agents-control').exists()


def run_host(*arguments: str, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    """Run the host module from this checkout, as the plugin's launcher would."""
    environment = {**os.environ, 'PYTHONPATH': str(SOURCE)}
    return subprocess.run([sys.executable, '-m', 'graftling.claude.host', *arguments], cwd=cwd,
                          env=environment, capture_output=True, text=True, timeout=30, **kwargs)


def test_plugin_serve_without_prior_configuration_writes_it_and_logs_its_refusal(
        tmp_path: Path, claude_on_path: Path) -> None:
    """serve --project creates the configuration; started by pytest, not Claude, it refuses into host.log."""
    project = tmp_path / 'project'
    project.mkdir()
    result = run_host('serve', '--project', str(project), cwd=project, input='')
    assert result.returncode == 0, result.stderr
    assert (project / '.agents-control' / 'claude-host.json').is_file()
    log = (project / '.agents-control' / 'host.log').read_text()
    assert 'must be launched directly by the selected Claude CLI' in log


def test_context_finds_the_configuration_above_the_session_cwd(tmp_path: Path, claude_on_path: Path) -> None:
    """--project-from walks up; with none, it says the host has not started and where to look."""
    project = tmp_path / 'project'
    (project / 'sub').mkdir(parents=True)
    missing = run_host('context', '--project-from', str(project / 'sub'), cwd=project, input='{}')
    assert missing.returncode == 1
    assert 'graftling plugin: no .agents-control/claude-host.json' in missing.stderr
    host.plugin_configuration(project)
    found = run_host('context', '--project-from', str(project / 'sub'), cwd=project, input='{}')
    assert found.returncode == 1
    assert 'agents host for this project is not running' in found.stderr


def fake_python(path: Path, body: str) -> Path:
    """A stand-in Python: ``body`` is the shell run for every invocation."""
    path.write_text(f'#!/bin/sh\n{body}\n')
    path.chmod(0o755)
    return path


@pytest.mark.parametrize('python, named', [
    ('missing', 'GRAFTLING_PYTHON='),
    ('without', 'GRAFTLING_PYTHON='),
])
def test_launcher_names_what_to_install_when_python_cannot_run_graftling(
        tmp_path: Path, python: str, named: str) -> None:
    """A Python that is missing or lacks graftling: stderr and host.log say what to install and set."""
    project = tmp_path / 'project'
    project.mkdir()
    executable = (tmp_path / 'nowhere' / 'python' if python == 'missing' else fake_python(
        tmp_path / 'python', "echo \"ModuleNotFoundError: No module named 'graftling'\" >&2; exit 1"))
    result = subprocess.run(['sh', str(LAUNCHER), 'serve', '--project', str(project)],
                            env={**os.environ, 'GRAFTLING_PYTHON': str(executable)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    for text in (result.stderr, (project / '.agents-control' / 'host.log').read_text()):
        assert 'graftling plugin: the agents host did not start' in text
        assert f'{named}{executable}' in text
        assert 'Install the graftling wheel' in text and 'set GRAFTLING_PYTHON' in text
    if python == 'without':
        assert "No module named 'graftling'" in result.stderr


def test_launcher_execs_the_found_python_with_the_host(tmp_path: Path) -> None:
    """GRAFTLING_PYTHON first; the host replaces the launcher with the same arguments."""
    record = tmp_path / 'argv'
    executable = fake_python(tmp_path / 'python',
                             f'[ "$1" = -c ] && exit 0; echo "$$ $*" > {record}; exit 0')
    result = subprocess.run(['sh', '-c', f'echo $$; exec sh {LAUNCHER} serve --project /p'],
                            env={**os.environ, 'GRAFTLING_PYTHON': str(executable)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    pid, arguments = record.read_text().strip().split(' ', 1)
    assert pid == result.stdout.strip(), 'exec keeps the process Claude Code started'
    assert arguments == '-m graftling.claude.host serve --project /p'


MOD = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const scenario = process.argv[2];
const handlers = new Map();
register((name, matcher, fn) => {
 const key = fn && matcher.tool ? `${name}:${matcher.tool}` : name;
 handlers.set(key, fn ?? matcher); return {catch() {}};
});
const env = scenario === 'inert' ? {GRAFTLING_CLAUDE_HOST_CONFIG: '/project/config'}
  : scenario === 'default' ? {} : {GRAFTLING_PYTHON: '/venv/python'};
const runs = [], log = [], registrations = [];
const host = {
 session: {id: async () => 'main', cwd: async () => '/project/sub'},
 command: {register: async entry => registrations.push(entry)},
 tool: {list: async () => [{name: 'mcp__plugin_graftling_agents__agents'}]},
 env: {get: async key => env[key]},
 process: {run: async (argv, options) => {
   runs.push(argv);
   if (scenario === 'without') return {exitCode: 1, stdout: '', stderr: "ModuleNotFoundError: No module named 'graftling'"};
   return argv[1] === '-c' ? {exitCode: 0, stdout: '0.5.0\n', stderr: ''} : {exitCode: 0, stdout: '{}', stderr: ''};
 }},
 clock: {setTimeout: () => {}},
 ui: {log: value => log.push(value)},
};
assert.ok(handlers.has('tool.check:mcp__plugin_graftling_agents__agents'));
assert.ok(!handlers.has('tool.check:mcp__agents__agents'));
await handlers.get('session.start')(host, {}, async () => 'started');
const check = handlers.get('tool.check:mcp__plugin_graftling_agents__agents');
const decided = await check(host, {input: {action: 'discover'}}, async () => ({decision: 'allow'}));
if (scenario === 'inert') {
 assert.equal(registrations.length, 0);
 assert.deepEqual(decided, {decision: 'allow'});
 assert.equal(runs.length, 0);
} else if (scenario === 'without') {
 assert.equal(decided.decision, 'deny');
 assert.match(decided.reason, /graftling plugin: \/venv\/python cannot import graftling\. Install the graftling wheel/);
 await handlers.get('command.run')(host);
 assert.ok(log.some(line => /cannot import graftling.*set GRAFTLING_PYTHON/.test(line)));
} else {
 const python = scenario === 'default' ? 'python3' : '/venv/python';
 assert.deepEqual(decided, {decision: 'allow'});
 assert.deepEqual(runs[0], [python, '-m', 'graftling.claude.host', 'context', '--project-from', '/project/sub']);
 await handlers.get('command.run')(host);
 assert.ok(log.includes(`graftling 0.5.0 at ${python}`), log.join('\n'));
 assert.ok(log.includes('MCP agents registered'));
}
'''


@pytest.mark.parametrize('scenario', ['set', 'default', 'without', 'inert'])
def test_plugin_mod_uses_plugin_tool_names_and_its_python(tmp_path: Path, scenario: str) -> None:
    """Plugin tool names; GRAFTLING_PYTHON else python3; an explicit missing message; inert beside material."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(marketplace_module())
    result = subprocess.run(['node', '--input-type=module', '-e', MOD, module.as_uri(), scenario],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
