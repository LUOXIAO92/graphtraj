"""An ordinary parent interrupt leaves the Session on standby for that parent."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import runner_control, runner_status
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import require_execution_allowed


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One idle child under a Leader, with recorded mappings read from disk."""
    sessions = tmp_path / 'sessions'
    for alias, parent in (('leader', None), ('child', 'leader')):
        (sessions / alias).mkdir(parents=True)
        (sessions / alias / 'mapping.yml').write_text(yaml.safe_dump({'alias': alias, 'parent': parent}))
    def read(runner: Path, alias: str) -> tuple[dict, Path]:
        return (yaml.safe_load((runner / 'sessions' / alias / 'mapping.yml').read_text()),
                runner / 'sessions' / alias)

    monkeypatch.setattr(runner_control, 'read_alias_mapping', read)
    monkeypatch.setattr(runner_status, 'read_alias_mapping', read)
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *args: None)
    return tmp_path


def _stop(runner: Path, alias: str, record: dict) -> Path:
    path = runner / 'sessions' / alias / 'stop.yml'
    path.write_text(yaml.safe_dump(record))
    return path


def _allowed(runner: Path, alias: str = 'child') -> bool:
    mapping = yaml.safe_load((runner / 'sessions' / alias / 'mapping.yml').read_text())
    try:
        require_execution_allowed(runner, alias, mapping)
    except RunnerError as error:
        assert error.code == 'subtree-stopped'
        return False
    return True


def test_the_interrupting_parent_continues_the_same_session(runner: Path) -> None:
    """The direct parent's own interrupt lifts on that parent's send or resume."""
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    assert not _allowed(runner)
    runner_control._continue_after_parent_interrupt(runner / 'sessions/child', 'child', 'leader')
    assert _allowed(runner)


@pytest.mark.parametrize('record, caller', [
    ({'alias': 'child', 'kind': 'interrupt', 'by': 'other'}, 'leader'),  # stopped by someone else
    ({'alias': 'child'}, 'leader'),                                      # Runner recovery or replacement
    ({'alias': 'child', 'by': 'leader'}, 'leader'),                      # no interrupt origin
    ({'alias': 'child', 'kind': 'interrupt', 'by': None}, 'leader'),     # Main's interrupt
])
def test_other_stops_stay_in_force(runner: Path, record: dict, caller: str) -> None:
    stop = _stop(runner, 'child', record)
    before = stop.read_bytes()
    runner_control._continue_after_parent_interrupt(runner / 'sessions/child', 'child', caller)
    assert stop.read_bytes() == before and not _allowed(runner)


def test_an_ancestor_stop_and_a_running_execution_stay_in_force(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    _stop(runner, 'leader', {'alias': 'leader'})
    runner_control._continue_after_parent_interrupt(runner / 'sessions/child', 'child', 'leader')
    assert not _allowed(runner)  # the child's own record lifted, the ancestor's did not
    assert yaml.safe_load((runner / 'sessions/child/stop.yml').read_text())['resumed'] is True

    _stop(runner, 'leader', {'alias': 'leader', 'kind': 'interrupt', 'by': None})
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *args: {'activity': 'running'})
    runner_control._continue_after_parent_interrupt(runner / 'sessions/leader', 'leader', None)
    assert not _allowed(runner, 'leader')  # the interrupted execution is still running


def test_the_execution_budget_stop_is_untouched(runner: Path) -> None:
    """The budget stop is separate Task state; lifting an interrupt never reads or clears it."""
    budget = runner / 'execution-budget.yml'
    budget.write_text(yaml.safe_dump({'stopped': True}))
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    runner_control._continue_after_parent_interrupt(runner / 'sessions/child', 'child', 'leader')
    assert yaml.safe_load(budget.read_text()) == {'stopped': True}


def test_ordinary_interrupt_records_its_origin_without_rewriting_another_stop(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``agents interrupt`` records an origin, and never over a stop already in force."""
    from graphtraj.teams import team_round

    monkeypatch.setattr(runner_control, 'discover_runner_directory', lambda cwd: runner)
    monkeypatch.setattr(runner_control, 'require_descendant_authority', lambda *args: None)
    monkeypatch.setattr(runner_control, 'execution_start_lock', lambda runner: contextlib.nullcontext())
    monkeypatch.setattr(runner_control, '_recorded_sessions', lambda *args, **kwargs: ({}, []))
    monkeypatch.setattr(runner_control, '_interrupt_session', lambda alias, *args: {
        'alias': alias, 'interrupt_status': 'interrupted'})
    monkeypatch.setattr(team_round, 'withdraw_pending_children', lambda directory: None)
    monkeypatch.setattr(runner_control, 'caller_alias', lambda runner: 'leader')
    stop = runner / 'sessions/child/stop.yml'

    runner_control.interrupt_session('child', runner)  # Runner abnormal-session answer
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child'}
    runner_control.interrupt_session('child', runner, ordinary=True)
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child'}  # still the Runner's stop

    stop.write_text(yaml.safe_dump({'alias': 'child', 'resumed': True}))
    runner_control.interrupt_session('child', runner, ordinary=True)
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'}
