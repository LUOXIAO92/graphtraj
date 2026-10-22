"""Exercise shared native values from the independent and combined wheels."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

from conftest import InstalledCommands


def test_independent_wheel_without_graphtraj(built_wheel: Path, tmp_path: Path) -> None:
    """The standalone artifact exposes native values without GraphTraj installed."""
    agents_wheel = next(built_wheel.parent.glob('agent_swarm-*.whl'))
    with zipfile.ZipFile(agents_wheel) as archive:
        archive.extractall(tmp_path)
    script = '''
import importlib.util
import sys
sys.path.insert(0, sys.argv[1])
assert importlib.util.find_spec('graphtraj') is None
from agent_swarm.runtime import (
    RuntimeAdapterError, RuntimeContext, RuntimeExecutionResult, RuntimeTurn, SessionStarted,
)
from agent_swarm import AgentControl, Caller
from agent_swarm.discovery import handle_request
from agent_swarm import cli, mcp
from agent_swarm.pi import PiDriver
from agent_swarm.pi import execution, host, launch, session
assert PiDriver({'worktree_path': '/w'}).prepare('pi', Caller('host', None))['cwd'] == '/w'
error = RuntimeAdapterError('NATIVE_FAILURE', 'native failure', terminal_confirmed=False)
assert (error.code, error.message, str(error), error.terminal_confirmed) == (
    'NATIVE_FAILURE', 'native failure', 'native failure', False)
assert RuntimeAdapterError('STOPPED', 'stopped').terminal_confirmed is True
result = RuntimeExecutionResult(outcome='interrupted', session_id='native-session',
    execution_id='native-execution', last_agent_message=None)
assert result == dict(outcome='interrupted', session_id='native-session',
    execution_id='native-execution', last_agent_message=None)
assert not any(name == 'graphtraj' or name.startswith('graphtraj.') for name in sys.modules)
'''
    completed = subprocess.run(
        [sys.executable, '-I', '-S', '-c', script, str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_wheels_have_separate_owners(built_wheel: Path) -> None:
    """Installation owns each native resource once and declares real dependencies."""
    agents_wheel = next(built_wheel.parent.glob('agent_swarm-*.whl'))
    with zipfile.ZipFile(agents_wheel) as archive:
        agents = set(archive.namelist())
        agents_metadata = archive.read(next(n for n in agents if n.endswith('/METADATA'))).decode()
    with zipfile.ZipFile(built_wheel) as archive:
        graphtraj = set(archive.namelist())
        metadata = archive.read(next(n for n in graphtraj if n.endswith('/METADATA'))).decode()
    assert not agents.intersection(graphtraj)
    assert 'Requires-Dist: agent-swarm==0.1.0' in metadata
    assert 'Requires-Dist: graphtraj' not in agents_metadata
    for text in (metadata, agents_metadata):
        assert 'Requires-Dist: PyYAML' in text
        assert 'Requires-Dist: websockets' in text
    assert 'agent_swarm/runtime.py' in agents
    assert 'agent_swarm/dsh/client.mjs' in agents
    assert 'agent_swarm/dsh/communication.mjs' in agents
    assert 'agent_swarm/dsh/package.json' in agents
    assert {'agent_swarm/pi/extension.mjs', 'agent_swarm/pi/launch.py', 'agent_swarm/pi/host.py'} <= agents
    assert 'graphtraj/runtimes/pi/extension.mjs' in graphtraj
    assert 'graphtraj/runtimes/claude/host_context.mjs' in graphtraj


def test_combined_native_values_and_adapters(installed_commands: InstalledCommands) -> None:
    """Both installed consumers catch the same errors and resolve every Adapter."""
    script = '''
import sys
from pathlib import Path
import agent_swarm.runtime
from agent_swarm.runtime import RuntimeAdapterError, RuntimeContext, RuntimeExecutionResult
from graphtraj.runtimes import runtime_adapter as consumer
assert Path(consumer.__file__).is_relative_to(sys.prefix)
assert Path(agent_swarm.runtime.__file__).is_relative_to(sys.prefix)
from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError
assert consumer.RuntimeAdapterError is RuntimeAdapterError
assert consumer.RuntimeContext is RuntimeContext
assert consumer.RuntimeExecutionResult is RuntimeExecutionResult
try:
    raise CodexAdapterError('NATIVE_FAILURE', 'native failure')
except RuntimeAdapterError as error:
    assert error.code == 'NATIVE_FAILURE'
for runtime in ('codex', 'claude', 'pi', 'dsh'):
    consumer.select_runtime_adapter(runtime)
from graphtraj.runtimes.claude import host
from agent_swarm.dsh import DshDriver
from agent_swarm.pi.execution import PiExecution
from graphtraj.runtimes.pi.managed_session import PiManagedExecution
assert issubclass(PiManagedExecution, PiExecution)
'''
    completed = subprocess.run(
        [str(installed_commands.product.with_name('python')), '-I', '-c', script],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
