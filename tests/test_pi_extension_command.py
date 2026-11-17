"""The Pi extension starts its own installation's commands without them on PATH."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from graftling.sessions.archive import JsonlSessionStore, archive_path
from graphtraj.configuration.project_configuration import default_configuration_content
import graftling
GRAFTLING = Path(graftling.__file__).resolve().parent  # the installed graftling package

SOURCE = Path(__file__).resolve().parents[1] / 'src'

DRIVER = '''
import { pathToFileURL } from 'node:url';
const extension = await import(pathToFileURL(process.argv[1]).href);
const header = {type: 'session', version: 3, id: process.env.GRAFTLING_NATIVE_SESSION,
  cwd: process.cwd(), timestamp: 0};
const ctx = {cwd: process.cwd(), sessionManager: {getHeader: () => header, getEntries: () => []}};
const report = {};
for (const [name, step] of [
  ['entry', () => extension.nativeEntry(ctx, {}, {event: 'session_start', reason: 'startup', header, entries: []})],
  ['collection', async () => {
    const collector = await extension.startCollection(ctx, {});
    await collector.write({type: 'message_update', message: {}, assistantMessageEvent:
      {type: 'text_delta', contentIndex: 0, delta: 'from installation', partial: {}}});
    await collector.close();
    return 'closed';
  }],
  ['mcp', () => extension.installedCommand('graphtraj-mcp')],
]) {
  try { report[name] = {value: await step()}; } catch (error) { report[name] = {error: error.message}; }
}
console.log(JSON.stringify(report));
'''


def installation(root: Path, scripts: bool) -> Path:
    """Copy both extensions into a POSIX prefix layout; return the GraphTraj extension.

    With ``scripts`` the prefix ``bin`` holds ``graphtraj-session`` and
    ``graphtraj-mcp`` wrappers that record their use before running GraphTraj.
    """
    site = root / 'lib/python3.13/site-packages'
    extension = site / 'graphtraj/runtimes/pi/extension.mjs'
    for target, origin in ((extension, SOURCE / 'graphtraj/runtimes/pi/extension.mjs'),
                           (site / 'graphtraj/runtimes/graftling.mjs', SOURCE / 'graphtraj/runtimes/graftling.mjs'),
                           (site / 'graftling/pi/extension.mjs', GRAFTLING / 'pi/extension.mjs')):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)

    if scripts:
        (root / 'bin').mkdir()
        for name, module in (('graphtraj-session', 'graphtraj.runtimes.native_entry'),
                             ('graphtraj-mcp', 'graphtraj.interfaces.mcp')):
            command = root / 'bin' / name
            command.write_text(f'#!{sys.executable}\nimport pathlib, sys\n'
                               f'with open({str(root / "used")!r}, "a") as used: used.write({name!r} + "\\n")\n'
                               f'from {module} import main\nmain()\n')
            command.chmod(0o755)
    return extension


def drive(project: Path, extension: Path) -> dict:
    """Run the extension's entry, collection and MCP lookup with PATH holding only Node."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the actual extension carrier')
    only_node = project / 'only-node'
    only_node.mkdir()
    (only_node / 'node').symlink_to(node)
    environment = {
        'PATH': str(only_node), 'HOME': os.environ.get('HOME', str(project)),
        'PYTHONPATH': str(SOURCE), 'GRAFTLING_NATIVE_RUNTIME': 'pi',
        'GRAFTLING_NATIVE_SESSION': 'main-installed',
        'GRAFTLING_NATIVE_SESSION_FILE': str(project / 'native.jsonl'),
    }
    completed = subprocess.run([node, '--input-type=module', '-e', DRIVER, str(extension)],
                               cwd=project, env=environment, check=True, timeout=30,
                               capture_output=True, text=True)
    return json.loads(completed.stdout)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a configured project with a native Pi Session file."""
    configuration = tmp_path / 'project/.graphtraj/config.yml'
    configuration.parent.mkdir(parents=True)
    configuration.write_text(default_configuration_content(configuration.parents[1], configuration.parents[1]))
    native = configuration.parents[1] / 'native.jsonl'
    native.write_text(json.dumps({'type': 'session', 'id': 'main-installed', 'version': 3,
                                  'timestamp': 0, 'cwd': str(native.parent)}) + '\n')
    return native.parent


def test_extension_starts_its_installation_commands_without_path(tmp_path: Path, project: Path) -> None:
    """Session entry, collection and the MCP server use the installation's bin, absent from PATH."""
    prefix = tmp_path / 'prefix'
    report = drive(project, installation(prefix, scripts=True))

    assert report['entry'] == {'value': {'source': 'main'}}
    assert report['collection'] == {'value': 'closed'}
    assert report['mcp'] == {'value': str(prefix / 'bin/graphtraj-mcp')}
    assert (prefix / 'used').read_text().splitlines() == ['graphtraj-session', 'graphtraj-session']

    with nullcontext(JsonlSessionStore(archive_path(project / '.graphtraj/swarm', 'pi:main-installed'))) as store:
        assert store.header['source'] == 'main'
        attempt = next(item['event'] for item in store.pending() if item['event']['type'] == 'assistant/attempt')
        assert ''.join(item.get('text', '') for item in attempt['data']['stream']) == 'from installation'


def test_missing_command_names_every_place_looked(tmp_path: Path, project: Path) -> None:
    """Without the installation's script or a PATH one, the error says what and where, not ENOENT."""
    prefix = tmp_path / 'prefix'
    report = drive(project, installation(prefix, scripts=False))

    for name, command in (('entry', 'graphtraj-session'), ('collection', 'graphtraj-session'),
                          ('mcp', 'graphtraj-mcp')):
        message = report[name]['error']
        assert 'ENOENT' not in message
        assert f'no executable {command}' in message
        assert f"this installation's {prefix / 'bin'}{os.sep}" in message
        assert f'on PATH ({project / "only-node"})' in message
