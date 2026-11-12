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


def _lift(directory: Path, alias: str, caller: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Continue as ``caller``, the identity the process tree would resolve."""
    monkeypatch.setattr(runner_control, 'caller_alias', lambda runner: caller)
    runner_control._continue_after_parent_interrupt(directory, alias, directory.parent.parent)


def _allowed(runner: Path, alias: str = 'child') -> bool:
    mapping = yaml.safe_load((runner / 'sessions' / alias / 'mapping.yml').read_text())
    try:
        require_execution_allowed(runner, alias, mapping)
    except RunnerError as error:
        assert error.code == 'subtree-stopped'
        return False
    return True


def test_the_interrupting_parent_continues_the_same_session(runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The direct parent's own interrupt lifts on that parent's send or resume."""
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    assert not _allowed(runner)
    _lift(runner / 'sessions/child', 'child', 'leader', monkeypatch)
    assert _allowed(runner)


@pytest.mark.parametrize('record, caller', [
    ({'alias': 'child', 'kind': 'interrupt', 'by': 'other'}, 'leader'),  # stopped by someone else
    ({'alias': 'child'}, 'leader'),                                      # Runner recovery or replacement
    ({'alias': 'child', 'by': 'leader'}, 'leader'),                      # no interrupt origin
    ({'alias': 'child', 'kind': 'interrupt', 'by': None}, 'leader'),     # Main's interrupt
    ({'alias': 'child', 'kind': 'interrupt', 'by': 'child'}, 'child'),   # its own interrupt
])
def test_other_stops_stay_in_force(
    runner: Path, record: dict, caller: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = _stop(runner, 'child', record)
    before = stop.read_bytes()
    _lift(runner / 'sessions/child', 'child', caller, monkeypatch)
    assert stop.read_bytes() == before and not _allowed(runner)


def test_an_ancestor_stop_and_a_running_execution_stay_in_force(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    _stop(runner, 'leader', {'alias': 'leader'})
    _lift(runner / 'sessions/child', 'child', 'leader', monkeypatch)
    assert not _allowed(runner)  # the child's own record lifted, the ancestor's did not
    assert yaml.safe_load((runner / 'sessions/child/stop.yml').read_text())['resumed'] is True

    _stop(runner, 'leader', {'alias': 'leader', 'kind': 'interrupt', 'by': None})
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *args: {'activity': 'running'})
    _lift(runner / 'sessions/leader', 'leader', None, monkeypatch)
    assert not _allowed(runner, 'leader')  # the interrupted execution is still running


def test_the_execution_budget_stop_is_untouched(runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The budget stop is separate Task state; lifting an interrupt never reads or clears it."""
    budget = runner / 'execution-budget.yml'
    budget.write_text(yaml.safe_dump({'stopped': True}))
    _stop(runner, 'child', {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'})
    _lift(runner / 'sessions/child', 'child', 'leader', monkeypatch)
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

    other = {'alias': 'child', 'kind': 'interrupt', 'by': 'other-parent', 'note': 'kept'}
    stop.write_text(yaml.safe_dump(other))
    runner_control.interrupt_session('child', runner, ordinary=True)
    assert yaml.safe_load(stop.read_text()) == other  # another parent's interrupt survives

    stop.write_text(yaml.safe_dump({'alias': 'child', 'resumed': True}))
    runner_control.interrupt_session('child', runner, ordinary=True)
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'}


def _abnormal_child(runner: Path, monkeypatch: pytest.MonkeyPatch, *, held: bool = False,
                    confirmed: bool = True, ended: str = 'e1') -> Path:
    """Record the child's execution e1 as answered abnormal, its end confirmed or not."""
    directory = runner / 'sessions/child'
    (directory / 'mapping.yml').write_text(yaml.safe_dump(
        {'alias': 'child', 'parent': 'leader', 'execution_id': 'e1', 'worker_pid': 1}))
    (directory / 'execution.yml').write_text(yaml.safe_dump({
        'outcome': 'runtime-error', 'execution_id': ended, 'terminal_confirmed': False,
        'error': {'code': 'owner-exited'}}))
    (directory / 'abnormal-response.yml').write_text('{"alias": "child", "at": 1}\n')

    def terminal(path: Path) -> str:
        if not confirmed:
            raise RunnerError('invalid-activity', 'no termination confirmation')
        return 'runtime-error'

    monkeypatch.setattr(runner_control, 'read_terminal_outcome', terminal)
    monkeypatch.setattr(runner_control, 'ownership_is_held', lambda directory, pid: held)
    return directory


def test_the_abnormal_answer_stop_lifts_once_its_execution_end_is_confirmed(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct parent continues a Session whose killed owner was reconciled (T5c)."""
    directory = _abnormal_child(runner, monkeypatch)
    _stop(runner, 'child', {'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'})
    assert not _allowed(runner)
    _lift(directory, 'child', 'leader', monkeypatch)
    assert _allowed(runner)
    # The answer's claim is kept under the answered execution, so a later
    # execution judged abnormal is answered again.
    assert not (directory / 'abnormal-response.yml').exists()
    assert (directory / 'abnormal-response-e1.yml').is_file()


@pytest.mark.parametrize('stop, setup', [
    ({'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e0'}, {}),            # another execution
    ({'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'}, {'held': True}),  # owner lock held
    ({'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'}, {'confirmed': False}),  # unconfirmed end
    ({'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'}, {'ended': 'e0'}),  # stale terminal
    ({'alias': 'child'}, {}),                                                       # Runner recovery
])
def test_other_abnormal_stops_stay_in_force(
    runner: Path, stop: dict, setup: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _abnormal_child(runner, monkeypatch, **setup)
    path = _stop(runner, 'child', stop)
    before = path.read_bytes()
    _lift(directory, 'child', 'leader', monkeypatch)
    assert path.read_bytes() == before and not _allowed(runner)
    assert (directory / 'abnormal-response.yml').is_file()


def test_the_abnormal_answer_stop_neither_lifts_for_itself_nor_under_an_ancestor_stop(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _abnormal_child(runner, monkeypatch)
    path = _stop(runner, 'child', {'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'})
    _lift(directory, 'child', 'child', monkeypatch)
    assert yaml.safe_load(path.read_text()).get('resumed') is None
    _stop(runner, 'leader', {'alias': 'leader'})
    _lift(directory, 'child', 'leader', monkeypatch)
    assert not _allowed(runner)  # the child's own record lifted, the ancestor's did not


def test_reconciliation_reads_only_an_owner_that_released_its_lock(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running or unreachable owner holds its lock and is left to the ordinary send."""
    directory = runner / 'sessions/child'
    mapping = {'alias': 'child', 'parent': 'leader', 'execution_id': 'e1', 'worker_pid': 1}
    judged = []
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *args: judged.append(args[0]))
    for held in (True, False):
        monkeypatch.setattr(runner_control, 'ownership_is_held', lambda directory, pid: held)
        runner_control._reconcile_exited_owner('child', directory, mapping)
    assert judged == ['child']
    (directory / 'execution.yml').write_text('outcome: completed\n')  # already ended
    runner_control._reconcile_exited_owner('child', directory, mapping)
    assert judged == ['child']


def test_abnormal_answer_records_its_execution_without_rewriting_another_stop(
    runner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from graphtraj.teams import team_round

    monkeypatch.setattr(runner_control, 'discover_runner_directory', lambda cwd: runner)
    monkeypatch.setattr(runner_control, 'require_descendant_authority', lambda *args: None)
    monkeypatch.setattr(runner_control, 'execution_start_lock', lambda runner: contextlib.nullcontext())
    monkeypatch.setattr(runner_control, '_recorded_sessions', lambda *args, **kwargs: ({}, []))
    monkeypatch.setattr(runner_control, '_interrupt_session', lambda alias, *args: {
        'alias': alias, 'interrupt_status': 'stopped'})
    monkeypatch.setattr(team_round, 'withdraw_pending_children', lambda directory: None)
    monkeypatch.setattr(runner_control, 'caller_alias', lambda runner: 'leader')
    stop = runner / 'sessions/child/stop.yml'

    runner_control.interrupt_session('child', runner, abnormal_execution='e1')
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1'}

    for previous in ({'alias': 'child'}, {'alias': 'child', 'kind': 'interrupt', 'by': 'leader'}):
        stop.write_text(yaml.safe_dump(previous))
        runner_control.interrupt_session('child', runner, abnormal_execution='e2')
        assert yaml.safe_load(stop.read_text()) == previous

    stop.write_text(yaml.safe_dump({'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e1', 'resumed': True}))
    runner_control.interrupt_session('child', runner, abnormal_execution='e2')
    assert yaml.safe_load(stop.read_text()) == {'alias': 'child', 'kind': 'abnormal', 'execution_id': 'e2'}
    # An ordinary interrupt leaves the abnormal answer's stop in force as recorded.
    runner_control.interrupt_session('child', runner, ordinary=True)
    assert yaml.safe_load(stop.read_text())['kind'] == 'abnormal'
