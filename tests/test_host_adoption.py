"""Public first adoption with controlled native review and lifecycle responses."""

import json
import os
import subprocess
import shlex
import signal
from pathlib import Path

import pytest
from click.testing import CliRunner

from graphtraj.execution import host_adoption, runner_worker
from graphtraj.execution.runner_connection import connection_operation
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.cli.graphtraj import main
from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter
from test_main_finalize import host, options


EVENT = {'hook_event_name': 'Stop', 'session_id': 'shared-native-session',
         'turn_id': 'main-turn', 'stop_hook_active': False, 'model': 'actual-model'}


@pytest.fixture
def external(host: tuple, monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Control native review/delivery only; retain production registration and transport."""
    root, _, visible = host
    monkeypatch.chdir(root)
    monkeypatch.setenv('CODEX_THREAD_ID', 'main')
    monkeypatch.setenv('CODEX_HOME', str(root))
    monkeypatch.setenv('PYTHONPATH', str(Path(host_adoption.__file__).parents[2]))
    proposals = []

    def review(adapter: object, proposal: dict, cwd: Path) -> dict:
        """Record the exact controlled decision; no live reviewer claim is made."""
        proposals.append(proposal)
        return {'decision': 'accept'}

    monkeypatch.setattr(CodexRuntimeAdapter, 'native_recovery_approval', review)
    monkeypatch.setattr(CodexRuntimeAdapter, 'send_host_event',
                        lambda adapter, connection, event: visible.append(event))
    options(host, read_id_from_request=True, turns_by_thread={'checker': 'check-turn'})
    return root, proposals, visible


def hook_arguments(document: dict) -> list[str]:
    """Read the executable carrier printed by the real public entry."""
    command = document['hook']['hooks']['Stop'][0]['hooks'][0]['command']
    return shlex.split(command)[3:]


def invoke_hook(document: dict, event: dict) -> subprocess.CompletedProcess[str]:
    """Run the exact prepared fixed handler as its own command process."""
    command = document['hook']['hooks']['Stop'][0]['hooks'][0]['command']
    return subprocess.run(
        shlex.split(command), input=json.dumps(event), text=True, capture_output=True,
        env={**os.environ, 'PYTHONPATH': str(Path(host_adoption.__file__).parents[2])},
        timeout=15,
    )


def test_public_adoption_serves_then_revokes_fixed_hook(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """The foreground CLI owns a usable hook until native termination releases it."""
    root, proposals, visible = external
    original = runner_worker.run_external_main
    prepared = []

    def exercise(cwd: Path, resume: str | None, ready: object) -> dict:
        """Exercise the live attachment inside the unchanged foreground owner."""
        def observe(document: dict) -> None:
            """Use the printed public hook while ownership remains held."""
            ready(document)
            prepared.append(document)
            options((root, None, None), read_id_from_request=True,
                    turns_by_thread={'checker': 'check-turn'},
                    checker_hook_command=document['hook']['hooks']['Stop'][0]['hooks'][0]['command'])
            result = invoke_hook(document, EVENT)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'pass:' in result.stdout
            assert '[GraphTraj hook: finish-check] start:' in result.stderr
            assert 'checker' in json.loads((root / 'checker-hook.json').read_text())['systemMessage']
            path = Path(hook_arguments(document)[1])
            capability = json.loads(path.read_text())
            with pytest.raises(RunnerError, match='not authenticated'):
                connection_operation(capability['address'], {'credential': 'wrong', 'event': EVENT})
            with pytest.raises(RunnerError, match='not authenticated'):
                connection_operation(capability['address'], {
                    'credential': capability['credential'], 'request': {'feature': 'swarm'},
                })
            checker = invoke_hook(document, {**EVENT, 'turn_id': 'check-turn'})
            assert 'skip:' in checker.stdout and 'checker' in checker.stdout
            signal.raise_signal(signal.SIGTERM)

        return original(cwd, resume, observe)

    monkeypatch.setattr(runner_worker, 'run_external_main', exercise)
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code == 0, result.output
    assert len(prepared) == 1
    assert proposals[0]['operation'] == 'adopt-main'
    assert proposals[0]['execution_connection']['session'] == 'main'
    assert any('pass:' in event['message'] for event in visible)
    assert not Path(hook_arguments(prepared[0])[1]).exists()
    closed = invoke_hook(prepared[0], EVENT)
    assert 'failure:' in closed.stdout
    assert '"continue": false' in closed.stdout
    # The closed owner remains registered; explicit restoration keeps that identity.
    with host_adoption.external_main(root, prepared[0]['alias']) as restored:
        assert restored['alias'] == prepared[0]['alias']


def test_adoption_refuses_missing_context_review_and_bound_member(
    external: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public command does not turn an absent/denied/bound caller into Main."""
    root, proposals, _ = external
    monkeypatch.delenv('CODEX_THREAD_ID')
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0 and 'owning Codex connection' in result.output
    assert not proposals
    monkeypatch.setenv('CODEX_THREAD_ID', 'main')
    monkeypatch.setattr(CodexRuntimeAdapter, 'native_recovery_approval',
                        lambda *args: {'decision': 'decline'})
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0 and 'did not authorize' in result.output
    from graphtraj.execution.runner_status import runtime_caller

    with runtime_caller(root / '.graphtraj/runner', 'registered-member'):
        result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0


def test_retained_checker_cannot_be_adopted_as_main(external: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport associated by an actual check cannot gain Main purpose later."""
    root, _, _ = external
    with host_adoption.external_main(root) as prepared:
        result = invoke_hook(prepared, EVENT)
        assert 'pass:' in result.stdout
        duplicate = CliRunner().invoke(main, ['adopt-main'])
        assert duplicate.exit_code != 0 and 'already belongs' in duplicate.output
    monkeypatch.setenv('CODEX_THREAD_ID', 'checker')
    result = CliRunner().invoke(main, ['adopt-main'])
    assert result.exit_code != 0 and 'already belongs' in result.output
