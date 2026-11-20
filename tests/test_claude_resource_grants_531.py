"""Task 531: a Claude member's child preflight reads no Session record for grants that touch no protected path.

At production scale (about 520 Runner Session records) reading every session.yml for the history exemption cost
about 8 CPU seconds per child creation, although the exemption only decides grants that touch a protected path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from graphtraj.runtimes.claude import adapter
from graphtraj.runtimes.codex import access
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


@pytest.fixture
def history_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Count project_history_files calls while keeping its answer."""
    calls: list[Path] = []
    original = access.project_history_files

    def counted(root: Path) -> set[Path]:
        calls.append(root)
        return original(root)

    monkeypatch.setattr(access, 'project_history_files', counted)
    return calls


def associate(root: Path, native: Path) -> None:
    record = root / '.graphtraj/runner/sessions/other/session.yml'
    record.parent.mkdir(parents=True)
    record.write_text(yaml.safe_dump({'session': 'other', 'rollout_path': str(native)}))


@pytest.mark.parametrize('grants', [[], ['docs'], ['docs', 'state/records']])
def test_unprotected_grants_read_no_session_record(tmp_path: Path, history_reads: list[Path], grants: list[str]) -> None:
    home = tmp_path / 'native-home'
    home.mkdir()
    resources = [str(tmp_path / grant) for grant in grants]
    assert adapter._validated_resources(resources, tmp_path, tmp_path / 'state', home) == resources
    assert history_reads == []


def test_protected_grant_still_needs_an_associated_history(tmp_path: Path, history_reads: list[Path]) -> None:
    """The exemption and the refusals are unchanged; the history is read once for several protected grants."""
    home = tmp_path / 'native-home'
    home.mkdir()
    history, unrelated = home / 'other-agent.jsonl', home / 'unrelated.jsonl'
    history.write_text('{}\n')
    unrelated.write_text('{}\n')
    associate(tmp_path, history)
    granted = [str(tmp_path / 'docs'), str(history), str(history)]
    assert adapter._validated_resources(granted, tmp_path, tmp_path / 'state', home) == granted
    assert history_reads == [tmp_path]
    for refused in (home, unrelated, tmp_path / '.codex', Path.home() / '.codex'):
        with pytest.raises(RuntimeAdapterError, match='credentials'):
            adapter._validated_resources([str(refused)], tmp_path, tmp_path / 'state', home)
