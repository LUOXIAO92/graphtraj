"""Running ``configuration --write`` again keeps the user's settings (419).

Each test runs the real command of both Claude Code host entries as a
subprocess, unless it checks a function directly. No model, network or Claude.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import agent_swarm


SOURCE = Path(agent_swarm.__file__).resolve().parents[1]


@dataclass(frozen=True)
class Entry:
    """One host entry's command and the paths it writes."""

    module: str
    config: str
    plugin: str
    description: str
    tools: tuple[str, ...]
    # What this entry's first install adds to the host configuration.
    written: tuple[tuple[str, object], ...]
    # Keys a user added to the host configuration.
    added: tuple[tuple[str, object], ...]

    def default_root(self, project: Path) -> Path:
        """The data root a first install writes."""
        return (project / self.config).parent if self.module.startswith('agent_swarm') else project


ENTRIES = {
    'agents': Entry('agent_swarm.claude.host', '.agents-control/claude-host.json', 'agents-claude-host',
                    'Native Claude context for independent agents MCP.', ('agents',), (('settings', {}),),
                    (('settings', {'model': 'chosen'}),
                     ('runtimes', {'pi': {'provider': 'deepseek', 'model': 'deepseek-flash'}}))),
    'graphtraj': Entry('graphtraj.runtimes.claude.host', '.graphtraj/claude-host/config.json',
                       'graphtraj-claude-host', 'GraphTraj Main host context for the agents and tasks MCP entries.',
                       ('agents', 'tasks'), (), (('note', 'mine'),)),
}


@pytest.fixture(params=list(ENTRIES))
def entry(request: pytest.FixtureRequest) -> Entry:
    """The host entry under test."""
    return ENTRIES[request.param]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An existing project directory, with its real path."""
    directory = tmp_path.resolve() / 'project'
    directory.mkdir()
    return directory


def command(entry: Entry, project: Path, *flags: str, claude: str = '/new/claude') -> subprocess.CompletedProcess:
    """Run the real ``configuration`` command against the source under test."""
    return subprocess.run(
        [sys.executable, '-m', entry.module, 'configuration', '--project', str(project), '--claude', claude, *flags],
        cwd=project.parent, capture_output=True, text=True, timeout=60,
        env={**os.environ, 'PYTHONPATH': str(SOURCE) + os.pathsep + os.environ.get('PYTHONPATH', '')})


def configure(entry: Entry, project: Path, *flags: str) -> subprocess.CompletedProcess:
    """Run the command and require that it succeeded."""
    done = command(entry, project, *flags)
    assert done.returncode == 0, done.stderr
    return done


def write_json(path: Path, document: object) -> None:
    """Place one existing JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding='utf-8')


def read_json(path: Path) -> dict:
    """Read one written JSON file."""
    return json.loads(path.read_text(encoding='utf-8'))


def snapshot(directory: Path) -> dict[str, bytes | None]:
    """Every path under ``directory``, with each file's exact bytes."""
    return {str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
            for path in sorted(directory.rglob('*'))}


def host_arguments(entry: Entry, project: Path) -> list[str]:
    """The ``args`` the command owns in ``.mcp.json``."""
    return ['-m', entry.module, 'serve', '--config', str(project / entry.config)]


def test_rerun_updates_only_what_the_command_owns(entry: Entry, project: Path, tmp_path: Path) -> None:
    """A configured project keeps the user's settings, gets the owned fields, and a second run changes nothing."""
    data = tmp_path.resolve() / 'data'
    write_json(project / '.mcp.json', {
        'top': 'level',
        'mcpServers': {
            'other': {'command': 'other', 'args': ['x']},
            'agents': {'command': '/stale/python', 'args': ['stale', 'args', 'many'], 'type': 'stdio',
                       'env': {'LANGUAGE': 'zh'}},
        },
    })
    write_json(project / '.claude/settings.local.json', {
        'env': {'KEEP': '1', 'GRAPHTRAJ_CLAUDE_HOST_PYTHON': '/stale/python'},
        'permissions': {'allow': ['Bash(ls)']},
    })
    write_json(project / entry.config, {
        'root': str(data), 'cwd': str(project), 'claude': '/stale/claude',
        'channel_file': str(data / 'channel.json'), **dict(entry.added),
    })

    done = configure(entry, project, '--write')

    assert str(project / '.mcp.json') in json.loads(done.stdout)
    assert read_json(project / '.mcp.json') == {
        'top': 'level',
        'mcpServers': {
            'other': {'command': 'other', 'args': ['x']},
            'agents': {'command': sys.executable, 'args': host_arguments(entry, project), 'type': 'stdio',
                       'env': {'LANGUAGE': 'zh'}},
        },
    }
    assert read_json(project / '.claude/settings.local.json') == {
        'env': {'KEEP': '1', 'GRAPHTRAJ_CLAUDE_HOST_PYTHON': sys.executable,
                'GRAPHTRAJ_CLAUDE_HOST_CONFIG': str(project / entry.config)},
        'permissions': {'allow': ['Bash(ls)']},
    }
    assert read_json(project / entry.config) == {
        'root': str(data), 'cwd': str(project), 'claude': '/new/claude',
        'channel_file': str(data / 'channel.json'), **dict(entry.added),
    }

    written = snapshot(project)
    configure(entry, project, '--write')
    assert snapshot(project) == written


