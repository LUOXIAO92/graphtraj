"""Actual Team membership through the shared state registration entry."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import require_task_authority, runtime_caller
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.ticket_graph import register_ticket, update_ticket_state
from graphtraj.graph.delivery_worldline import read_worldline
from test_ticket_graph import _ticket


def _register_research_team(tmp_path: Path) -> Path:
    """A Team needs no fixed seats and may contain repeated roles."""
    state = tmp_path / 'state'
    directory = register_ticket(state, tmp_path, _ticket('148', 'research'))
    (tmp_path / 'evidence.md').write_text('Task evidence\n')
    event = update_ticket_state(state, tmp_path, {
        'ticket_id': '148', 'status': 'ready', 'active_team_ordinal': None,
        'worktree': None, 'branch': None, 'current_candidate': None,
        'caused_by_event_ids': [], 'evidence_refs': ['evidence.md'],
    })
    request = {
        'phase': 'start', 'ticket_id': '148',
        'caused_by_event_ids': [event['event_id']], 'evidence_refs': ['evidence.md'],
        'worktree': 'worktrees/research', 'branch': 'agent/148-research',
        'members': {'first': {'role': 'researcher', 'session_ref': 'research@x1'}},
    }
    apply_delivery_state_request(state, tmp_path, request, request)
    path = directory / 'teams/1/team.yml'
    assert read_team(path)['members'] == {
        'first': {'role': 'researcher', 'session_ref': 'research@x1'},
    }
    for name, role, alias in [
        ('second', 'researcher', 'research@x2'),
        ('third', 'analyst', 'research@x3'),
    ]:
        request = {
            'phase': 'member', 'ticket_id': '148',
            'caused_by_event_ids': [read_worldline(state, tmp_path)[-1]['event_id']],
            'evidence_refs': ['evidence.md'], 'member': name, 'role': role,
            'session_ref': alias,
        }
        apply_delivery_state_request(state, tmp_path, request, request)
    return path


def test_register_single_researcher_then_multiple_actual_members(tmp_path: Path) -> None:
    """Registration preserves multiple roles and repeated-role instances."""
    path = _register_research_team(tmp_path)
    assert read_team(path)['members'] == {
        'first': {'role': 'researcher', 'session_ref': 'research@x1'},
        'second': {'role': 'researcher', 'session_ref': 'research@x2'},
        'third': {'role': 'analyst', 'session_ref': 'research@x3'},
    }


def test_task_authority_uses_actual_parent_and_member_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-role siblings and forged role environment values grant no authority."""
    _register_research_team(tmp_path)
    runner = tmp_path / 'runner'
    for alias, parent, role in [
        ('research@x1', None, 'researcher'),
        ('research@x2', None, 'researcher'),
        ('research@x3', 'research@x1', 'analyst'),
        ('research@x4', 'research@x1', 'analyst'),
    ]:
        directory = runner / 'sessions' / alias
        directory.mkdir(parents=True)
        (directory / 'mapping.yml').write_text(yaml.safe_dump({
            'alias': alias, 'runtime': 'codex', 'session': 'native-' + alias,
            'ticket_id': '148', 'team_generation': 1, 'role': role, 'parent': parent,
            'retained_batch_file': 'batch.yml', 'worktree_path': str(tmp_path),
            'trace_file': 'events.jsonl', 'worker_pid': 1, 'runtime_pid': 1,
        }))
    state = tmp_path / 'state'
    with runtime_caller(runner, 'research@x3'):
        require_task_authority(state, runner, '148', 'research@x3', 'submit')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, '148', 'research@x3', 'accept')
    with runtime_caller(runner, 'research@x1'):
        require_task_authority(state, runner, '148', 'research@x3', 'accept')
        require_task_authority(state, runner, '148', 'research@x4', 'register-member')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, '148', 'research@x4', 'accept')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, 'wrong-ticket', 'research@x3', 'accept')
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'team-leader')
    monkeypatch.setenv('GRAPHTRAJ_PARENT_ALIAS', 'research@x1')
    with runtime_caller(runner, 'research@x2'):
        require_task_authority(state, runner, '148', 'research@x2', 'submit')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, '148', 'research@x3', 'accept')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, '148', 'research@x4', 'register-member')
    with runtime_caller(runner, None):
        require_task_authority(state, runner, '148', 'research@x1', 'accept')
        with pytest.raises(RunnerError):
            require_task_authority(state, runner, '148', 'research@x3', 'accept')

    # Exercise the existing process/ownership boundary, without a caller override.
    directory = runner / 'sessions' / 'research@x2'
    mapping_file = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping.update(worker_pid=os.getpid(), runtime_pid=os.getpid(), role='team-leader')
    mapping_file.write_text(yaml.safe_dump(mapping))
    script = (
        'from pathlib import Path\n'
        'from graphtraj.execution.runner_status import require_task_authority\n'
        'from graphtraj.execution.runner_models import RunnerError\n'
        f'state = Path({str(state)!r})\nrunner = Path({str(runner)!r})\n'
        "require_task_authority(state, runner, '148', 'research@x2', 'submit')\n"
        "try:\n    require_task_authority(state, runner, '148', 'research@x3', 'accept')\n"
        "except RunnerError as error:\n    assert error.code == 'authority-denied'\n"
        "else:\n    raise AssertionError('A same-role non-parent was authorized')\n"
    )
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    with hold_ownership(directory, os.getpid()):
        result = subprocess.run(
            [sys.executable, '-c', script], env=environment, capture_output=True, text=True,
            timeout=15,
        )
    assert result.returncode == 0, result.stdout + result.stderr


def test_historical_four_seat_team_reads_without_rewriting(tmp_path: Path) -> None:
    """Completed legacy Team records keep their empty seats and closed Round."""
    document = {
        'team_ordinal': 1, 'status': 'active', 'current_round': 1,
        'started_at': '2026-09-01T00:00:00Z',
        'members': {
            'team_leader': {'role': 'team-leader', 'session_ref': 'old@l1'},
            'engineer': {'role': 'engineer-expert', 'session_ref': 'old@e1'},
            'standards_reviewer': {'role': 'standards-reviewer', 'session_ref': None},
            'spec_reviewer': {'role': 'spec-reviewer', 'session_ref': None},
        },
    }
    path = tmp_path / 'team.yml'
    path.write_text(yaml.safe_dump(document))
    path.chmod(0o444)
    before = path.read_bytes()
    assert read_team(path) == document
    assert path.read_bytes() == before


def test_duplicate_session_cannot_register_as_a_second_member(tmp_path: Path) -> None:
    """A role rename cannot create another membership for an existing Session."""
    path = _register_research_team(tmp_path)
    before = path.read_bytes()
    state = tmp_path / 'state'
    events = read_worldline(state, tmp_path)
    request = {
        'phase': 'member', 'ticket_id': '148',
        'caused_by_event_ids': [events[-1]['event_id']], 'evidence_refs': ['evidence.md'],
        'member': 'renamed', 'role': 'team-leader', 'session_ref': 'research@x1',
    }
    with pytest.raises(ValueError):
        apply_delivery_state_request(state, tmp_path, request, request)
    assert path.read_bytes() == before
    assert read_worldline(state, tmp_path) == events
