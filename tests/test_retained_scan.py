"""A whole-project status view scans the retained Session records once, not once per Session."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from graphtraj.execution import runner_status


@pytest.fixture
def scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Retain six Sessions in Task Traces and count the configuration loads that start each scan."""
    import graphtraj.configuration.project_configuration as configuration
    import graphtraj.workspace.runner_project as runner_project

    for index in range(6):
        retained = tmp_path / f'state/tasks/{index}-task/teams/1/traces/{index}-task-handover0-engineer@engineer_{index}/runner'
        retained.mkdir(parents=True)
        (retained / 'session.yml').write_text('retirement: {}\n')
    (tmp_path / 'runner/sessions/live').mkdir(parents=True)
    loads: list[Path] = []
    monkeypatch.setattr(configuration, 'load_project_configuration',
                        lambda root: loads.append(root) or SimpleNamespace(state=tmp_path / 'state'))
    monkeypatch.setattr(runner_project, 'discover_project_root', lambda cwd: tmp_path)
    return loads


def test_one_enumeration_scans_retained_records_once(tmp_path: Path, scans: list[Path]) -> None:
    records, failures = runner_status._recorded_sessions(tmp_path / 'runner')
    assert {alias for alias, _ in failures} == {'live', *(f'{index}-task-handover0-engineer@engineer_{index}' for index in range(6))}
    assert len(scans) == 1


def test_the_member_default_tree_scans_once(
    tmp_path: Path, scans: list[Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_status, 'discover_runner_directory', lambda cwd: tmp_path / 'runner')
    monkeypatch.setattr(runner_status, 'caller_alias', lambda runner: 'live')
    runner_status.status_tree(tmp_path)
    assert len(scans) == 1


def test_the_shared_scan_ends_with_its_call(tmp_path: Path, scans: list[Path]) -> None:
    """A later call sees records retired after the earlier one."""
    runner_status._recorded_sessions(tmp_path / 'runner')
    runner_status._recorded_sessions(tmp_path / 'runner')
    assert len(scans) == 2
    assert runner_status._retained_scan.get() is None
