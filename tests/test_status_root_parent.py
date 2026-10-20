"""A trimmed status view keeps each root's real recorded parent."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphtraj.execution import runner_status


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Record Main -> leader -> engineer without any live control."""
    records = {
        'leader@l1': {'parent': None},
        'engineer@e1': {'parent': 'leader@l1'},
        'helper@h1': {'parent': 'engineer@e1'},
    }
    monkeypatch.setattr(runner_status, 'discover_runner_directory', lambda cwd: tmp_path)
    monkeypatch.setattr(runner_status, '_recorded_sessions', lambda runner: (records, []))
    monkeypatch.setattr(runner_status, '_status_alias', lambda runner, alias, **options: {})
    return tmp_path


def _parents(root: Path) -> dict:
    return {node['alias']: node['parent'] for node in runner_status.status_tree(root).document['agents']}


def test_a_member_view_root_reports_its_real_parent(recorded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_status, 'caller_alias', lambda runner: 'engineer@e1')
    assert _parents(recorded) == {'engineer@e1': 'leader@l1', 'helper@h1': 'engineer@e1'}


def test_the_main_view_keeps_top_level_parents_empty(recorded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_status, 'caller_alias', lambda runner: None)
    assert _parents(recorded) == {'leader@l1': None, 'engineer@e1': 'leader@l1', 'helper@h1': 'engineer@e1'}