def test_printing_writes_nothing_and_shows_the_kept_paths(entry: Entry, project: Path, tmp_path: Path) -> None:
    """Without --write nothing changes; the host configuration shows what a write keeps."""
    data = tmp_path.resolve() / 'data'
    write_json(project / '.mcp.json', {'mcpServers': {'agents': {'env': {'LANGUAGE': 'zh'}}}})
    write_json(project / entry.config, {'root': str(data), 'cwd': str(project), 'claude': '/stale/claude',
                                        'channel_file': str(data / 'channel.json')})
    before = snapshot(project)

    printed = json.loads(configure(entry, project).stdout)

    assert snapshot(project) == before
    host = printed[str(project / entry.config)]
    assert (host['root'], host['channel_file']) == (str(data), str(data / 'channel.json'))
    # Otherwise it prints the command's own fragment, as before.
    assert printed[str(project / '.mcp.json')] == {'mcpServers': {'agents': {
        'command': sys.executable, 'args': host_arguments(entry, project)}}}


@pytest.mark.parametrize('recorded, expected', [
    ('{old}/custom', '{new}/custom'),
    ('{old}/custom/channel.json', '{new}/custom/channel.json'),
    ('{outside}/data', '{outside}/data'),
    # A name that only starts like the old project, and a path that leaves it, are outside.
    ('{old}-sibling/data', '{old}-sibling/data'),
    ('{old}/../elsewhere/data', '{old}/../elsewhere/data'),
])
def test_moved_project_carries_only_paths_inside_it(
    entry: Entry, project: Path, tmp_path: Path, recorded: str, expected: str,
) -> None:
    """A path inside the recorded old cwd follows the project; any other stays exactly as written."""
    places = {'old': str(tmp_path.resolve() / 'old-place'), 'new': str(project),
              'outside': str(tmp_path.resolve() / 'outside')}
    write_json(project / entry.config, {'root': recorded.format(**places), 'cwd': places['old'],
                                        'claude': '/stale/claude', 'channel_file': recorded.format(**places)})

    configure(entry, project, '--write')

    host = read_json(project / entry.config)
    assert host['cwd'] == str(project)
    assert (host['root'], host['channel_file']) == (expected.format(**places), expected.format(**places))


def test_moved_project_default_paths_follow_it(entry: Entry, project: Path, tmp_path: Path) -> None:
    """A first install's paths, moved with the project, point into its new location."""
    old = tmp_path.resolve() / 'old-place'
    write_json(project / entry.config, {
        'root': str(entry.default_root(old)), 'cwd': str(old), 'claude': '/stale/claude',
        'channel_file': str((old / entry.config).parent / 'live/channel.json'),
    })

    configure(entry, project, '--write')

    host = read_json(project / entry.config)
    assert host['root'] == str(entry.default_root(project))
    assert host['channel_file'] == str((project / entry.config).parent / 'live/channel.json')


def test_unmoved_project_keeps_a_custom_path_inside_it(entry: Entry, project: Path) -> None:
    """With the same cwd a path inside the project stays where the user put it."""
    write_json(project / entry.config, {'root': str(project / 'custom'), 'cwd': str(project), 'claude': '/stale/claude',
                                        'channel_file': str(project / 'custom/channel.json')})

    configure(entry, project, '--write')

    host = read_json(project / entry.config)
    assert (host['root'], host['channel_file']) == (str(project / 'custom'), str(project / 'custom/channel.json'))


@pytest.mark.parametrize('document', [
    {},
    {'root': 3, 'channel_file': None},
])
def test_missing_or_non_string_paths_get_the_default(entry: Entry, project: Path, document: dict) -> None:
    """Only an existing string is kept."""
    write_json(project / entry.config, document)

    configure(entry, project, '--write')

    host = read_json(project / entry.config)
    assert host['root'] == str(entry.default_root(project))
    assert host['channel_file'] == str((project / entry.config).parent / 'live/channel.json')


