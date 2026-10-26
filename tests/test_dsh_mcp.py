"""Progressive MCP evidence, independent from official UI/model acceptance."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

def test_installed_dsh_official_mcp_client() -> None:
    """Use installed official client initialize/list/call over actual stdio."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required for native MCP evidence.')
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_mcp.mjs'), str(Path(dsh).resolve()),
        sys.executable, str(root / 'tests/fixtures/dsh_mcp_server.py'), str(root / 'src'),
    ], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence['tools'] == ['mcp__agents__agents']
    assert evidence['call']['result']['caller'] == 'native-parent'


def test_delivered_plugin_native_scopes(tmp_path: Path) -> None:
    """The installed client publishes one scoped tool and preserves source context."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH and Node are required for native MCP evidence.')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_mcp_plugin.mjs'), str(Path(dsh).resolve()),
        str(root / 'src/agent_swarm/dsh/plugin.mjs'), sys.executable,
        str(root / 'tests/fixtures/dsh_mcp_server.py'),
    ], cwd=tmp_path, env={**os.environ,
        'GRAPHTRAJ_CLI_CONNECTION': 'controlled-unused', 'GRAPHTRAJ_DSH_AGENTS_ONLY': '1',
        'GRAPHTRAJ_HARNESS_ROOT': str(tmp_path), 'PYTHONPATH': str(root / 'src'),
    }, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence['childSourcePreserved']
    assert evidence['browserEntry'] == 'agents-dsh'


@pytest.mark.parametrize("registration_order", ["ready", "delayed"])
def test_browser_tool_view_preserves_model_content(registration_order: str) -> None:
    """Project outgoing text without replaying calls or duplicating inbound relay."""
    node, dsh = shutil.which('node'), shutil.which('dsh')
    if node is None or dsh is None:
        pytest.skip('Installed DSH slots and Node are required for the browser projection fixture.')
    slots = subprocess.run([node, '-e', "require('module').createRequire(process.argv[1])"
                            ".resolve('@deepseek-ai/dsh-client-ui-slots')", str(Path(dsh).resolve())],
                           capture_output=True, text=True, timeout=10)
    if slots.returncode != 0:
        pytest.skip('Installed DSH does not provide @deepseek-ai/dsh-client-ui-slots.')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        node, str(root / 'tests/fixtures/dsh_client_view.mjs'),
        str(root / 'src/agent_swarm/dsh/client.mjs'), str(Path(dsh).resolve()),
        registration_order,
    ], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
