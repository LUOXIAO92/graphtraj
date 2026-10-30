"""Task 382's Pi host and members together with agents 0.2.0 (384)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphtraj.runtimes.pi.managed_session import PiManagedExecution
from test_pi_standalone_host import run_host


def test_host_starts_with_archiving_on(tmp_path: Path) -> None:
    """Every host archives when saving is on; ``archive-unavailable`` is no longer returned."""
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.yml').write_text('save_normalized_sessions: true\n')
    process, first = run_host(tmp_path, {'root': str(data)})
    assert process.returncode == 0, process.stderr.read()
    assert json.loads(first)['connection']


def test_runner_member_keeps_the_hosted_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Runner execution serves the hosted CLI; the agents driver path keeps its own connection."""
    turn = PiManagedExecution({'harness_root': str(tmp_path)}, 'go', tmp_path / 'alias', None, None,
                              tmp_path / 'trace.jsonl', None)
    calls = []
    monkeypatch.setattr('graphtraj.interfaces.hosted_cli.cli_connection',
                        lambda *arguments: calls.append(arguments) or 'hosted')
    assert turn._connection() == 'hosted'
    assert calls[0][:2] == (tmp_path, 'alias')
    assert turn._connection_environment('address') == {
        'GRAPHTRAJ_CLI_CONNECTION': 'address', 'GRAPHTRAJ_HARNESS_ROOT': str(tmp_path.resolve())}
    turn.independent = True
    assert 'AGENT_SWARM_CONNECTION' in turn._connection_environment('address')
