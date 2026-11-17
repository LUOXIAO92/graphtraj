"""A DSH session the user starts becomes GraphTraj Main through the shipped patch."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from graphtraj.execution.main_continuity import current_main
from test_external_session_entry import project  # noqa: F401
from test_pi_dsh_main_continuity import as_dsh_mcp, agents, mcp


ROOT = Path(__file__).resolve().parents[1]

# Load the shipped plugin as DSH would: argv[1] is the `dsh` command (a symlink),
# the config comes from the patch row, and the native ctx/agent are recorded.
SCRIPT = '''
import { pathToFileURL } from 'node:url';
const [, module, cwd, python, refuse] = process.argv.slice(1);
const plugin = await import(pathToFileURL(module).href);
const handlers = {}, attached = [], errors = [], sent = [];
const ctx = {
  shellEnv: { register() {} }, effect() {}, logger: { error: message => errors.push(message) },
  on: (name, handler) => { handlers[name] = handler; },
  sessionQuery: { observeSession: async () => ({ events: [], cursor: -1, [Symbol.dispose]() {} }) },
};
if (refuse) {
  try { plugin.apply(ctx, { finishCheck: false, python }); console.log(JSON.stringify({ applied: true })); }
  catch (error) { console.log(JSON.stringify({ refused: error.message })); }
  process.exit(0);
}
plugin.apply(ctx, { finishCheck: false, python });
const header = { version: 4, id: 'dsh-user-main', createdAt: 1, isSeeded: false, cwd };
const agent = { session: { id: header.id, header }, send: message => sent.push(message),
  ctx: { plugin: (client, config) => { attached.push(config); return { await: async () => {} }; } } };
const signal = new AbortController().signal;
await handlers['agent/created']({ agent, source: 'startup', signal });
await handlers['agent/created']({ agent, source: 'compact', signal });
await handlers['session/disposed']({ id: header.id });
console.log(JSON.stringify({ attached, errors, sent: sent.length }));
'''


def run_plugin(project: Path, python: Path, **environment: str) -> dict:  # noqa: F811
    """Run the shipped tool.mjs in Node with a recording DSH context."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Node and the installed DSH are required')
    # A user's shell has no member or package variables.
    clean = {name: value for name, value in os.environ.items()
             if not name.startswith(('GRAPHTRAJ_', 'GRAFTLING_', 'DSH_'))}
    refuse = '1' if environment else ''
    result = subprocess.run(
        [node, '--input-type=module', '-e', SCRIPT, dsh, str(ROOT / 'src/graphtraj/runtimes/dsh/tool.mjs'),
         str(project), str(python), refuse],
        cwd=project, env={**clean, **environment}, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_patch_names_this_installation(tmp_path: Path) -> None:
    """The command writes one row loading the shipped plugin with this Python."""
    target = tmp_path / 'patch/graphtraj-main.yml'
    result = subprocess.run(
        [sys.executable, '-I', '-m', 'graphtraj.runtimes.dsh.main_entry', 'patch', '--write', str(target)],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(target)
    row, = yaml.safe_load(target.read_text())[0]['insert']
    assert row['id'] == 'graphtraj-main' and row['id'] != 'agents-host'
    assert Path(row['name']).is_file() and row['name'].endswith('graphtraj/runtimes/dsh/tool.mjs')
    assert row['config'] == {'python': str(Path(sys.executable).absolute())}


def test_user_started_dsh_claims_main_and_gets_the_tasks_tool(
    project: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """agent/created claims Main once; the attached server serves that Main's tasks."""
    python = Path(sys.executable).absolute()
    result = run_plugin(project, python)

    main = current_main(project / '.graphtraj/runner')
    assert main['entry'] == 'dsh:agent/created:startup'
    assert main['connection']['session'] == 'dsh-user-main'
    assert result['errors'] == []
    assert result['attached'] == [{
        'transport': 'stdio', 'serverName': 'graphtraj', 'command': str(python),
        'args': ['-I', '-m', 'graphtraj.interfaces.mcp'], 'cwd': str(project),
        'env': {'DSH_SESSION_ID': 'dsh-user-main', 'DSH_AGENT_SOURCE': 'main'},
        'toolCallTimeoutMs': 300000, 'failOnStartupError': True,
    }]

    # That server's environment identifies the claimed Main without a host channel.
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    as_dsh_mcp(monkeypatch, 'dsh-user-main')
    status, graph = mcp(agents('status'), ('tasks', {'action': 'execute', 'feature': 'task_graph', 'arguments': {}}))
    assert not status['isError'] and not graph['isError'], (status, graph)


def test_graftling_host_configuration_is_refused(project: Path, tmp_path: Path) -> None:  # noqa: F811
    """With graftling-dsh's host enabled the Session would get a second agents host."""
    result = run_plugin(project, Path(sys.executable), GRAFTLING_DSH_CONFIG=str(tmp_path / 'host.json'))
    assert 'GRAFTLING_DSH_CONFIG' in result['refused']
