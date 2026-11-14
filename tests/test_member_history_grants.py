"""Codex member read grants do not grow with associated Sessions (Task 465).

Members read associated Sessions through ``session_read``. Codex Main keeps
its exact per-file history grants. The integrated member launch and resume
paths are covered by test_codex_app_server.py and test_codex_approval.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import cli_directory
from graphtraj.runtimes.codex.access import member_project_reads, private_filesystem, project_history_files
from test_claude_runtime import seed_associated_histories
from test_task_graph import _configure


def member_profile(root: Path, runtime_home: Path) -> dict[str, str]:
    """Combine grants exactly as codex_adapter.py renders a member request."""
    filesystem = {}
    filesystem.update(private_filesystem(root / '.codex', str(runtime_home), history=False))
    filesystem.update(member_project_reads(root))
    return filesystem


def test_codex_member_profile_does_not_grow_with_associated_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 or 1000 associated Sessions yield the same member profile; Main lists them all."""
    root = tmp_path / 'project'
    root.mkdir()
    _configure(root)
    codex_home = tmp_path / 'user-codex'
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    runtime_home = tmp_path / 'runtime-home'
    homes = tmp_path / 'native-homes'
    associated = seed_associated_histories(root, homes, 0, 3)
    small = member_profile(root, runtime_home)
    associated += seed_associated_histories(root, homes, 3, 997)
    assert set(associated) <= project_history_files(root)
    large = member_profile(root, runtime_home)

    assert large == small
    assert not any(str(path) in large for path in associated)
    assert not any(key.endswith('.jsonl') for key in large)
    for protected in (codex_home.resolve(), runtime_home.resolve(), root / '.codex'):
        assert large[str(protected)] == 'none'
    assert large[str(cli_directory(root))] == 'none'

    # Codex Main is out of scope and keeps one exact grant per associated file.
    main = private_filesystem(root / '.codex')
    assert all(main[str(path)] == 'read' for path in associated)
    assert main[str(codex_home.resolve())] == 'none'