def test_first_install_content_is_unchanged(entry: Entry, project: Path) -> None:
    """With no existing files the command writes exactly these bytes."""
    configure(entry, project, '--write')

    config = project / entry.config
    module = (SOURCE / 'agent_swarm/claude/host_context.mjs').read_text(encoding='utf-8')
    plugin = f'.claude/skills/{entry.plugin}'
    expected = {
        entry.config: json.dumps({
            'root': str(entry.default_root(project)), 'cwd': str(project), 'claude': '/new/claude',
            'channel_file': str(config.parent / 'live/channel.json'), **dict(entry.written),
        }, indent=2) + '\n',
        '.mcp.json': json.dumps({'mcpServers': {'agents': {
            'command': sys.executable, 'args': host_arguments(entry, project)}}}, indent=2) + '\n',
        '.claude/settings.local.json': json.dumps({'env': {
            'GRAPHTRAJ_CLAUDE_HOST_PYTHON': sys.executable,
            'GRAPHTRAJ_CLAUDE_HOST_CONFIG': str(config)}}, indent=2) + '\n',
        f'{plugin}/.claude-plugin/plugin.json': json.dumps(
            {'name': entry.plugin, 'version': '1', 'description': entry.description}, indent=2) + '\n',
        f'{plugin}/hooks/hooks.json': json.dumps({'modules': ['./host_context.mjs']}, indent=2) + '\n',
        f'{plugin}/hooks/host_context.mjs': module.replace(
            'const TOOLS = ["agents"];', f'const TOOLS = {json.dumps(list(entry.tools))};'),
    }
    written = {path: content.decode('utf-8') for path, content in snapshot(project).items() if content is not None}
    assert written == expected


BAD_FILES = {
    'mcp': lambda entry: '.mcp.json',
    'settings': lambda entry: '.claude/settings.local.json',
    'manifest': lambda entry: f'.claude/skills/{entry.plugin}/.claude-plugin/plugin.json',
    'config': lambda entry: entry.config,
}


@pytest.mark.parametrize('content', ['{not json', '[1, 2]', '"text"'], ids=['malformed', 'list', 'string'])
@pytest.mark.parametrize('which', list(BAD_FILES))
def test_bad_existing_file_is_named_and_nothing_is_written(entry: Entry, project: Path, which: str, content: str) -> None:
    """The file is refused by path; no other file was written first, and it is not replaced."""
    bad = project / BAD_FILES[which](entry)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(content, encoding='utf-8')
    before = snapshot(project)

    done = command(entry, project, '--write')

    assert done.returncode != 0
    last = done.stderr.strip().splitlines()[-1]
    assert last.startswith('ValueError: ') and str(bad) in last, done.stderr
    assert snapshot(project) == before


def test_printing_refuses_a_bad_host_configuration(entry: Entry, project: Path) -> None:
    """The kept paths cannot be shown from a bad configuration, and it stays as it is."""
    bad = project / entry.config
    bad.parent.mkdir(parents=True)
    bad.write_text('{not json', encoding='utf-8')

    done = command(entry, project)

    assert done.returncode != 0 and str(bad) in done.stderr.strip().splitlines()[-1], done.stderr
    assert bad.read_text(encoding='utf-8') == '{not json'


@pytest.mark.parametrize('module', [entry.module for entry in ENTRIES.values()])
def test_write_adoption_computes_every_document_first(module: str, tmp_path: Path) -> None:
    """Both hosts share the public function, which writes nothing when a later file is bad."""
    write_adoption = importlib.import_module(module).write_adoption
    assert write_adoption is importlib.import_module('agent_swarm.claude').write_adoption
    good, text, bad = tmp_path / 'new/good.json', tmp_path / 'new/text.mjs', tmp_path / 'bad.json'
    bad.write_text('{not json', encoding='utf-8')

    with pytest.raises(ValueError, match=str(bad)):
        write_adoption({str(good): {'a': 1}, str(text): 'text', str(bad): {'b': 2}})

    assert not (tmp_path / 'new').exists()
    assert bad.read_text(encoding='utf-8') == '{not json'


@pytest.mark.parametrize('existing, update, merged', [
    ({'a': {'b': {'c': 1, 'd': 2}}}, {'a': {'b': {'c': 3}}}, {'a': {'b': {'c': 3, 'd': 2}}}),
    ({'a': [1, 2], 'b': 1}, {'a': [3]}, {'a': [3], 'b': 1}),
    ({'a': {'keep': 1}}, {'a': 'scalar'}, {'a': 'scalar'}),
    ({'a': 'scalar'}, {'a': {'new': 1}}, {'a': {'new': 1}}),
    ({'a': {'keep': 1}}, {'a': {}}, {'a': {'keep': 1}}),
])
def test_merge_is_recursive_over_objects(tmp_path: Path, existing: dict, update: dict, merged: dict) -> None:
    """Objects merge at any depth; a list or scalar from the command replaces the value."""
    from agent_swarm.claude import write_adoption

    target = tmp_path / 'document.json'
    target.write_text(json.dumps(existing), encoding='utf-8')
    write_adoption({str(target): update})
    assert read_json(target) == merged
