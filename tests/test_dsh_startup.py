"""Failed native startup retains bounded diagnostics without credentials."""
import os
from pathlib import Path
import sys

import pytest

from agent_swarm.dsh.errors import DshError
from agent_swarm.dsh.service import DshService


def test_failed_startup_retains_reason_and_redacts_credentials(tmp_path: Path) -> None:
    """A real subprocess failure names its cause, not auth values or URLs."""
    program = tmp_path / 'dsh'
    program.write_text(f'#!{sys.executable}\nimport os\n'
                       'print("Error: missing package example-module")\n'
                       'print(os.environ["TEST_API_KEY"])\n'
                       'print("Authorization: Bearer sensitive-token")\n'
                       'print("https://example.invalid/?token=hidden")\n'
                       'raise SystemExit(7)\n')
    program.chmod(0o755)
    service = DshService(str(program), tmp_path, {**os.environ, 'TEST_API_KEY': 'never-retain-me'})
    try:
        with pytest.raises(DshError) as failure:
            service.start()
        assert 'missing package example-module' in failure.value.message
        assert 'pid=' in failure.value.message
        assert all(secret not in failure.value.message for secret in (
            'never-retain-me', 'sensitive-token', 'example.invalid', 'hidden'))
    finally:
        service.close()
    assert service.process.poll() == 7


@pytest.mark.skipif(not os.environ.get('TASK334_STARTUP_ROOT'), reason='Requires assigned native startup diagnosis.')
def test_actual_startup_without_model() -> None:
    """Start only the assigned retained profile, authenticate, and close; no Session input."""
    import json
    root = Path(os.environ['TASK334_STARTUP_ROOT'])
    record = json.loads(next((root / 'control/agents').glob('*.json')).read_text())
    request = record['settings']
    directory = root / 'native' / record['agent']
    environment = dict(os.environ)
    for name in ('AGENTS_CONNECTION', 'AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION'):
        environment.pop(name, None)
    environment.update(DSH_HOME=str(directory / 'dsh-home'), DSH_AGENT_PACKAGE=request['package'],
                       DSH_PERMISSION_MODE=request['sandbox'], NO_COLOR='1')
    service = DshService(request['executable'], Path(request['worktree_path']), environment)
    try:
        service.start()
        print(json.dumps({'startup_authenticated': True, 'origin': service.origin,
                          'pid': service.process.pid, 'model_turns': 0}))
    except DshError as error:
        (directory / 'startup-diagnostic.txt').write_text(error.message)
        raise
    finally:
        service.close()
        if service.process is not None:
            print(json.dumps({'startup_pid': service.process.pid, 'returncode': service.process.poll()}))
